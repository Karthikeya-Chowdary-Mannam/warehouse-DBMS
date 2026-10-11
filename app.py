"""Flask interface for the Warehouse Management System PostgreSQL schema."""
import base64
import json
import os
from datetime import date, datetime
from decimal import Decimal

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import MetaData, Table, and_, create_engine, func, inspect, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "local-development-key-change-me")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/warehouse")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
metadata = MetaData()

TABLES = [
    "manager", "warehouse", "employee", "users", "supplier", "customer",
    "product_category", "product", "inventory", "purchase_order",
    "purchase_order_item", "sales_order", "sales_order_item", "delivery",
    "payment", "return", "stock_transfer",
]
GROUPS = {
    "People & Places": ["manager", "warehouse", "employee", "users", "supplier", "customer"],
    "Catalog & Stock": ["product_category", "product", "inventory"],
    "Purchasing": ["purchase_order", "purchase_order_item"],
    "Sales & Fulfilment": ["sales_order", "sales_order_item", "delivery", "payment", "return"],
    "Warehouse Operations": ["stock_transfer"],
}
LABELS = {"users": "User Accounts", "product_category": "Product Categories",
          "purchase_order": "Purchase Orders", "purchase_order_item": "Purchase Order Items",
          "sales_order": "Sales Orders", "sales_order_item": "Sales Order Items",
          "stock_transfer": "Stock Transfers"}


def label(name):
    return LABELS.get(name, name.replace("_", " ").title())


def table_for(name):
    if name not in TABLES:
        abort(404)
    try:
        return Table(name, metadata, autoload_with=engine)
    except SQLAlchemyError:
        abort(503, "Database schema is unavailable. Run schema.sql and configure DATABASE_URL.")


def pk_columns(table):
    return list(table.primary_key.columns)


def encode_key(row, table):
    vals = [str(row[c.name]) for c in pk_columns(table)]
    return base64.urlsafe_b64encode(json.dumps(vals).encode()).decode().rstrip("=")


def decode_key(key, table):
    try:
        values = json.loads(base64.urlsafe_b64decode(key + "=" * (-len(key) % 4)))
        cols = pk_columns(table)
        if len(values) != len(cols):
            raise ValueError()
        converted = []
        for col, value in zip(cols, values):
            typ = col.type.__class__.__name__.lower()
            if "int" in typ:
                value = int(value)
            elif any(x in typ for x in ("numeric", "float", "decimal")):
                value = Decimal(value)
            converted.append(col == value)
        return and_(*converted)
    except Exception:
        abort(404)


def ref_options(column):
    fk = next(iter(column.foreign_keys), None)
    if not fk:
        return None
    target = fk.column.table
    pk = list(target.primary_key.columns)[0]
    display = next((target.c[n] for n in ("name", "product_name", "category_name", "username") if n in target.c), pk)
    with engine.connect() as conn:
        return [(str(row[0]), f"{row[0]} — {row[1]}") for row in conn.execute(select(pk, display).order_by(display)).all()]


def form_fields(table, row=None):
    fields = []
    pks = set(pk_columns(table))
    for col in table.columns:
        if col in pks and col.autoincrement is True:
            continue
        if col.computed is not None or col.identity is not None:
            continue
        options = ref_options(col)
        typ = col.type.__class__.__name__.lower()
        if options is not None:
            kind = "select"
        elif "date" in typ and "time" not in typ:
            kind = "date"
        elif "time" in typ:
            kind = "datetime-local"
        elif "bool" in typ:
            kind = "checkbox"
        elif "text" in typ:
            kind = "textarea"
        elif any(x in typ for x in ("int", "numeric", "float", "decimal")):
            kind = "number"
        else:
            kind = "text"
        value = row[col.name] if row is not None else (col.default.arg if col.default and not callable(col.default.arg) else "")
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = str(value)
        fields.append({"name": col.name, "label": col.name.replace("_", " ").title(),
                       "kind": kind, "value": value or "", "required": not col.nullable and col.default is None and col.server_default is None,
                       "options": options, "step": "any" if "numeric" in typ or "float" in typ or "decimal" in typ else "1"})
    return fields


def parse_form(table):
    data = {}
    pks = set(pk_columns(table))
    for col in table.columns:
        if col in pks and col.autoincrement is True or col.computed is not None or col.identity is not None:
            continue
        raw = request.form.get(col.name, "")
        if raw == "":
            if col.nullable or col.default is not None or col.server_default is not None:
                continue
            raise ValueError(f"{col.name.replace('_', ' ').title()} is required.")
        typ = col.type.__class__.__name__.lower()
        if "bool" in typ:
            data[col.name] = raw.lower() in ("1", "true", "on", "yes")
        elif "int" in typ:
            data[col.name] = int(raw)
        elif any(x in typ for x in ("numeric", "float", "decimal")):
            data[col.name] = Decimal(raw)
        elif "date" in typ and "time" not in typ:
            data[col.name] = date.fromisoformat(raw)
        elif "time" in typ:
            data[col.name] = datetime.fromisoformat(raw)
        else:
            data[col.name] = raw.strip()
    return data


@app.context_processor
def inject_navigation():
    return {"groups": GROUPS, "table_label": label, "current_table": request.view_args.get("table") if request.view_args else None,
            "now_label": datetime.now().strftime("%d %b %Y")}


@app.get("/")
def index():
    stats, low = {}, []
    try:
        with engine.connect() as conn:
            for name in ("warehouse", "employee", "supplier", "customer", "product", "sales_order", "purchase_order"):
                stats[name] = conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one()
            low = conn.execute(text("SELECT warehouse_name, product_name, quantity_on_hand, reorder_level, stock_class FROM low_stock ORDER BY quantity_on_hand, product_name LIMIT 8")).mappings().all()
    except SQLAlchemyError as exc:
        flash("Could not connect to PostgreSQL. Set DATABASE_URL and run schema.sql.", "error")
    return render_template("dashboard.html", stats=stats, low=low)


@app.get("/inventory/low-stock")
def low_stock():
    try:
        with engine.connect() as conn:
            records = conn.execute(text("SELECT * FROM low_stock ORDER BY stock_class, warehouse_name, product_name")).mappings().all()
    except SQLAlchemyError:
        records = []
        flash("Low stock view is unavailable. Run schema.sql first.", "error")
    return render_template("low_stock.html", records=records)


@app.get("/data/<table>")
def list_data(table):
    t = table_for(table)
    q = request.args.get("q", "").strip()
    classify = request.args.get("class", "")
    stmt = select(t)
    text_cols = [c for c in t.columns if c.type.__class__.__name__.lower() in ("text", "varchar", "string")]
    if q and text_cols:
        stmt = stmt.where(or_(*[c.ilike(f"%{q}%") for c in text_cols]))
    class_col = next((c for c in t.columns if c.name in ("status", "category_id", "warehouse_id", "stock_class")), None)
    classes = []
    if class_col is not None:
        with engine.connect() as conn:
            classes = [str(r[0]) for r in conn.execute(select(class_col).distinct().where(class_col.is_not(None)).order_by(class_col)).all()]
        if classify:
            stmt = stmt.where(class_col == classify)
    stmt = stmt.order_by(*pk_columns(t)).limit(500)
    try:
        with engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(stmt)]
    except SQLAlchemyError as exc:
        rows = []
        flash(f"Could not load {label(table)}: {exc}", "error")
    columns = list(t.columns)
    display_columns = columns[:7]
    return render_template("table.html", table=table, title=label(table), rows=rows, columns=columns,
                           display_columns=display_columns, q=q, classify=classify, classes=classes,
                           key_for=lambda row: encode_key(row, t), total=len(rows), truncated=len(rows) == 500)


@app.route("/data/<table>/new", methods=["GET", "POST"])
def create_data(table):
    t = table_for(table)
    fields = form_fields(t)
    if request.method == "POST":
        try:
            values = parse_form(t)
            with engine.begin() as conn:
                conn.execute(t.insert().values(**values))
            flash(f"{label(table)} record created.", "success")
            return redirect(url_for("list_data", table=table))
        except (ValueError, TypeError, IntegrityError, SQLAlchemyError) as exc:
            flash(f"Could not save record: {exc}", "error")
            fields = form_fields(t)
            for field in fields:
                field["value"] = request.form.get(field["name"], "")
    return render_template("form.html", table=table, title=f"Add {label(table)}", fields=fields, action="Create record")


@app.route("/data/<table>/<key>/edit", methods=["GET", "POST"])
def edit_data(table, key):
    t = table_for(table)
    where = decode_key(key, t)
    with engine.connect() as conn:
        row = conn.execute(select(t).where(where)).mappings().first()
    if row is None:
        abort(404)
    fields = form_fields(t, row)
    if request.method == "POST":
        try:
            values = parse_form(t)
            with engine.begin() as conn:
                conn.execute(t.update().where(where).values(**values))
            flash(f"{label(table)} record updated.", "success")
            return redirect(url_for("list_data", table=table))
        except (ValueError, TypeError, IntegrityError, SQLAlchemyError) as exc:
            flash(f"Could not update record: {exc}", "error")
            fields = form_fields(t, row)
            for field in fields:
                field["value"] = request.form.get(field["name"], "")
    return render_template("form.html", table=table, title=f"Edit {label(table)}", fields=fields, action="Save changes")


@app.post("/data/<table>/<key>/delete")
def delete_data(table, key):
    t = table_for(table)
    try:
        with engine.begin() as conn:
            result = conn.execute(t.delete().where(decode_key(key, t)))
        flash("Record deleted." if result.rowcount else "Record was not found.", "success")
    except IntegrityError:
        flash("This record is still referenced by other data. Remove or reassign those records first.", "error")
    except SQLAlchemyError as exc:
        flash(f"Could not delete record: {exc}", "error")
    return redirect(url_for("list_data", table=table))


@app.errorhandler(503)
def unavailable(error):
    return render_template("error.html", code=503, message=str(error.description)), 503


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
