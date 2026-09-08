"""Comprehensive tests for Phase 4B.2 Rule Engine."""
import json
import pytest
import sqlite3
import os
import sys

from asset_auditor.assessment.models import (
    EvaluationOutcome, Lineage, StagedIssue, ReadinessStatus,
)
from asset_auditor.assessment.context import AssessmentContext
from asset_auditor.assessment.evaluators import (
    evaluate_no_mesh_objects,
    evaluate_zero_geometry,
    evaluate_invalid_bounding_box,
    evaluate_no_materials,
    evaluate_external_missing_texture,
    evaluate_textured_mesh_without_uv,
    evaluate_explicit_uv_layer_missing,
)
from asset_auditor.assessment.dispatcher import derive_readiness
from asset_auditor.assessment.rules import compute_ruleset_hash, load_ruleset
from asset_auditor.assessment.lineage import compute_input_signature


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_lineage(**kwargs):
    defaults = {
        "asset_id": "test-asset",
        "source_fingerprint": "123:456",
        "source_file_size_bytes": 123,
        "source_modified_time_ns": 456,
        "basic_analysis_run_id": "basic-1",
        "deep_analysis_run_id": "deep-1",
        "preview_id": "preview-1",
    }
    defaults.update(kwargs)
    return Lineage(**defaults)


def _make_ctx(geometry=None, materials=None, images=None,
              material_textures=None, uv_summaries=None,
              mesh_materials=None, **lineage_kw):
    return AssessmentContext(
        lineage=_make_lineage(**lineage_kw),
        geometry=geometry or {},
        materials=materials or [],
        images=images or [],
        material_textures=material_textures or [],
        uv_summaries=uv_summaries or [],
        mesh_materials=mesh_materials or [],
    )


# ===========================================================================
# NO_MESH_OBJECTS
# ===========================================================================
class TestNoMeshObjects:
    def test_triggered(self):
        ctx = _make_ctx(geometry={"mesh_objects_count": 0})
        result = evaluate_no_mesh_objects(ctx, {})
        assert result[0].outcome == EvaluationOutcome.TRIGGERED

    def test_pass(self):
        ctx = _make_ctx(geometry={"mesh_objects_count": 5})
        result = evaluate_no_mesh_objects(ctx, {})
        assert result[0].outcome == EvaluationOutcome.PASS

    def test_no_geometry_data(self):
        ctx = _make_ctx(geometry=None)
        result = evaluate_no_mesh_objects(ctx, {})
        assert result[0].outcome == EvaluationOutcome.TRIGGERED


# ===========================================================================
# ZERO_GEOMETRY
# ===========================================================================
class TestZeroGeometry:
    def test_triggered(self):
        ctx = _make_ctx(geometry={"mesh_objects_count": 1, "vertices": 0, "faces": 0})
        result = evaluate_zero_geometry(ctx, {})
        assert result[0].outcome == EvaluationOutcome.TRIGGERED

    def test_pass(self):
        ctx = _make_ctx(geometry={"mesh_objects_count": 1, "vertices": 100, "faces": 50})
        result = evaluate_zero_geometry(ctx, {})
        assert result[0].outcome == EvaluationOutcome.PASS

    def test_not_applicable_no_mesh(self):
        ctx = _make_ctx(geometry={"mesh_objects_count": 0})
        result = evaluate_zero_geometry(ctx, {})
        assert result[0].outcome == EvaluationOutcome.NOT_APPLICABLE

    def test_not_applicable_no_geometry_data(self):
        ctx = _make_ctx(geometry=None)
        result = evaluate_zero_geometry(ctx, {})
        assert result[0].outcome == EvaluationOutcome.NOT_APPLICABLE


# ===========================================================================
# INVALID_BOUNDING_BOX
# ===========================================================================
class TestInvalidBoundingBox:
    def test_pass_normal(self):
        ctx = _make_ctx(geometry={
            "bbox_min_x": -1, "bbox_min_y": -1, "bbox_min_z": -1,
            "bbox_max_x": 1, "bbox_max_y": 1, "bbox_max_z": 1,
            "width": 2, "depth": 2, "height": 2,
        })
        result = evaluate_invalid_bounding_box(ctx, {"epsilon": 1e-7})
        assert result[0].outcome == EvaluationOutcome.PASS

    def test_pass_planar(self):
        """A plane (one zero extent) is legitimate."""
        ctx = _make_ctx(geometry={
            "bbox_min_x": 0, "bbox_min_y": 0, "bbox_min_z": 0,
            "bbox_max_x": 1, "bbox_max_y": 0, "bbox_max_z": 1,
            "width": 1, "depth": 0, "height": 1,
        })
        result = evaluate_invalid_bounding_box(ctx, {"epsilon": 1e-7})
        assert result[0].outcome == EvaluationOutcome.PASS

    def test_triggered_all_zero(self):
        ctx = _make_ctx(geometry={
            "bbox_min_x": 0, "bbox_min_y": 0, "bbox_min_z": 0,
            "bbox_max_x": 0, "bbox_max_y": 0, "bbox_max_z": 0,
            "width": 0, "depth": 0, "height": 0,
        })
        result = evaluate_invalid_bounding_box(ctx, {"epsilon": 1e-7})
        assert result[0].outcome == EvaluationOutcome.TRIGGERED

    def test_triggered_negative_extent(self):
        ctx = _make_ctx(geometry={
            "bbox_min_x": 1, "bbox_min_y": 0, "bbox_min_z": 0,
            "bbox_max_x": -1, "bbox_max_y": 1, "bbox_max_z": 1,
            "width": -2, "depth": 1, "height": 1,
        })
        result = evaluate_invalid_bounding_box(ctx, {"epsilon": 1e-7})
        assert result[0].outcome == EvaluationOutcome.TRIGGERED

    def test_triggered_missing_coords(self):
        ctx = _make_ctx(geometry={
            "bbox_min_x": None, "bbox_min_y": 0, "bbox_min_z": 0,
            "bbox_max_x": 1, "bbox_max_y": 1, "bbox_max_z": 1,
            "width": 1, "depth": 1, "height": 1,
        })
        result = evaluate_invalid_bounding_box(ctx, {"epsilon": 1e-7})
        assert result[0].outcome == EvaluationOutcome.TRIGGERED

    def test_triggered_nan(self):
        ctx = _make_ctx(geometry={
            "bbox_min_x": float("nan"), "bbox_min_y": 0, "bbox_min_z": 0,
            "bbox_max_x": 1, "bbox_max_y": 1, "bbox_max_z": 1,
            "width": 1, "depth": 1, "height": 1,
        })
        result = evaluate_invalid_bounding_box(ctx, {"epsilon": 1e-7})
        assert result[0].outcome == EvaluationOutcome.TRIGGERED


# ===========================================================================
# NO_MATERIALS
# ===========================================================================
class TestNoMaterials:
    def test_triggered(self):
        ctx = _make_ctx(materials=[])
        result = evaluate_no_materials(ctx, {})
        assert result[0].outcome == EvaluationOutcome.TRIGGERED

    def test_pass(self):
        ctx = _make_ctx(materials=[{"id": 1, "material_name": "Mat"}])
        result = evaluate_no_materials(ctx, {})
        assert result[0].outcome == EvaluationOutcome.PASS


# ===========================================================================
# EXTERNAL_MISSING_TEXTURE
# ===========================================================================
class TestExternalMissingTexture:
    def test_triggered(self):
        ctx = _make_ctx(images=[
            {"image_index": 0, "image_name": "img", "resource_status": "EXTERNAL_MISSING"},
        ])
        result = evaluate_external_missing_texture(ctx, {"acceptable_resource_status": ["PACKED"]})
        assert result[0].outcome == EvaluationOutcome.TRIGGERED

    def test_pass_packed(self):
        ctx = _make_ctx(images=[
            {"image_index": 0, "image_name": "img", "resource_status": "PACKED"},
        ])
        result = evaluate_external_missing_texture(ctx, {"acceptable_resource_status": ["PACKED"]})
        assert result[0].outcome == EvaluationOutcome.PASS

    def test_not_applicable_no_images(self):
        ctx = _make_ctx(images=[])
        result = evaluate_external_missing_texture(ctx, {})
        assert result[0].outcome == EvaluationOutcome.NOT_APPLICABLE

    def test_unknown_is_not_missing(self):
        """UNKNOWN must not automatically trigger EXTERNAL_MISSING."""
        ctx = _make_ctx(images=[
            {"image_index": 0, "image_name": "img", "resource_status": "UNKNOWN"},
        ])
        result = evaluate_external_missing_texture(ctx, {"acceptable_resource_status": ["PACKED"]})
        assert result[0].outcome == EvaluationOutcome.PASS


# ===========================================================================
# TEXTURED_MESH_WITHOUT_UV
# ===========================================================================
class TestTexturedMeshWithoutUv:
    def test_triggered(self):
        ctx = _make_ctx(
            mesh_materials=[{"material_id": 1, "mesh_index": 0}],
            material_textures=[{
                "material_id": 1, "uv_mapping_source": "DEFAULT",
            }],
            uv_summaries=[{"mesh_index": 0, "has_uv": 0, "mesh_name": "Cube"}],
        )
        cfg = {"uv_dependent_sources": ["DEFAULT", "EXPLICIT_UV_MAP"]}
        result = evaluate_textured_mesh_without_uv(ctx, cfg)
        triggered = [r for r in result if r.outcome == EvaluationOutcome.TRIGGERED]
        assert len(triggered) == 1

    def test_pass_has_uv(self):
        ctx = _make_ctx(
            mesh_materials=[{"material_id": 1, "mesh_index": 0}],
            material_textures=[{
                "material_id": 1, "uv_mapping_source": "EXPLICIT_UV_MAP",
            }],
            uv_summaries=[{"mesh_index": 0, "has_uv": 1, "mesh_name": "Cube"}],
        )
        cfg = {"uv_dependent_sources": ["DEFAULT", "EXPLICIT_UV_MAP"]}
        result = evaluate_textured_mesh_without_uv(ctx, cfg)
        assert all(r.outcome != EvaluationOutcome.TRIGGERED for r in result)

    def test_not_applicable_other_source(self):
        """uv_mapping_source=OTHER should not trigger this rule."""
        ctx = _make_ctx(
            mesh_materials=[{"material_id": 1, "mesh_index": 0}],
            material_textures=[{
                "material_id": 1, "uv_mapping_source": "OTHER",
            }],
            uv_summaries=[{"mesh_index": 0, "has_uv": 0, "mesh_name": "Cube"}],
        )
        cfg = {"uv_dependent_sources": ["DEFAULT", "EXPLICIT_UV_MAP"]}
        result = evaluate_textured_mesh_without_uv(ctx, cfg)
        triggered = [r for r in result if r.outcome == EvaluationOutcome.TRIGGERED]
        assert len(triggered) == 0

    def test_deduplication(self):
        """Duplicate object instances using same mesh+material should not create duplicate issues."""
        ctx = _make_ctx(
            mesh_materials=[
                {"material_id": 1, "mesh_index": 0},
                {"material_id": 1, "mesh_index": 0},  # duplicate instance
            ],
            material_textures=[{
                "material_id": 1, "uv_mapping_source": "DEFAULT",
            }],
            uv_summaries=[{"mesh_index": 0, "has_uv": 0, "mesh_name": "Cube"}],
        )
        cfg = {"uv_dependent_sources": ["DEFAULT", "EXPLICIT_UV_MAP"]}
        result = evaluate_textured_mesh_without_uv(ctx, cfg)
        triggered = [r for r in result if r.outcome == EvaluationOutcome.TRIGGERED]
        assert len(triggered) == 1


# ===========================================================================
# EXPLICIT_UV_LAYER_MISSING
# ===========================================================================
class TestExplicitUvLayerMissing:
    def test_triggered(self):
        ctx = _make_ctx(
            mesh_materials=[{"material_id": 1, "mesh_index": 0}],
            material_textures=[{
                "material_id": 1, "uv_mapping_source": "EXPLICIT_UV_MAP",
                "uv_map_name": "UVMap.001",
            }],
            uv_summaries=[{
                "mesh_index": 0, "mesh_name": "Cube",
                "uv_layer_names_json": '["UVMap"]',
            }],
        )
        result = evaluate_explicit_uv_layer_missing(ctx, {})
        triggered = [r for r in result if r.outcome == EvaluationOutcome.TRIGGERED]
        assert len(triggered) == 1
        assert triggered[0].observed_value["requested_uv"] == "UVMap.001"

    def test_pass(self):
        ctx = _make_ctx(
            mesh_materials=[{"material_id": 1, "mesh_index": 0}],
            material_textures=[{
                "material_id": 1, "uv_mapping_source": "EXPLICIT_UV_MAP",
                "uv_map_name": "UVMap",
            }],
            uv_summaries=[{
                "mesh_index": 0, "mesh_name": "Cube",
                "uv_layer_names_json": '["UVMap"]',
            }],
        )
        result = evaluate_explicit_uv_layer_missing(ctx, {})
        assert all(r.outcome != EvaluationOutcome.TRIGGERED for r in result)

    def test_not_applicable_default(self):
        """DEFAULT source should not trigger this rule."""
        ctx = _make_ctx(
            mesh_materials=[{"material_id": 1, "mesh_index": 0}],
            material_textures=[{
                "material_id": 1, "uv_mapping_source": "DEFAULT",
                "uv_map_name": None,
            }],
            uv_summaries=[{
                "mesh_index": 0, "mesh_name": "Cube",
                "uv_layer_names_json": '["UVMap"]',
            }],
        )
        result = evaluate_explicit_uv_layer_missing(ctx, {})
        triggered = [r for r in result if r.outcome == EvaluationOutcome.TRIGGERED]
        assert len(triggered) == 0

    def test_deduplication(self):
        """Multiple texture-relationships pointing at same uv_map_name on same mesh+material."""
        ctx = _make_ctx(
            mesh_materials=[{"material_id": 1, "mesh_index": 0}],
            material_textures=[
                {"material_id": 1, "uv_mapping_source": "EXPLICIT_UV_MAP", "uv_map_name": "Missing"},
                {"material_id": 1, "uv_mapping_source": "EXPLICIT_UV_MAP", "uv_map_name": "Missing"},
            ],
            uv_summaries=[{
                "mesh_index": 0, "mesh_name": "Cube",
                "uv_layer_names_json": '["UVMap"]',
            }],
        )
        result = evaluate_explicit_uv_layer_missing(ctx, {})
        triggered = [r for r in result if r.outcome == EvaluationOutcome.TRIGGERED]
        assert len(triggered) == 1


# ===========================================================================
# Readiness Derivation
# ===========================================================================
class TestReadinessDerivation:
    def test_ready(self):
        assert derive_readiness([]) == "READY"

    def test_warning(self):
        issues = [StagedIssue("R1", "WARNING", "NONE", "cat", "msg")]
        assert derive_readiness(issues) == "READY_WITH_WARNINGS"

    def test_needs_fix(self):
        issues = [StagedIssue("R1", "BLOCKER", "NEEDS_FIX", "cat", "msg")]
        assert derive_readiness(issues) == "NEEDS_FIX"

    def test_not_sellable(self):
        issues = [StagedIssue("R1", "BLOCKER", "NOT_SELLABLE", "cat", "msg")]
        assert derive_readiness(issues) == "NOT_SELLABLE"

    def test_not_sellable_overrides_needs_fix(self):
        issues = [
            StagedIssue("R1", "BLOCKER", "NEEDS_FIX", "cat", "msg"),
            StagedIssue("R2", "BLOCKER", "NOT_SELLABLE", "cat", "msg"),
        ]
        assert derive_readiness(issues) == "NOT_SELLABLE"

    def test_info_does_not_lower(self):
        issues = [StagedIssue("R1", "INFO", "NONE", "cat", "msg")]
        assert derive_readiness(issues) == "READY"


# ===========================================================================
# Ruleset Hash
# ===========================================================================
class TestRulesetHash:
    def test_deterministic(self):
        data = {"a": 1, "b": 2}
        h1 = compute_ruleset_hash(data)
        h2 = compute_ruleset_hash(data)
        assert h1 == h2

    def test_key_order_irrelevant(self):
        d1 = {"b": 2, "a": 1}
        d2 = {"a": 1, "b": 2}
        assert compute_ruleset_hash(d1) == compute_ruleset_hash(d2)

    def test_config_change_changes_hash(self):
        d1 = {"rules": {"X": {"severity": "BLOCKER"}}}
        d2 = {"rules": {"X": {"severity": "WARNING"}}}
        assert compute_ruleset_hash(d1) != compute_ruleset_hash(d2)

    def test_real_ruleset_loads(self):
        data = load_ruleset()
        h = compute_ruleset_hash(data)
        assert len(h) == 64  # SHA256 hex


# ===========================================================================
# Score fields NULL
# ===========================================================================
class TestNullableScores:
    def test_assessment_result_has_no_scores(self):
        """AssessmentResult never populates score fields (Phase 4B.2)."""
        from asset_auditor.assessment.models import AssessmentResult
        r = AssessmentResult(readiness_status="READY")
        # No score attributes exist on AssessmentResult
        assert not hasattr(r, "geometry_score")
