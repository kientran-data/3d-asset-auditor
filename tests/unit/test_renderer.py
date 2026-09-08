import os
import sqlite3
import unittest
from unittest.mock import patch, MagicMock

from asset_auditor.renderer.dispatcher import run_render, recover_stale_renders

class TestRendererUnit(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript("""
            CREATE TABLE assets (
                asset_id TEXT PRIMARY KEY,
                is_present INTEGER,
                analysis_status TEXT,
                extension TEXT,
                file_size_bytes INTEGER,
                modified_time_ns INTEGER,
                preview_status TEXT
            );
            CREATE TABLE asset_previews (
                preview_id TEXT PRIMARY KEY,
                asset_id TEXT,
                render_run_id TEXT,
                renderer_version TEXT,
                render_schema_version TEXT,
                blender_version TEXT,
                render_engine TEXT,
                status TEXT,
                preview_type TEXT,
                output_path TEXT,
                width_px INTEGER,
                height_px INTEGER,
                file_format TEXT,
                camera_mode TEXT,
                render_settings_json TEXT,
                source_file_size_bytes INTEGER,
                source_modified_time_ns INTEGER,
                source_fingerprint TEXT,
                started_at TEXT,
                finished_at TEXT,
                duration_ms INTEGER,
                error_type TEXT,
                error_message TEXT
            );
        """)
        self.conn.execute("INSERT INTO assets VALUES ('a1', 1, 'SUCCESS', '.glb', 100, 200, 'PENDING')")
        self.conn.execute("INSERT INTO assets VALUES ('a2', 1, 'FAILED_IMPORT', '.glb', 100, 200, 'PENDING')")
        self.conn.execute("INSERT INTO assets VALUES ('a3', 1, 'SUCCESS', '.obj', 100, 200, 'PENDING')")
        self.conn.execute("INSERT INTO assets VALUES ('a4', 0, 'SUCCESS', '.glb', 100, 200, 'PENDING')")
        self.conn.commit()

    def test_recover_stale_renders(self):
        self.conn.execute("UPDATE assets SET preview_status = 'RENDERING' WHERE asset_id = 'a1'")
        self.conn.commit()
        count = recover_stale_renders(self.conn)
        self.assertEqual(count, 1)
        status = self.conn.execute("SELECT preview_status FROM assets WHERE asset_id = 'a1'").fetchone()[0]
        self.assertEqual(status, 'PENDING')

    @patch("asset_auditor.renderer.dispatcher.subprocess.run")
    def test_run_render_eligibility(self, mock_run):
        # Ineligible because analysis_status != SUCCESS
        run_render(self.conn, 'a2', '/tmp/a2.glb', '/tmp')
        mock_run.assert_not_called()
        
        # Ineligible because extension != .glb/.gltf
        run_render(self.conn, 'a3', '/tmp/a3.obj', '/tmp')
        mock_run.assert_not_called()
        
        # Ineligible because is_present != 1
        run_render(self.conn, 'a4', '/tmp/a4.glb', '/tmp')
        mock_run.assert_not_called()

if __name__ == '__main__':
    unittest.main()
