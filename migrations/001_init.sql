-- Initial schema for the demo shop.

CREATE TABLE users (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    email   TEXT NOT NULL,
    city    TEXT NOT NULL
);

CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL
);

CREATE TABLE order_items (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    product     TEXT NOT NULL,
    qty         INTEGER NOT NULL,
    unit_price  REAL NOT NULL
);

CREATE INDEX idx_orders_created_at ON orders(created_at);
