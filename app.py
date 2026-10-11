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

        value = row[col.name] if row is not None else ""
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = str(value)

        has_database_default = col.default is not None or col.server_default is not None

        fields.append({
            "name": col.name,
            "label": col.name.replace("_", " ").title(),
            "kind": kind,
            "value": "" if value is None else value,
            # Defaults are supplied by PostgreSQL/Python; unchecked boxes mean False.
            "required": not has_database_default and kind != "checkbox",
            "options": options,
            "step": (
                "any"
                if any(x in typ for x in ("numeric", "float", "decimal"))
                else "1"
            ),
        })

    return fields


def parse_form(table):
    data = {}
    pks = set(pk_columns(table))

    for col in table.columns:
        if (
            (col in pks and col.autoincrement is True)
            or col.computed is not None
            or col.identity is not None
        ):
            continue

        typ = col.type.__class__.__name__.lower()

        # Unchecked HTML checkboxes are omitted from the form.
        if "bool" in typ:
            raw = request.form.get(col.name)
            data[col.name] = raw is not None and raw.lower() in (
                "1", "true", "on", "yes"
            )
            continue

        raw = request.form.get(col.name, "").strip()

        if raw == "":
            # Let the database apply its default. Otherwise, reject blanks,
            # including for columns PostgreSQL permits to be NULL.
            if col.default is not None or col.server_default is not None:
                continue
            raise ValueError(
                f"{col.name.replace('_', ' ').title()} is required."
            )
        if col.name == "phone" and (len(raw) != 10 or not raw.isascii() or not raw.isdigit()):
            raise ValueError("Phone number must contain exactly 10 digits.")

        if "int" in typ:
            data[col.name] = int(raw)
        elif any(x in typ for x in ("numeric", "float", "decimal")):
            data[col.name] = Decimal(raw)
        elif "date" in typ and "time" not in typ:
            data[col.name] = date.fromisoformat(raw)
        elif "time" in typ:
            data[col.name] = datetime.fromisoformat(raw)
        else:
            data[col.name] = raw

    return data
