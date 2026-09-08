import os
import sqlite3
from asset_auditor.analyzer.runner import run_blender_analysis
from asset_auditor.analyzer.result_parser import persist_analysis_result
from asset_auditor.catalog.database import Database

def run_test():
    fixture_path = "/tmp/tiny_fixture.glb"
    db_path = "/tmp/test_integration.db"

    # 1. File stats before
    stat_before = os.stat(fixture_path)
    size_before = stat_before.st_size
    mtime_before = stat_before.st_mtime_ns

    if os.path.exists(db_path):
        os.remove(db_path)
    
    db = Database(db_path)
    with db.get_connection() as conn:
        from asset_auditor.catalog.repository import AssetRepository
        from asset_auditor.scanner.scanner import Scanner
        repo = AssetRepository(conn)
        scanner = Scanner("/tmp", repo)
        conn.execute("BEGIN")
        scanner.scan()
        conn.execute("COMMIT")

        c = conn.cursor()
        c.execute("SELECT asset_id FROM assets WHERE filename = 'tiny_fixture.glb'")
        asset_id = c.fetchone()[0]

        # 3. Run analysis
        result = run_blender_analysis(asset_id, fixture_path, timeout=60)
        
        # 4. Verify result object
        assert result.status == "SUCCESS", f"Analysis failed: {result.error_message}, stderr: {result.stderr_tail}"
        assert result.blender_version == "4.0.2", f"Expected Blender 4.0.2, got {result.blender_version}"
        assert result.blender_exit_code == 0
        
        data = result.result_data
        assert data is not None
        assert data["scene"]["mesh_objects"] == 1
        assert data["geometry"]["vertices"] > 0
        assert data["geometry"]["faces"] > 0
        assert data["geometry"]["triangles"] > 0
        
        bbox = data["bounding_box"]
        assert bbox["width"] > 0
        assert bbox["depth"] > 0
        assert bbox["height"] > 0

        # 5. Persist to DB
        persist_analysis_result(conn, result)

        # 6. Verify DB
        c = conn.cursor()
        c.execute("SELECT status, blender_version FROM analysis_runs WHERE asset_id = ?", (asset_id,))
        row = c.fetchone()
        assert row is not None
        assert row[0] == "SUCCESS"
        assert row[1] == "4.0.2"
        
        c.execute("SELECT vertices, faces, triangles FROM asset_geometry WHERE asset_id = ?", (asset_id,))
        geo = c.fetchone()
        assert geo is not None
        assert geo[0] > 0
        assert geo[1] > 0
        assert geo[2] > 0

    # 7. File stats after
    stat_after = os.stat(fixture_path)
    size_after = stat_after.st_size
    mtime_after = stat_after.st_mtime_ns

    assert size_before == size_after, f"Size changed! Before: {size_before}, After: {size_after}"
    assert mtime_before == mtime_after, f"Mtime changed! Before: {mtime_before}, After: {mtime_after}"

    print("✅ INTEGRATION TEST PASSED")
    print(f"- Exit code: 0")
    print(f"- Status: SUCCESS")
    print(f"- Blender version: 4.0.2")
    print(f"- Vertices: {data['geometry']['vertices']}")
    print(f"- Triangles: {data['geometry']['triangles']}")
    print(f"- Source integrity verified: size={size_before}, mtime_ns={mtime_before} unchanged")

if __name__ == "__main__":
    run_test()
