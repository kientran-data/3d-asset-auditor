"""Comprehensive Phase 1 test suite.

All tests use temporary directories with dummy zero-byte 3D files.
Phase 1 never parses model contents so dummy files are sufficient.
"""
import csv
import json
import os
import sqlite3
import stat
import tempfile
import time

import pytest
from pathlib import Path

from asset_auditor.catalog.database import Database
from asset_auditor.catalog.repository import AssetRepository
from asset_auditor.scanner.scanner import Scanner
from asset_auditor.scanner.formats import (
    get_format_status,
    FormatStatus,
    initial_analysis_status,
    MVP_FORMATS,
    LATER_FORMATS,
    UNSUPPORTED_FORMATS,
)
from asset_auditor.scanner.fingerprint import create_fingerprint
from asset_auditor.exporters.csv_exporter import export_to_csv
from asset_auditor.exporters.json_exporter import export_to_json


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_env():
    """Provide a temp directory with db_path and source_root."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        source_root = os.path.join(temp_dir, "models")
        os.makedirs(source_root)
        yield temp_dir, db_path, source_root


def _scan(db_path, source_root):
    """Helper: run a full scan and return (stats, repo, conn)."""
    db = Database(db_path)
    conn = sqlite3.connect(db_path)
    repo = AssetRepository(conn)
    scanner = Scanner(source_root, repo)
    conn.execute("BEGIN")
    stats = scanner.scan()
    conn.execute("COMMIT")
    return stats, repo, conn


# ---------------------------------------------------------------------------
# 1. Empty directory
# ---------------------------------------------------------------------------

class TestEmptyDirectory:
    def test_zero_assets(self, temp_env):
        _, db_path, source_root = temp_env
        stats, repo, conn = _scan(db_path, source_root)
        assert stats["total_3d_assets"] == 0
        assert stats["new"] == 0
        assert list(repo.get_all_assets(source_root)) == []
        conn.close()


# ---------------------------------------------------------------------------
# 2. Single .blend asset
# ---------------------------------------------------------------------------

class TestSingleBlend:
    def test_one_blend(self, temp_env):
        _, db_path, source_root = temp_env
        Path(source_root, "wheel.blend").touch()
        stats, repo, conn = _scan(db_path, source_root)
        assert stats["total_3d_assets"] == 1
        assert stats["new"] == 1
        assets = list(repo.get_all_assets(source_root))
        assert len(assets) == 1
        a = assets[0]
        assert a.extension == ".blend"
        assert a.format_status == "MVP_SUPPORTED"
        assert a.scan_status == "SUCCESS"
        assert a.analysis_status == "PENDING"
        assert a.preview_status == "PENDING"
        assert a.assessment_status == "PENDING"
        conn.close()


# ---------------------------------------------------------------------------
# 3. Mixed recognized formats
# ---------------------------------------------------------------------------

class TestMixedFormats:
    def test_counts(self, temp_env):
        _, db_path, source_root = temp_env
        Path(source_root, "a.blend").touch()
        Path(source_root, "b.fbx").touch()
        Path(source_root, "c.obj").touch()
        Path(source_root, "d.glb").touch()
        Path(source_root, "e.gltf").touch()
        Path(source_root, "f.stl").touch()
        Path(source_root, "g.max").touch()
        Path(source_root, "h.c4d").touch()
        Path(source_root, "i.ply").touch()
        Path(source_root, "j.dae").touch()
        Path(source_root, "k.3ds").touch()
        Path(source_root, "readme.txt").touch()
        stats, repo, conn = _scan(db_path, source_root)
        assert stats["total_3d_assets"] == 11
        assert stats["non_3d_files"] == 1
        assert stats["capabilities"]["MVP_SUPPORTED"] == 6
        assert stats["capabilities"]["SUPPORTED_LATER"] == 3
        assert stats["capabilities"]["UNSUPPORTED_FORMAT"] == 2
        conn.close()


# ---------------------------------------------------------------------------
# 4. Case-insensitive extensions
# ---------------------------------------------------------------------------

class TestCaseInsensitive:
    def test_mixed_case(self, temp_env):
        _, db_path, source_root = temp_env
        Path(source_root, "MODEL.FBX").touch()
        Path(source_root, "wheel.BlEnD").touch()
        Path(source_root, "mesh.Stl").touch()
        stats, repo, conn = _scan(db_path, source_root)
        assert stats["total_3d_assets"] == 3
        assert stats["formats"]["FBX"] == 1
        assert stats["formats"]["BLEND"] == 1
        assert stats["formats"]["STL"] == 1
        conn.close()


# ---------------------------------------------------------------------------
# 5. Path containing spaces
# ---------------------------------------------------------------------------

class TestSpacesInPath:
    def test_spaces(self, temp_env):
        _, db_path, source_root = temp_env
        spaced = os.path.join(source_root, "my models", "sub folder")
        os.makedirs(spaced)
        Path(spaced, "cool model.blend").touch()
        stats, repo, conn = _scan(db_path, source_root)
        assert stats["total_3d_assets"] == 1
        a = list(repo.get_all_assets(source_root))[0]
        assert "my models" in a.relative_path
        assert a.filename == "cool model.blend"
        conn.close()


# ---------------------------------------------------------------------------
# 6. Unicode directories and filenames
# ---------------------------------------------------------------------------

class TestUnicode:
    def test_unicode_paths(self, temp_env):
        _, db_path, source_root = temp_env
        uni_dir = os.path.join(source_root, "Lenkräder", "Spëcial–Chars")
        os.makedirs(uni_dir)
        Path(uni_dir, "Brücke_Modèll.fbx").touch()
        stats, repo, conn = _scan(db_path, source_root)
        assert stats["total_3d_assets"] == 1
        a = list(repo.get_all_assets(source_root))[0]
        assert "Lenkräder" in a.relative_path
        assert a.filename == "Brücke_Modèll.fbx"
        conn.close()


# ---------------------------------------------------------------------------
# 7. Nested directories
# ---------------------------------------------------------------------------

class TestNestedDirectories:
    def test_deep_nesting(self, temp_env):
        _, db_path, source_root = temp_env
        deep = os.path.join(source_root, "A", "B", "C", "D")
        os.makedirs(deep)
        Path(deep, "deep.blend").touch()
        Path(os.path.join(source_root, "A"), "shallow.obj").touch()
        stats, repo, conn = _scan(db_path, source_root)
        assert stats["total_3d_assets"] == 2
        assets = {a.filename: a for a in repo.get_all_assets(source_root)}
        assert assets["deep.blend"].directory_depth == 4
        assert assets["shallow.obj"].directory_depth == 1
        conn.close()


# ---------------------------------------------------------------------------
# 8–11. Path semantics: relative_path, parent_directory, top_level_directory, directory_depth
# ---------------------------------------------------------------------------

class TestPathSemantics:
    def test_all_path_fields(self, temp_env):
        _, db_path, source_root = temp_env
        nested = os.path.join(source_root, "BMW", "M3", "interior")
        os.makedirs(nested)
        Path(nested, "wheel.blend").touch()
        stats, repo, conn = _scan(db_path, source_root)
        a = list(repo.get_all_assets(source_root))[0]
        assert a.relative_path == os.path.join("BMW", "M3", "interior", "wheel.blend")
        assert a.parent_directory == "interior"
        assert a.top_level_directory == "BMW"
        assert a.directory_depth == 3
        assert a.filename == "wheel.blend"
        assert a.stem == "wheel"
        assert a.extension == ".blend"
        conn.close()

    def test_root_level_file(self, temp_env):
        """A file directly in source_root has depth 0 and empty directory fields."""
        _, db_path, source_root = temp_env
        Path(source_root, "root.obj").touch()
        stats, repo, conn = _scan(db_path, source_root)
        a = list(repo.get_all_assets(source_root))[0]
        assert a.directory_depth == 0
        assert a.top_level_directory == ""
        assert a.parent_directory == ""
        assert a.relative_path == "root.obj"
        conn.close()


# ---------------------------------------------------------------------------
# 12–16. Format status classification
# ---------------------------------------------------------------------------

class TestFormatClassification:
    def test_max_unsupported(self, temp_env):
        _, db_path, source_root = temp_env
        Path(source_root, "scene.max").touch()
        stats, repo, conn = _scan(db_path, source_root)
        a = list(repo.get_all_assets(source_root))[0]
        assert a.format_status == "UNSUPPORTED_FORMAT"
        assert a.analysis_status == "UNSUPPORTED_FORMAT"
        conn.close()

    def test_c4d_unsupported(self, temp_env):
        _, db_path, source_root = temp_env
        Path(source_root, "scene.c4d").touch()
        stats, repo, conn = _scan(db_path, source_root)
        a = list(repo.get_all_assets(source_root))[0]
        assert a.format_status == "UNSUPPORTED_FORMAT"
        assert a.analysis_status == "UNSUPPORTED_FORMAT"
        conn.close()

    def test_ply_supported_later(self, temp_env):
        _, db_path, source_root = temp_env
        Path(source_root, "cloud.ply").touch()
        stats, repo, conn = _scan(db_path, source_root)
        a = list(repo.get_all_assets(source_root))[0]
        assert a.format_status == "SUPPORTED_LATER"
        assert a.analysis_status == "SUPPORTED_LATER"
        conn.close()

    def test_dae_supported_later(self, temp_env):
        _, db_path, source_root = temp_env
        Path(source_root, "scene.dae").touch()
        stats, repo, conn = _scan(db_path, source_root)
        a = list(repo.get_all_assets(source_root))[0]
        assert a.format_status == "SUPPORTED_LATER"
        assert a.analysis_status == "SUPPORTED_LATER"
        conn.close()

    def test_3ds_supported_later(self, temp_env):
        _, db_path, source_root = temp_env
        Path(source_root, "old.3ds").touch()
        stats, repo, conn = _scan(db_path, source_root)
        a = list(repo.get_all_assets(source_root))[0]
        assert a.format_status == "SUPPORTED_LATER"
        assert a.analysis_status == "SUPPORTED_LATER"
        conn.close()


# ---------------------------------------------------------------------------
# 17. Non-3D files excluded
# ---------------------------------------------------------------------------

class TestNon3DExclusion:
    def test_non_3d_not_in_db(self, temp_env):
        _, db_path, source_root = temp_env
        Path(source_root, "readme.txt").touch()
        Path(source_root, "texture.png").touch()
        Path(source_root, "archive.zip").touch()
        Path(source_root, "notes.pdf").touch()
        Path(source_root, "model.blend").touch()
        stats, repo, conn = _scan(db_path, source_root)
        assert stats["total_3d_assets"] == 1
        assert stats["non_3d_files"] == 4
        assets = list(repo.get_all_assets(source_root))
        assert len(assets) == 1
        assert assets[0].filename == "model.blend"
        conn.close()


# ---------------------------------------------------------------------------
# 18–22. Rescan behavior
# ---------------------------------------------------------------------------

class TestRescanUnchanged:
    def test_preserves_asset_id_and_counts_unchanged(self, temp_env):
        _, db_path, source_root = temp_env
        Path(source_root, "a.blend").touch()
        Path(source_root, "b.fbx").touch()
        Path(source_root, "c.obj").touch()

        stats1, repo1, conn1 = _scan(db_path, source_root)
        assert stats1["new"] == 3
        ids1 = {a.filename: a.asset_id for a in repo1.get_all_assets(source_root)}
        conn1.close()

        stats2, repo2, conn2 = _scan(db_path, source_root)
        assert stats2["new"] == 0
        assert stats2["unchanged"] == 3
        assert stats2["changed"] == 0
        ids2 = {a.filename: a.asset_id for a in repo2.get_all_assets(source_root)}
        assert ids1 == ids2
        conn2.close()


class TestRescanChanged:
    def test_changed_preserves_id_resets_downstream(self, temp_env):
        _, db_path, source_root = temp_env
        fp = Path(source_root, "model.blend")
        fp.touch()

        stats1, repo1, conn1 = _scan(db_path, source_root)
        original_id = list(repo1.get_all_assets(source_root))[0].asset_id
        conn1.close()

        # Modify the file (changes both size and mtime)
        time.sleep(0.05)
        fp.write_text("new content changes fingerprint")

        stats2, repo2, conn2 = _scan(db_path, source_root)
        assert stats2["changed"] == 1
        assert stats2["new"] == 0
        a = list(repo2.get_all_assets(source_root))[0]
        assert a.asset_id == original_id  # ID preserved
        assert a.analysis_status == "PENDING"
        assert a.preview_status == "PENDING"
        assert a.assessment_status == "PENDING"
        conn2.close()


# ---------------------------------------------------------------------------
# 23–24. Removed file handling
# ---------------------------------------------------------------------------

class TestRemovedFile:
    def test_removed_not_deleted_marked_missing(self, temp_env):
        _, db_path, source_root = temp_env
        fp = Path(source_root, "model.blend")
        fp.touch()

        stats1, repo1, conn1 = _scan(db_path, source_root)
        original_id = list(repo1.get_all_assets(source_root))[0].asset_id
        conn1.close()

        fp.unlink()

        stats2, repo2, conn2 = _scan(db_path, source_root)
        assert stats2["missing"] == 1

        # Verify record still exists
        cursor = conn2.cursor()
        cursor.execute("SELECT is_present, asset_id FROM assets WHERE asset_id = ?", (original_id,))
        row = cursor.fetchone()
        assert row is not None, "Historical record must NOT be deleted"
        assert row[0] == 0, "is_present must be 0"
        assert row[1] == original_id

        # Present-only query should exclude it
        present = list(repo2.get_all_assets(source_root, present_only=True))
        assert len(present) == 0

        # All query should include it
        all_assets = list(repo2.get_all_assets(source_root, present_only=False))
        assert len(all_assets) == 1
        conn2.close()


# ---------------------------------------------------------------------------
# 25. CSV export validation
# ---------------------------------------------------------------------------

class TestCSVExport:
    def test_csv_content(self, temp_env):
        temp_dir, db_path, source_root = temp_env
        Path(source_root, "a.blend").touch()
        Path(source_root, "b.max").touch()
        csv_path = os.path.join(temp_dir, "out.csv")

        stats, repo, conn = _scan(db_path, source_root)
        assets = list(repo.get_all_assets(source_root))
        export_to_csv(assets, csv_path)
        conn.close()

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        filenames = {r["filename"] for r in rows}
        assert filenames == {"a.blend", "b.max"}
        assert "asset_id" in rows[0]
        assert "source_root" in rows[0]


# ---------------------------------------------------------------------------
# 26–27. JSON export validation
# ---------------------------------------------------------------------------

class TestJSONExport:
    def test_json_structure(self, temp_env):
        temp_dir, db_path, source_root = temp_env
        Path(source_root, "a.blend").touch()
        json_path = os.path.join(temp_dir, "out.json")

        stats, repo, conn = _scan(db_path, source_root)
        assets = list(repo.get_all_assets(source_root))
        export_to_json(assets, source_root, stats, json_path)
        conn.close()

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        assert "schema_version" in data
        assert "generated_at" in data
        assert "source_root" in data
        assert "summary" in data
        assert "assets" in data
        assert len(data["assets"]) == 1

    def test_json_preserves_unicode(self, temp_env):
        temp_dir, db_path, source_root = temp_env
        uni_dir = os.path.join(source_root, "Lenkräder")
        os.makedirs(uni_dir)
        Path(uni_dir, "Brücke.fbx").touch()
        json_path = os.path.join(temp_dir, "out.json")

        stats, repo, conn = _scan(db_path, source_root)
        assets = list(repo.get_all_assets(source_root))
        export_to_json(assets, source_root, stats, json_path)
        conn.close()

        raw = Path(json_path).read_text(encoding="utf-8")
        assert "Lenkräder" in raw  # Must be readable, not escaped
        assert "Brücke" in raw


# ---------------------------------------------------------------------------
# 28. SQLite persistence across connections
# ---------------------------------------------------------------------------

class TestSQLitePersistence:
    def test_data_persists_across_connections(self, temp_env):
        _, db_path, source_root = temp_env
        Path(source_root, "a.blend").touch()

        stats1, repo1, conn1 = _scan(db_path, source_root)
        original_id = list(repo1.get_all_assets(source_root))[0].asset_id
        conn1.close()

        # Open a completely new connection
        conn2 = sqlite3.connect(db_path)
        repo2 = AssetRepository(conn2)
        assets = list(repo2.get_all_assets(source_root))
        assert len(assets) == 1
        assert assets[0].asset_id == original_id
        conn2.close()


# ---------------------------------------------------------------------------
# 29. Same filename in different directories
# ---------------------------------------------------------------------------

class TestFilenameCollision:
    def test_same_name_different_dirs(self, temp_env):
        _, db_path, source_root = temp_env
        os.makedirs(os.path.join(source_root, "BMW"))
        os.makedirs(os.path.join(source_root, "AUDI"))
        Path(source_root, "BMW", "wheel.blend").touch()
        Path(source_root, "AUDI", "wheel.blend").touch()
        stats, repo, conn = _scan(db_path, source_root)
        assert stats["total_3d_assets"] == 2
        assets = list(repo.get_all_assets(source_root))
        assert len(assets) == 2
        ids = {a.asset_id for a in assets}
        assert len(ids) == 2  # Distinct UUIDs
        dirs = {a.top_level_directory for a in assets}
        assert dirs == {"BMW", "AUDI"}
        conn.close()


# ---------------------------------------------------------------------------
# 30. Symlink directories not followed
# ---------------------------------------------------------------------------

class TestSymlinks:
    def test_symlink_dir_not_followed(self, temp_env):
        _, db_path, source_root = temp_env
        real_dir = os.path.join(source_root, "real")
        os.makedirs(real_dir)
        Path(real_dir, "model.blend").touch()

        # Create a symlink directory pointing to real_dir
        link_dir = os.path.join(source_root, "link_to_real")
        try:
            os.symlink(real_dir, link_dir)
        except OSError:
            pytest.skip("Cannot create symlinks on this OS/filesystem")

        stats, repo, conn = _scan(db_path, source_root)
        # Should find model.blend via real/ but NOT via link_to_real/
        assert stats["total_3d_assets"] == 1
        conn.close()


# ---------------------------------------------------------------------------
# 31. Broken symlinks don't crash
# ---------------------------------------------------------------------------

class TestBrokenSymlinks:
    def test_broken_symlink_file(self, temp_env):
        _, db_path, source_root = temp_env
        broken = os.path.join(source_root, "broken.blend")
        try:
            os.symlink("/nonexistent/path/model.blend", broken)
        except OSError:
            pytest.skip("Cannot create symlinks on this OS/filesystem")

        Path(source_root, "real.fbx").touch()
        stats, repo, conn = _scan(db_path, source_root)
        # broken.blend should be skipped (it's a symlink), real.fbx should be found
        assert stats["total_3d_assets"] == 1
        conn.close()


# ---------------------------------------------------------------------------
# 32. Filesystem permission errors
# ---------------------------------------------------------------------------

class TestPermissionErrors:
    def test_inaccessible_dir_does_not_crash(self, temp_env):
        _, db_path, source_root = temp_env
        protected = os.path.join(source_root, "protected")
        os.makedirs(protected)
        Path(protected, "secret.blend").touch()
        Path(source_root, "public.fbx").touch()

        # Remove read permission
        try:
            os.chmod(protected, 0o000)
        except OSError:
            pytest.skip("Cannot change permissions on this OS/filesystem")

        try:
            stats, repo, conn = _scan(db_path, source_root)
            assert stats["errors"] >= 1
            # public.fbx should still be found
            assets = list(repo.get_all_assets(source_root))
            filenames = {a.filename for a in assets}
            assert "public.fbx" in filenames
            conn.close()
        finally:
            os.chmod(protected, 0o755)


# ---------------------------------------------------------------------------
# 33. Multiple nesting levels calculate directory_depth correctly
# ---------------------------------------------------------------------------

class TestDirectoryDepthMultiple:
    def test_various_depths(self, temp_env):
        _, db_path, source_root = temp_env
        # depth 0
        Path(source_root, "root.blend").touch()
        # depth 1
        os.makedirs(os.path.join(source_root, "L1"))
        Path(source_root, "L1", "d1.fbx").touch()
        # depth 2
        os.makedirs(os.path.join(source_root, "L1", "L2"))
        Path(source_root, "L1", "L2", "d2.obj").touch()
        # depth 5
        os.makedirs(os.path.join(source_root, "A", "B", "C", "D", "E"))
        Path(source_root, "A", "B", "C", "D", "E", "d5.stl").touch()

        stats, repo, conn = _scan(db_path, source_root)
        assets = {a.filename: a for a in repo.get_all_assets(source_root)}
        assert assets["root.blend"].directory_depth == 0
        assert assets["d1.fbx"].directory_depth == 1
        assert assets["d2.obj"].directory_depth == 2
        assert assets["d5.stl"].directory_depth == 5
        assert assets["d5.stl"].top_level_directory == "A"
        assert assets["d5.stl"].parent_directory == "E"
        conn.close()


# ---------------------------------------------------------------------------
# Format registry unit tests
# ---------------------------------------------------------------------------

class TestFormatRegistry:
    @pytest.mark.parametrize("ext", [".blend", ".fbx", ".obj", ".glb", ".gltf", ".stl"])
    def test_mvp_formats(self, ext):
        assert get_format_status(ext) == FormatStatus.MVP_SUPPORTED
        assert get_format_status(ext.upper()) == FormatStatus.MVP_SUPPORTED

    @pytest.mark.parametrize("ext", [".ply", ".dae", ".3ds"])
    def test_later_formats(self, ext):
        assert get_format_status(ext) == FormatStatus.SUPPORTED_LATER

    @pytest.mark.parametrize("ext", [".max", ".c4d"])
    def test_unsupported_formats(self, ext):
        assert get_format_status(ext) == FormatStatus.UNSUPPORTED_FORMAT

    @pytest.mark.parametrize("ext", [".txt", ".png", ".jpg", ".pdf", ".zip"])
    def test_non_3d(self, ext):
        assert get_format_status(ext) == FormatStatus.NON_3D

    def test_initial_analysis_status_mvp(self):
        assert initial_analysis_status(FormatStatus.MVP_SUPPORTED) == "PENDING"

    def test_initial_analysis_status_later(self):
        assert initial_analysis_status(FormatStatus.SUPPORTED_LATER) == "SUPPORTED_LATER"

    def test_initial_analysis_status_unsupported(self):
        assert initial_analysis_status(FormatStatus.UNSUPPORTED_FORMAT) == "UNSUPPORTED_FORMAT"


# ---------------------------------------------------------------------------
# Fingerprint unit tests
# ---------------------------------------------------------------------------

class TestFingerprint:
    def test_deterministic(self):
        assert create_fingerprint(100, 999) == "100:999"

    def test_different_inputs(self):
        assert create_fingerprint(100, 999) != create_fingerprint(101, 999)
        assert create_fingerprint(100, 999) != create_fingerprint(100, 998)


# ---------------------------------------------------------------------------
# Safe missing-file reconciliation
# ---------------------------------------------------------------------------

class TestSafeMissingReconciliation:
    def test_permission_error_skips_reconciliation(self, temp_env):
        """If a subtree can't be scanned, assets inside must NOT be marked missing."""
        _, db_path, source_root = temp_env
        protected = os.path.join(source_root, "protected")
        os.makedirs(protected)
        Path(protected, "secret.blend").touch()
        Path(source_root, "public.fbx").touch()

        # First scan — both files found
        stats1, repo1, conn1 = _scan(db_path, source_root)
        assert stats1["total_3d_assets"] == 2
        conn1.close()

        # Now remove permissions on protected dir
        try:
            os.chmod(protected, 0o000)
        except OSError:
            pytest.skip("Cannot change permissions on this OS/filesystem")

        try:
            # Rescan with inaccessible directory
            stats2, repo2, conn2 = _scan(db_path, source_root)
            assert stats2["errors"] >= 1

            # secret.blend must NOT be marked missing because the scan had errors
            assert stats2["missing"] == 0
            all_assets = list(repo2.get_all_assets(source_root, present_only=False))
            by_name = {a.filename: a for a in all_assets}
            assert by_name["secret.blend"].is_present == 1  # NOT falsely marked missing
            conn2.close()
        finally:
            os.chmod(protected, 0o755)
