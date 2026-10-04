"""CPython-only SQLite adapter and local runnable app."""


class SQLiteDatabase:
    def __init__(self, connection):
        self.connection = connection

    async def first(self, sql, *values):
        row = self.connection.execute(sql, values).fetchone()
        return dict(row) if row else None

    async def all(self, sql, *values):
        return [dict(row) for row in self.connection.execute(sql, values).fetchall()]

    async def run(self, sql, *values):
        with self.connection:
            return self.connection.execute(sql, values).rowcount

    async def batch(self, statements):
        with self.connection:
            for sql, *values in statements:
                self.connection.execute(sql, values)


def local_app():
    import os
    import sqlite3
    from pathlib import Path

    from followup.app import create_app
    from followup.security import Settings

    connection = sqlite3.connect(
        os.getenv("PILOT_SQLITE_PATH", "pilot.sqlite3"), check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE IF NOT EXISTS applied_migrations(name TEXT PRIMARY KEY)")
    for path in sorted((Path(__file__).resolve().parents[2] / "migrations").glob("*.sql")):
        if not connection.execute(
            "SELECT name FROM applied_migrations WHERE name=?", (path.name,)
        ).fetchone():
            connection.executescript(path.read_text())
            connection.execute("INSERT INTO applied_migrations VALUES (?)", (path.name,))
            connection.commit()
    return create_app(SQLiteDatabase(connection), Settings.from_env(os.environ))
