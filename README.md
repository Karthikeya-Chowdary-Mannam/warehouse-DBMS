# Warehouse Desk

A Flask and PostgreSQL warehouse-management application based on the supplied **Database Design.pdf**. It provides a manager-facing dashboard and create, browse, search, classify, edit, and delete screens for every database entity. It is designed for one manager working across multiple warehouses and intentionally has no login page.

## Included data model

The schema includes Manager, Warehouse, Employee, User account, Supplier, Customer, Product Category, Product, Inventory, Purchase Order and items, Sales Order and items, Delivery, Payment, Return, and Stock Transfer. It preserves the normalized order/item structure and enforces primary keys, foreign keys, uniqueness, nonnegative amounts/quantities, order statuses, and valid warehouse transfers. The `users` table is included because the PDF's workflow says there is one login account per employee; the app does not authenticate against it.

## Setup

Requires Python 3.10+ and PostgreSQL.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
createdb warehouse
psql -d warehouse -f schema.sql
```

Run these commands from this project directory. The Flask app expects a SQLAlchemy URL in this form:

```sh
export DATABASE_URL='postgresql+psycopg://postgres:your-password@localhost:5432/warehouse'
export FLASK_SECRET_KEY='replace-with-a-random-local-secret'
flask --app app run --debug
```

Open `http://127.0.0.1:5000`. The app does not initialize the schema automatically; apply `schema.sql` first. The secret key is used for Flask sessions and flash messages, not for user login.

## Typical workflow

1. Create one Manager, then create all Warehouses under that manager. Employees are assigned to a warehouse; create a User account for each employee if you need the account records from the PDF.
2. Add product categories, products, suppliers, and customers. Create an initial Inventory row for each product/warehouse pair as needed.
3. Create a Purchase Order in Draft, add its Purchase Order Items, then change its status to Received. The database trigger adds received quantities to that warehouse's inventory and keeps the order total in sync.
4. Create a Sales Order, add Sales Order Items, then change its status to Delivered when fulfillment is complete. The database checks available inventory and deducts the order quantities. A completed order cannot be moved back to an earlier status, preventing accidental repeat movements.
5. Record deliveries and payments against the order. Record returns against a product on the sales order; returned quantities are added to the order's warehouse inventory.
6. Record Stock Transfers to move quantities. The database checks source stock, subtracts it, and adds it to the destination warehouse.

The dashboard includes business counts and a low-stock queue. Every table view supports text search; tables with status/category/warehouse columns have a classification filter. Forms use dropdowns for foreign keys. Deleting a record is blocked when other records still reference it, except purchase and sales order items cascade when their parent order is deleted.

## Notes

- PostgreSQL is the source of truth. `schema.sql` contains the relational schema, indexes, low-stock view, total-maintenance triggers, and inventory movement triggers.
- The `password_hash` fields are retained from the PDF schema. The app does not provide login or password hashing; do not enter a raw password in those fields.
- This is an internal coursework application and has no authentication or CSRF layer. Keep it bound to localhost or a trusted environment.
- Deleting or editing completed stock movement records does not reverse their inventory effects. Use a compensating transfer/return or correct the inventory record directly.
