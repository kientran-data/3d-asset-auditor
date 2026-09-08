"""SQLite database initialization and connection management."""
import sqlite3
from contextlib import contextmanager
from .schema import SCHEMA_V1, SCHEMA_V2_ANALYSIS, SCHEMA_V3_PHASE3A, SCHEMA_V4_PHASE3B, SCHEMA_V5_PHASE4A, SCHEMA_V6_PHASE4B2

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SCHEMA_V1)
            conn.executescript(SCHEMA_V2_ANALYSIS)
            self._migrate_phase3a(conn)
            self._migrate_phase3b(conn)
            self._migrate_phase4a(conn)
            self._migrate_phase4b2(conn)
            
    def _migrate_phase3a(self, conn: sqlite3.Connection):
        """Idempotent migration for Phase 3A."""
        # 1. Add deep_analysis_status to assets
        cursor = conn.execute("PRAGMA table_info(assets)")
        columns = [row[1] for row in cursor.fetchall()]
        if "deep_analysis_status" not in columns:
            conn.execute("ALTER TABLE assets ADD COLUMN deep_analysis_status TEXT NOT NULL DEFAULT 'PENDING'")
            
            # Initialize existing ones
            conn.execute("""
                UPDATE assets 
                SET deep_analysis_status = 
                    CASE 
                        WHEN LOWER(extension) IN ('.glb', '.gltf') THEN 'PENDING'
                        WHEN format_status = 'UNSUPPORTED_FORMAT' THEN 'UNSUPPORTED_FORMAT'
                        ELSE 'SUPPORTED_LATER'
                    END
            """)

        # 2. Add analysis_profile to analysis_runs
        cursor = conn.execute("PRAGMA table_info(analysis_runs)")
        columns = [row[1] for row in cursor.fetchall()]
        if "analysis_profile" not in columns:
            conn.execute("ALTER TABLE analysis_runs ADD COLUMN analysis_profile TEXT NOT NULL DEFAULT 'BASIC'")
        
        # 3. Create new Phase 3A tables
        conn.executescript(SCHEMA_V3_PHASE3A)

    def _migrate_phase3b(self, conn: sqlite3.Connection):
        """Idempotent migration for Phase 3B."""
        conn.executescript(SCHEMA_V4_PHASE3B)

    def _migrate_phase4a(self, conn: sqlite3.Connection):
        """Idempotent migration for Phase 4A."""
        conn.executescript(SCHEMA_V5_PHASE4A)

    def _migrate_phase4b2(self, conn: sqlite3.Connection):
        """Idempotent migration for Phase 4B.2."""
        conn.executescript(SCHEMA_V6_PHASE4B2)
        # Add subject_type / subject_key to assessment_issues if missing
        cursor = conn.execute("PRAGMA table_info(assessment_issues)")
        columns = [row[1] for row in cursor.fetchall()]
        if "subject_type" not in columns:
            conn.execute("ALTER TABLE assessment_issues ADD COLUMN subject_type TEXT")
            conn.execute("ALTER TABLE assessment_issues ADD COLUMN subject_key TEXT")

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()
