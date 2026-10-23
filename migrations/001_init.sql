-- Initial schema for the demo: one table.

CREATE TABLE people (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    email   TEXT NOT NULL,
    city    TEXT NOT NULL
);
