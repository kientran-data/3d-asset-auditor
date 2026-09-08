"""Asset repository — data access layer for the assets table."""
import sqlite3
from typing import Optional, Iterable, Set
import dataclasses
from ..models import AssetRecord


class AssetRepository:
    def __init__(self, db_connection: sqlite3.Connection):
        self.conn = db_connection

    def get_by_path(self, source_root: str, absolute_path: str) -> Optional[AssetRecord]:
        """Retrieve a single asset by its unique (source_root, absolute_path) key."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM assets WHERE source_root = ? AND absolute_path = ?",
            (source_root, absolute_path),
        )
        row = cursor.fetchone()
        if row:
            return self._row_to_asset(row, cursor.description)
        return None

    def upsert_asset(self, asset: AssetRecord):
        """Insert or update an asset record using ON CONFLICT on (source_root, absolute_path)."""
        fields = [f.name for f in dataclasses.fields(AssetRecord)]
        placeholders = ", ".join(["?"] * len(fields))
        update_set = ", ".join(
            [f"{f}=excluded.{f}" for f in fields if f != "asset_id"]
        )
        sql = f"""
            INSERT INTO assets ({', '.join(fields)})
            VALUES ({placeholders})
            ON CONFLICT(source_root, absolute_path) DO UPDATE SET
            {update_set}
        """
        values = [getattr(asset, f) for f in fields]
        self.conn.execute(sql, values)

    def mark_present(self, source_root: str, absolute_path: str):
        """Mark a single asset as present (seen during scan)."""
        self.conn.execute(
            "UPDATE assets SET is_present = 1 WHERE source_root = ? AND absolute_path = ?",
            (source_root, absolute_path),
        )

    def reconcile_missing(self, source_root: str, seen_paths: Set[str]) -> int:
        """Mark assets not in seen_paths as missing. Returns count of newly missing assets.

        This is only called when the scan completed without directory errors,
        so we can be confident that unseen paths are genuinely gone.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT absolute_path FROM assets WHERE source_root = ? AND is_present = 1",
            (source_root,),
        )
        missing_count = 0
        for (path,) in cursor.fetchall():
            if path not in seen_paths:
                self.conn.execute(
                    "UPDATE assets SET is_present = 0 WHERE source_root = ? AND absolute_path = ?",
                    (source_root, path),
                )
                missing_count += 1
        return missing_count

    def get_all_assets(
        self, source_root: Optional[str] = None, present_only: bool = True
    ) -> Iterable[AssetRecord]:
        """Yield all assets, optionally filtered by source_root and presence."""
        cursor = self.conn.cursor()
        if source_root and present_only:
            cursor.execute(
                "SELECT * FROM assets WHERE source_root = ? AND is_present = 1",
                (source_root,),
            )
        elif source_root:
            cursor.execute(
                "SELECT * FROM assets WHERE source_root = ?", (source_root,)
            )
        elif present_only:
            cursor.execute("SELECT * FROM assets WHERE is_present = 1")
        else:
            cursor.execute("SELECT * FROM assets")

        for row in cursor:
            yield self._row_to_asset(row, cursor.description)

    def _row_to_asset(self, row, description) -> AssetRecord:
        col_names = [col[0] for col in description]
        data = dict(zip(col_names, row))
        data.pop("id", None)
        return AssetRecord(**data)
