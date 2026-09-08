import os
import sqlite3
import subprocess
import unittest
from pathlib import Path

from asset_auditor.catalog.database import Database
from asset_auditor.catalog.repository import AssetRepository
from asset_auditor.scanner.scanner import Scanner
from asset_auditor.renderer.dispatcher import run_render

class TestRenderPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path("/tmp/render_test_env")
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        
        cls.models_dir = cls.test_dir / "models"
        cls.models_dir.mkdir(parents=True, exist_ok=True)
        
        cls.db_path = cls.test_dir / "catalog.db"
        
        # Create tiny fixture
        subprocess.run(["blender", "--background", "--factory-startup", "--python", "tests/integration/create_tiny_glb.py", "--", str(cls.models_dir / "tiny_fixture.glb")], check=True)
        
        # Initialize DB and scan
        if cls.db_path.exists():
            cls.db_path.unlink()
        cls.db = Database(str(cls.db_path))
        with cls.db.get_connection() as conn:
            repo = AssetRepository(conn)
            scanner = Scanner(str(cls.models_dir), repo)
            conn.execute("BEGIN")
            scanner.scan()
            conn.execute("COMMIT")
            
            # Force analysis SUCCESS for testing
            conn.execute("UPDATE assets SET analysis_status = 'SUCCESS'")
            conn.commit()

    def test_render_tiny_fixture(self):
        with self.db.get_connection() as conn:
            # Get asset id
            row = conn.execute("SELECT asset_id, absolute_path FROM assets WHERE filename = 'tiny_fixture.glb'").fetchone()
            self.assertIsNotNone(row)
            asset_id, absolute_path = row
            
            # Record mtime and size
            orig_stat = os.stat(absolute_path)
            
            # Run render
            run_render(conn, asset_id, absolute_path, str(self.models_dir), timeout=60)
            
            # Check db preview_status
            status = conn.execute("SELECT preview_status FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()[0]
            self.assertEqual(status, "SUCCESS")
            
            # Check asset_previews
            preview_row = conn.execute("SELECT preview_id, output_path, status, preview_type FROM asset_previews WHERE asset_id = ?", (asset_id,)).fetchone()
            self.assertIsNotNone(preview_row)
            
            preview_id, output_path, p_status, p_type = preview_row
            self.assertEqual(p_status, "SUCCESS")
            self.assertEqual(p_type, "HERO")
            self.assertTrue(os.path.exists(output_path))
            self.assertTrue(output_path.endswith("hero.png"))
            self.assertIn(preview_id, output_path) # immutable path includes preview_id
            
            # Verify image file
            size = os.path.getsize(output_path)
            self.assertGreater(size, 0)
            
            from PIL import Image
            with Image.open(output_path) as img:
                self.assertEqual(img.size, (1024, 1024))
                
            # Verify source unchanged
            new_stat = os.stat(absolute_path)
            self.assertEqual(orig_stat.st_size, new_stat.st_size)
            self.assertEqual(orig_stat.st_mtime_ns, new_stat.st_mtime_ns)

if __name__ == '__main__':
    unittest.main()
