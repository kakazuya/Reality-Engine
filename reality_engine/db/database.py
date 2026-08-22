"""
Database Engine Module
Manages SQLite connection lifecycle, PRAGMA optimization, WAL mode, and schema migrations.
"""

import sqlite3
from pathlib import Path
from typing import Optional, Generator
from contextlib import contextmanager

from reality_engine.config import DB_PATH, SQLITE_PRAGMAS


class DatabaseManager:
    """Manages high-performance SQLite connections with WAL mode and memory PRAGMAs."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Create an optimized SQLite connection with configured PRAGMAs."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        
        # Apply performance PRAGMAs
        with conn:
            for pragma in SQLITE_PRAGMAS:
                conn.execute(pragma)
                
        return conn

    @contextmanager
    def session(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager providing an auto-committing or rolling back SQLite connection."""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initializes tables, indices, and views from schema.sql."""
        schema_file = Path(__file__).parent / "schema.sql"
        if not schema_file.exists():
            raise FileNotFoundError(f"Schema file not found at {schema_file}")

        with open(schema_file, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        with self.session() as conn:
            conn.executescript(schema_sql)
            self._apply_runtime_migrations(conn)

    def _apply_runtime_migrations(self, conn: sqlite3.Connection) -> None:
        """Idempotent ALTER TABLE migrations for pre-existing databases."""
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(telegram_posts)").fetchall()}
            if cols and "button_links_json" not in cols:
                conn.execute("ALTER TABLE telegram_posts ADD COLUMN button_links_json TEXT")
        except Exception as exc:
            # Table may not exist yet (fresh DB handled by schema.sql); ignore.
            pass

    def vacuum(self) -> None:
        """Optimizes and re-indexes the SQLite database."""
        with self.session() as conn:
            conn.execute("PRAGMA optimize;")


# Global singleton instance
db_manager = DatabaseManager()
