import os
import sqlite3
import sys

# Ensure src is in python path
sys.path.insert(0, os.path.abspath('src'))

from asset_auditor.catalog.database import Database
from asset_auditor.catalog.repository import AssetRepository
from asset_auditor.scanner.scanner import Scanner
from asset_auditor.analyzer.dispatcher import run_batch_analysis

def test_deep_pipeline():
    db_path = "/tmp/test_deep.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    
    # 1. Init DB
    db = Database(db_path)
    
    # 2. Scan temp dir with tiny fixture
    fixture_dir = "/tmp"
    with db.get_connection() as conn:
        repo = AssetRepository(conn)
        scanner = Scanner(fixture_dir, repo)
        
        # Mock scanner to only process tiny_fixture
        conn.execute("BEGIN")
        # Just scan normally, but it might pick up other things in /tmp. Let's make a clean dir
        conn.execute("COMMIT")
        
def run_clean_test():
    import shutil
    clean_dir = "/tmp/asset_fixture_test"
    if os.path.exists(clean_dir):
        shutil.rmtree(clean_dir)
    os.makedirs(clean_dir)
    
    # copy tiny glb
    import subprocess
    subprocess.run(["cp", "/tmp/tiny_fixture.glb", os.path.join(clean_dir, "tiny_fixture.glb")], check=True)
    
    db_path = os.path.join(clean_dir, "catalog.db")
    db = Database(db_path)
    
    with db.get_connection() as conn:
        repo = AssetRepository(conn)
        scanner = Scanner(clean_dir, repo)
        conn.execute("BEGIN")
        scanner.scan()
        conn.execute("COMMIT")
        
        # 3. Run BASIC Analysis
        print("Running BASIC analysis...")
        stats = run_batch_analysis(conn, timeout=60, deep=False)
        print("BASIC stats:", stats)
        
        # 4. Run DEEP Analysis
        print("Running DEEP analysis...")
        stats_deep = run_batch_analysis(conn, timeout=60, deep=True)
        print("DEEP stats:", stats_deep)
        
        # 5. Verify Database contents
        print("Verifying database contents...")
        cur = conn.cursor()
        
        cur.execute("SELECT asset_id, analysis_status, deep_analysis_status FROM assets")
        asset = cur.fetchone()
        print("Asset Statuses:", asset)
        assert asset[1] == "SUCCESS", "analysis_status should be SUCCESS"
        assert asset[2] == "SUCCESS", "deep_analysis_status should be SUCCESS"
        
        asset_id = asset[0]
        
        # Check Analysis Runs
        cur.execute("SELECT analysis_profile, status FROM analysis_runs WHERE asset_id = ?", (asset_id,))
        runs = cur.fetchall()
        print("Runs:", runs)
        assert len(runs) == 2, "Should have 1 basic and 1 deep run"
        
        # Check Materials
        cur.execute("SELECT material_name, principled_bsdf_count FROM asset_materials WHERE asset_id = ?", (asset_id,))
        mats = cur.fetchall()
        print("Materials:", mats)
        
        # Check Images
        cur.execute("SELECT image_name, resource_status FROM asset_images WHERE asset_id = ?", (asset_id,))
        imgs = cur.fetchall()
        print("Images:", imgs)
        
        # Check Textures
        cur.execute("SELECT texture_role, uv_mapping_source, uv_map_name FROM asset_material_textures WHERE asset_id = ?", (asset_id,))
        texs = cur.fetchall()
        print("Textures:", texs)
        roles = [t[0] for t in texs]
        assert "BASE_COLOR" in roles, "Missing BASE_COLOR"
        assert "ROUGHNESS" in roles, "Missing ROUGHNESS"
        assert "NORMAL" in roles, "Missing NORMAL"
        
        # Check UVs
        cur.execute("SELECT active_uv_layer, has_uv FROM asset_uv_summary WHERE asset_id = ?", (asset_id,))
        uvs = cur.fetchall()
        print("UVs:", uvs)
        
        # Check Mesh Materials
        cur.execute("SELECT object_name, material_slot_index FROM asset_mesh_materials WHERE asset_id = ?", (asset_id,))
        mesh_mats = cur.fetchall()
        print("Mesh Materials:", mesh_mats)
        
        print("ALL GREEN!")

if __name__ == "__main__":
    run_clean_test()
