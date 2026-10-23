"""Data access for users. SQL lives here and nowhere else."""
from app.db import query


class UserRepository:
    def __init__(self, con):
        self.con = con

    def get(self, user_id):
        """The user row, or None when the id does not exist."""
        rows = query(self.con, "SELECT id, name, email, city FROM users WHERE id = ?", (user_id,))
        return rows[0] if rows else None
