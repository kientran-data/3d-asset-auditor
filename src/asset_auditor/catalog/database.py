"""SQLite database initialization and connection management."""
import sqlite3
from contextlib import contextmanager
from .schema import SCHEMA_V1, SCHEMA_V2_ANALYSIS


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(SCHEMA_V1)
            conn.executescript(SCHEMA_V2_ANALYSIS)

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()
