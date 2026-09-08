"""Comprehensive Phase 2A test suite.

Tests the analysis pipeline using mocked subprocess results
and a programmatically generated minimal GLB fixture.
"""
import json
import os
import sqlite3
import struct
import tempfile
import time

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from asset_auditor.catalog.database import Database
from asset_auditor.catalog.repository import AssetRepository
from asset_auditor.scanner.scanner import Scanner
from asset_auditor.scanner.formats import get_format_status, FormatStatus
from asset_auditor.analyzer.runner import (
    run_blender_analysis,
    AnalysisResult,
    _validate_result,
)
from asset_auditor.analyzer.result_parser import persist_analysis_result
from asset_auditor.analyzer.dispatcher import (
    get_pending_assets,
    run_batch_analysis,
    PHASE_2A_EXTENSIONS,
)
from asset_auditor.config import ANALYZER_VERSION, ANALYSIS_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_env():
    """Provide a temp DB with schema initialized and a few test assets."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        source_root = os.path.join(temp_dir, "models")
        os.makedirs(source_root)
        db = Database(db_path)
        yield temp_dir, db_path, source_root, db


def _scan_and_get_conn(db_path, source_root):
    """Scan source_root and return (conn, stats)."""
    db = Database(db_path)
    conn = sqlite3.connect(db_path)
    repo = AssetRepository(conn)
    scanner = Scanner(source_root, repo)
    conn.execute("BEGIN")
    stats = scanner.scan()
    conn.execute("COMMIT")
    return conn, stats


def _make_success_result(asset_id: str, run_id: str = "run-001") -> AnalysisResult:
    """Create a mock SUCCESS AnalysisResult."""
    return AnalysisResult(
        analysis_run_id=run_id,
        asset_id=asset_id,
        status="SUCCESS",
        blender_version="4.2.0",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:03+00:00",
        duration_ms=3000,
        blender_exit_code=0,
        result_data={
            "schema_version": "1",
            "asset_id": asset_id,
            "source_path": "/test/model.glb",
            "status": "SUCCESS",
            "blender_version": "4.2.0",
            "scene": {
                "objects": 10,
                "mesh_objects": 5,
                "empties": 2,
                "cameras": 1,
                "lights": 1,
                "armatures": 1,
            },
            "geometry": {
                "vertices": 1000,
                "edges": 2000,
                "faces": 500,
                "triangles": 1000,
            },
            "bounding_box": {
                "min_x": -0.5, "min_y": -0.3, "min_z": 0.0,
                "max_x": 0.5, "max_y": 0.3, "max_z": 0.4,
                "width": 1.0, "depth": 0.6, "height": 0.4,
            },
            "units": {"system": "METRIC", "scale_length": 1.0},
            "materials": {"count": 3},
            "images": {"count": 5},
        },
    )


# ---------------------------------------------------------------------------
# 1. GLB recognized for Phase 2A
# ---------------------------------------------------------------------------

class TestFormatRecognition:
    def test_glb_is_mvp_supported(self):
        assert get_format_status(".glb") == FormatStatus.MVP_SUPPORTED

    def test_gltf_is_mvp_supported(self):
        assert get_format_status(".gltf") == FormatStatus.MVP_SUPPORTED

    def test_glb_in_phase_2a_extensions(self):
        assert ".glb" in PHASE_2A_EXTENSIONS

    def test_gltf_in_phase_2a_extensions(self):
        assert ".gltf" in PHASE_2A_EXTENSIONS


# ---------------------------------------------------------------------------
# 3. Non-Phase-2A formats not dispatched
# ---------------------------------------------------------------------------

class TestNonPhase2AExclusion:
    def test_blend_not_dispatched(self, db_env):
        _, db_path, source_root, _ = db_env
        Path(source_root, "model.blend").touch()
        Path(source_root, "model.glb").touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)
        pending = get_pending_assets(conn, source_root)
        filenames = {os.path.basename(p["absolute_path"]) for p in pending}
        assert "model.glb" in filenames
        assert "model.blend" not in filenames
        conn.close()

    def test_fbx_not_dispatched(self, db_env):
        _, db_path, source_root, _ = db_env
        Path(source_root, "model.fbx").touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)
        pending = get_pending_assets(conn, source_root)
        assert len(pending) == 0
        conn.close()


# ---------------------------------------------------------------------------
# 4. PENDING → ANALYZING → SUCCESS
# ---------------------------------------------------------------------------

class TestSuccessLifecycle:
    def test_success_persists_correctly(self, db_env):
        _, db_path, source_root, _ = db_env
        Path(source_root, "model.glb").touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)

        cursor = conn.cursor()
        cursor.execute("SELECT asset_id FROM assets WHERE filename = 'model.glb'")
        asset_id = cursor.fetchone()[0]

        result = _make_success_result(asset_id)
        persist_analysis_result(conn, result)

        # Check analysis_runs
        cursor.execute("SELECT status, blender_version, analyzer_version FROM analysis_runs WHERE asset_id = ?", (asset_id,))
        row = cursor.fetchone()
        assert row[0] == "SUCCESS"
        assert row[1] == "4.2.0"
        assert row[2] == ANALYZER_VERSION

        # Check asset_geometry
        cursor.execute("SELECT vertices, faces, triangles, width FROM asset_geometry WHERE asset_id = ?", (asset_id,))
        geo = cursor.fetchone()
        assert geo[0] == 1000
        assert geo[1] == 500
        assert geo[2] == 1000
        assert geo[3] == 1.0

        # Check assets.analysis_status updated
        cursor.execute("SELECT analysis_status FROM assets WHERE asset_id = ?", (asset_id,))
        assert cursor.fetchone()[0] == "SUCCESS"
        conn.close()


# ---------------------------------------------------------------------------
# 5. Failed import
# ---------------------------------------------------------------------------

class TestFailedImport:
    def test_failed_import_persists(self, db_env):
        _, db_path, source_root, _ = db_env
        Path(source_root, "bad.glb").touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)

        cursor = conn.cursor()
        cursor.execute("SELECT asset_id FROM assets WHERE filename = 'bad.glb'")
        asset_id = cursor.fetchone()[0]

        result = AnalysisResult(
            analysis_run_id="run-fail-001",
            asset_id=asset_id,
            status="FAILED_IMPORT",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
            duration_ms=1000,
            blender_exit_code=1,
            error_type="RuntimeError",
            error_message="GLB import failed",
        )
        persist_analysis_result(conn, result)

        cursor.execute("SELECT status, error_type FROM analysis_runs WHERE asset_id = ?", (asset_id,))
        row = cursor.fetchone()
        assert row[0] == "FAILED_IMPORT"
        assert row[1] == "RuntimeError"

        cursor.execute("SELECT analysis_status FROM assets WHERE asset_id = ?", (asset_id,))
        assert cursor.fetchone()[0] == "FAILED_IMPORT"

        # No geometry should exist
        cursor.execute("SELECT COUNT(*) FROM asset_geometry WHERE asset_id = ?", (asset_id,))
        assert cursor.fetchone()[0] == 0
        conn.close()


# ---------------------------------------------------------------------------
# 6. Failed analysis
# ---------------------------------------------------------------------------

class TestFailedAnalysis:
    def test_failed_analysis_persists(self, db_env):
        _, db_path, source_root, _ = db_env
        Path(source_root, "corrupt.glb").touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)

        cursor = conn.cursor()
        cursor.execute("SELECT asset_id FROM assets WHERE filename = 'corrupt.glb'")
        asset_id = cursor.fetchone()[0]

        result = AnalysisResult(
            analysis_run_id="run-fail-002",
            asset_id=asset_id,
            status="FAILED_ANALYSIS",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:02+00:00",
            duration_ms=2000,
            blender_exit_code=2,
            error_type="ValueError",
            error_message="Cannot process geometry",
        )
        persist_analysis_result(conn, result)

        cursor.execute("SELECT analysis_status FROM assets WHERE asset_id = ?", (asset_id,))
        assert cursor.fetchone()[0] == "FAILED_ANALYSIS"
        conn.close()


# ---------------------------------------------------------------------------
# 7. Timeout
# ---------------------------------------------------------------------------

class TestTimeout:
    def test_timeout_persists(self, db_env):
        _, db_path, source_root, _ = db_env
        Path(source_root, "huge.glb").touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)

        cursor = conn.cursor()
        cursor.execute("SELECT asset_id FROM assets WHERE filename = 'huge.glb'")
        asset_id = cursor.fetchone()[0]

        result = AnalysisResult(
            analysis_run_id="run-timeout-001",
            asset_id=asset_id,
            status="TIMEOUT",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:02:00+00:00",
            duration_ms=120000,
            blender_exit_code=-1,
            error_type="Timeout",
            error_message="Exceeded 120s timeout",
        )
        persist_analysis_result(conn, result)

        cursor.execute("SELECT analysis_status FROM assets WHERE asset_id = ?", (asset_id,))
        assert cursor.fetchone()[0] == "TIMEOUT"
        conn.close()


# ---------------------------------------------------------------------------
# 8. Non-zero exit code
# ---------------------------------------------------------------------------

class TestNonZeroExitCode:
    def test_nonzero_exit_recorded(self, db_env):
        _, db_path, source_root, _ = db_env
        Path(source_root, "crash.glb").touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)

        cursor = conn.cursor()
        cursor.execute("SELECT asset_id FROM assets WHERE filename = 'crash.glb'")
        asset_id = cursor.fetchone()[0]

        result = AnalysisResult(
            analysis_run_id="run-crash-001",
            asset_id=asset_id,
            status="FAILED_ANALYSIS",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
            duration_ms=1000,
            blender_exit_code=139,
            error_type="SegFault",
            error_message="Blender segfaulted",
        )
        persist_analysis_result(conn, result)

        cursor.execute("SELECT blender_exit_code FROM analysis_runs WHERE asset_id = ?", (asset_id,))
        assert cursor.fetchone()[0] == 139
        conn.close()


# ---------------------------------------------------------------------------
# 9–11. Result validation
# ---------------------------------------------------------------------------

class TestResultValidation:
    def test_missing_result_json(self):
        err = _validate_result({}, "abc-123", "BASIC")
        assert "Missing schema_version" in err

    def test_malformed_result(self):
        err = _validate_result({"schema_version": "1", "status": "SUCCESS", "asset_id": "abc"}, "abc", "BASIC")
        assert "Missing required section 'scene' on SUCCESS" in err

    def test_wrong_asset_id(self):
        err = _validate_result(
            {"schema_version": "1", "status": "SUCCESS", "asset_id": "wrong"},
            "expected",
            "BASIC"
        )
        assert "asset_id mismatch" in err

    def test_valid_success(self):
        data = {
            "schema_version": "1",
            "status": "SUCCESS",
            "asset_id": "abc",
            "analysis_profile": "BASIC",
            "scene": {},
            "geometry": {},
            "materials": {"count": 1},
            "images": {"count": 1},
            "bounding_box": {},
            "units": {},
        }
        assert _validate_result(data, "abc", "BASIC") is None

    def test_valid_failure_no_sections_needed(self):
        data = {
            "schema_version": "1",
            "status": "FAILED_IMPORT",
            "asset_id": "abc",
        }
        assert _validate_result(data, "abc", "BASIC") is None


# ---------------------------------------------------------------------------
# 12. Stable persistence
# ---------------------------------------------------------------------------

class TestStablePersistence:
    def test_analysis_persists_across_connections(self, db_env):
        _, db_path, source_root, _ = db_env
        Path(source_root, "model.glb").touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)

        cursor = conn.cursor()
        cursor.execute("SELECT asset_id FROM assets WHERE filename = 'model.glb'")
        asset_id = cursor.fetchone()[0]

        result = _make_success_result(asset_id, "run-persist-001")
        persist_analysis_result(conn, result)
        conn.close()

        # New connection
        conn2 = sqlite3.connect(db_path)
        cursor2 = conn2.cursor()
        cursor2.execute("SELECT status FROM analysis_runs WHERE asset_id = ?", (asset_id,))
        assert cursor2.fetchone()[0] == "SUCCESS"
        cursor2.execute("SELECT vertices FROM asset_geometry WHERE asset_id = ?", (asset_id,))
        assert cursor2.fetchone()[0] == 1000
        conn2.close()


# ---------------------------------------------------------------------------
# 13. Successful analysis is not rerun on resume
# ---------------------------------------------------------------------------

class TestResumeSkipsSuccess:
    def test_success_not_requeued(self, db_env):
        _, db_path, source_root, _ = db_env
        Path(source_root, "model.glb").touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)

        cursor = conn.cursor()
        cursor.execute("SELECT asset_id FROM assets WHERE filename = 'model.glb'")
        asset_id = cursor.fetchone()[0]

        # Mark as SUCCESS
        result = _make_success_result(asset_id)
        persist_analysis_result(conn, result)

        # Query pending
        pending = get_pending_assets(conn, source_root)
        assert len(pending) == 0
        conn.close()


# ---------------------------------------------------------------------------
# 14. Failed asset does not stop next asset
# ---------------------------------------------------------------------------

class TestBatchContinuesAfterFailure:
    @patch("asset_auditor.analyzer.dispatcher.run_blender_analysis")
    def test_batch_continues(self, mock_run, db_env):
        _, db_path, source_root, _ = db_env
        Path(source_root, "a.glb").touch()
        Path(source_root, "b.glb").touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)

        cursor = conn.cursor()
        cursor.execute("SELECT asset_id, filename FROM assets ORDER BY filename")
        rows = cursor.fetchall()
        asset_map = {row[0]: row[1] for row in rows}

        # Dynamically produce the right mock result based on which asset is dispatched
        first_call = [True]
        def mock_side_effect(asset_id, asset_path, timeout=120, analysis_profile="BASIC"):
            if first_call[0]:
                first_call[0] = False
                return AnalysisResult(
                    analysis_run_id="run-fail",
                    asset_id=asset_id,
                    status="FAILED_IMPORT",
                    started_at="2026-01-01T00:00:00+00:00",
                    finished_at="2026-01-01T00:00:01+00:00",
                    duration_ms=1000,
                    blender_exit_code=1,
                    error_type="ImportError",
                    error_message="Bad file",
                )
            else:
                return _make_success_result(asset_id, "run-ok")

        mock_run.side_effect = mock_side_effect

        stats = run_batch_analysis(conn, source_root)
        assert stats["failed_import"] == 1
        assert stats["success"] == 1
        assert stats["total"] == 2

        # Verify that one is FAILED_IMPORT and one is SUCCESS
        statuses = set()
        for aid in asset_map:
            cursor.execute("SELECT analysis_status FROM assets WHERE asset_id = ?", (aid,))
            statuses.add(cursor.fetchone()[0])
        assert "FAILED_IMPORT" in statuses
        assert "SUCCESS" in statuses
        conn.close()


# ---------------------------------------------------------------------------
# 15. Changed Phase 1 asset becomes eligible again
# ---------------------------------------------------------------------------

class TestChangedAssetReeligible:
    def test_changed_asset_requeued(self, db_env):
        _, db_path, source_root, _ = db_env
        fp = Path(source_root, "model.glb")
        fp.touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)

        cursor = conn.cursor()
        cursor.execute("SELECT asset_id FROM assets WHERE filename = 'model.glb'")
        asset_id = cursor.fetchone()[0]

        # Mark as SUCCESS
        result = _make_success_result(asset_id)
        persist_analysis_result(conn, result)
        conn.close()

        # Modify file
        time.sleep(0.05)
        fp.write_bytes(b"changed content")

        # Rescan
        conn2, _ = _scan_and_get_conn(db_path, source_root)
        cursor2 = conn2.cursor()
        cursor2.execute("SELECT analysis_status FROM assets WHERE asset_id = ?", (asset_id,))
        assert cursor2.fetchone()[0] == "PENDING"  # Reset by scanner

        pending = get_pending_assets(conn2, source_root)
        assert len(pending) == 1
        conn2.close()


# ---------------------------------------------------------------------------
# 16. Analysis run history retained
# ---------------------------------------------------------------------------

class TestAnalysisHistory:
    def test_multiple_runs_retained(self, db_env):
        _, db_path, source_root, _ = db_env
        Path(source_root, "model.glb").touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)

        cursor = conn.cursor()
        cursor.execute("SELECT asset_id FROM assets WHERE filename = 'model.glb'")
        asset_id = cursor.fetchone()[0]

        # Two analysis runs
        r1 = AnalysisResult(
            analysis_run_id="run-001", asset_id=asset_id, status="FAILED_IMPORT",
            started_at="2026-01-01T00:00:00+00:00", finished_at="2026-01-01T00:00:01+00:00",
            duration_ms=1000, blender_exit_code=1,
            error_type="ImportError", error_message="Bad",
        )
        persist_analysis_result(conn, r1)

        # Reset status to PENDING (as scanner would)
        conn.execute("UPDATE assets SET analysis_status = 'PENDING' WHERE asset_id = ?", (asset_id,))
        conn.commit()

        r2 = _make_success_result(asset_id, "run-002")
        persist_analysis_result(conn, r2)

        cursor.execute("SELECT COUNT(*) FROM analysis_runs WHERE asset_id = ?", (asset_id,))
        assert cursor.fetchone()[0] == 2  # Both runs retained
        conn.close()


# ---------------------------------------------------------------------------
# 17. Geometry linked to correct analysis run
# ---------------------------------------------------------------------------

class TestGeometryLinkage:
    def test_geometry_links_to_run(self, db_env):
        _, db_path, source_root, _ = db_env
        Path(source_root, "model.glb").touch()
        conn, _ = _scan_and_get_conn(db_path, source_root)

        cursor = conn.cursor()
        cursor.execute("SELECT asset_id FROM assets WHERE filename = 'model.glb'")
        asset_id = cursor.fetchone()[0]

        result = _make_success_result(asset_id, "run-linked-001")
        persist_analysis_result(conn, result)

        cursor.execute(
            "SELECT analysis_run_id FROM asset_geometry WHERE asset_id = ?",
            (asset_id,)
        )
        assert cursor.fetchone()[0] == "run-linked-001"
        conn.close()


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestSchemaIntegrity:
    def test_analysis_runs_table_exists(self, db_env):
        _, db_path, _, _ = db_env
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE name = 'analysis_runs'")
        assert cursor.fetchone() is not None
        conn.close()

    def test_asset_geometry_table_exists(self, db_env):
        _, db_path, _, _ = db_env
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE name = 'asset_geometry'")
        assert cursor.fetchone() is not None
        conn.close()

    def test_indexes_exist(self, db_env):
        _, db_path, _, _ = db_env
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'")
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_analysis_runs_asset_id" in indexes
        assert "idx_analysis_runs_status" in indexes
        assert "idx_asset_geometry_asset_id" in indexes
        assert "idx_asset_geometry_run_id" in indexes
        conn.close()
