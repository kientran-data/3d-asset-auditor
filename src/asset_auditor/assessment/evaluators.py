"""Rule evaluators for TECHNICAL_MARKETPLACE_V1.

Each evaluator returns factual observations only.  Severity, disposition,
and category are sourced from the ruleset JSON configuration, not from
these functions.
"""
import json
import math
from typing import Dict, Any, List
from .models import EvaluationOutcome, RuleEvaluation
from .context import AssessmentContext


# ---------------------------------------------------------------------------
# 1.  NO_MESH_OBJECTS
# ---------------------------------------------------------------------------
def evaluate_no_mesh_objects(ctx: AssessmentContext, config: Dict[str, Any]) -> List[RuleEvaluation]:
    """Trigger when the model contains zero mesh objects."""
    if ctx.geometry is None:
        return [RuleEvaluation(
            outcome=EvaluationOutcome.TRIGGERED,
            observed_value={"geometry_data": None},
            expected_value={"geometry_data": "present"},
            message_context="No geometry data found in BASIC analysis.",
        )]

    mesh_count = ctx.geometry.get("mesh_objects_count", 0)
    if mesh_count == 0:
        return [RuleEvaluation(
            outcome=EvaluationOutcome.TRIGGERED,
            observed_value={"mesh_objects_count": 0},
            expected_value={"mesh_objects_count": "> 0"},
            message_context=None,
        )]
    return [RuleEvaluation(outcome=EvaluationOutcome.PASS)]


# ---------------------------------------------------------------------------
# 2.  ZERO_GEOMETRY
# ---------------------------------------------------------------------------
def evaluate_zero_geometry(ctx: AssessmentContext, config: Dict[str, Any]) -> List[RuleEvaluation]:
    """Trigger only when mesh objects exist but contain no vertices/faces.

    NOT_APPLICABLE when mesh_objects_count == 0 (covered by NO_MESH_OBJECTS).
    """
    if ctx.geometry is None:
        return [RuleEvaluation(outcome=EvaluationOutcome.NOT_APPLICABLE)]

    mesh_count = ctx.geometry.get("mesh_objects_count", 0)
    if mesh_count == 0:
        return [RuleEvaluation(outcome=EvaluationOutcome.NOT_APPLICABLE)]

    vertices = ctx.geometry.get("vertices", 0)
    faces = ctx.geometry.get("faces", 0)
    if vertices == 0:
        return [RuleEvaluation(
            outcome=EvaluationOutcome.TRIGGERED,
            observed_value={"vertices": vertices, "faces": faces},
            expected_value={"vertices": "> 0"},
            message_context=f"{vertices} vertices, {faces} faces",
        )]
    return [RuleEvaluation(outcome=EvaluationOutcome.PASS)]


# ---------------------------------------------------------------------------
# 3.  INVALID_BOUNDING_BOX
# ---------------------------------------------------------------------------
def evaluate_invalid_bounding_box(ctx: AssessmentContext, config: Dict[str, Any]) -> List[RuleEvaluation]:
    """Trigger on objectively invalid spatial data.

    Does NOT trigger on zero volume from a single zero extent (planar OK).
    """
    if ctx.geometry is None:
        return [RuleEvaluation(
            outcome=EvaluationOutcome.TRIGGERED,
            observed_value={"geometry_data": None},
            expected_value={"valid_spatial_data": True},
            message_context="No geometry data available.",
        )]

    epsilon = config.get("epsilon", 1e-7)
    g = ctx.geometry

    coords = [
        g.get("bbox_min_x"), g.get("bbox_min_y"), g.get("bbox_min_z"),
        g.get("bbox_max_x"), g.get("bbox_max_y"), g.get("bbox_max_z"),
    ]

    # Missing coordinates
    if any(c is None for c in coords):
        return [RuleEvaluation(
            outcome=EvaluationOutcome.TRIGGERED,
            observed_value={"bbox_coords": coords},
            expected_value={"valid_spatial_data": True},
            message_context="Missing bounding box coordinates.",
        )]

    # Non-finite values
    if any(not math.isfinite(c) for c in coords):
        return [RuleEvaluation(
            outcome=EvaluationOutcome.TRIGGERED,
            observed_value={"bbox_coords": coords},
            expected_value={"valid_spatial_data": True},
            message_context="Non-finite bounding box coordinates.",
        )]

    width = g.get("width", 0)
    depth = g.get("depth", 0)
    height = g.get("height", 0)

    # min > max  → negative derived extents
    if width < 0 or depth < 0 or height < 0:
        return [RuleEvaluation(
            outcome=EvaluationOutcome.TRIGGERED,
            observed_value={"width": width, "depth": depth, "height": height},
            expected_value={"valid_spatial_data": True},
            message_context="Negative derived extents (min > max).",
        )]

    # ALL three extents are effectively zero
    if width <= epsilon and depth <= epsilon and height <= epsilon:
        return [RuleEvaluation(
            outcome=EvaluationOutcome.TRIGGERED,
            observed_value={"width": width, "depth": depth, "height": height},
            expected_value={"valid_spatial_data": True},
            message_context="All spatial extents are zero or near-zero.",
        )]

    return [RuleEvaluation(outcome=EvaluationOutcome.PASS)]


# ---------------------------------------------------------------------------
# 4.  NO_MATERIALS
# ---------------------------------------------------------------------------
def evaluate_no_materials(ctx: AssessmentContext, config: Dict[str, Any]) -> List[RuleEvaluation]:
    """Trigger when no material datablocks exist in the frozen DEEP run."""
    if len(ctx.materials) == 0:
        return [RuleEvaluation(
            outcome=EvaluationOutcome.TRIGGERED,
            observed_value={"materials_count": 0},
            expected_value={"materials_count": "> 0"},
        )]
    return [RuleEvaluation(outcome=EvaluationOutcome.PASS)]


# ---------------------------------------------------------------------------
# 5.  EXTERNAL_MISSING_TEXTURE
# ---------------------------------------------------------------------------
def evaluate_external_missing_texture(ctx: AssessmentContext, config: Dict[str, Any]) -> List[RuleEvaluation]:
    """Trigger when any image has resource_status not in the acceptable set."""
    if not ctx.images:
        return [RuleEvaluation(outcome=EvaluationOutcome.NOT_APPLICABLE)]

    acceptable = set(config.get("acceptable_resource_status", ["PACKED", "EXTERNAL_PRESENT", "GENERATED"]))
    missing = []
    for img in ctx.images:
        status = img.get("resource_status", "UNKNOWN")
        if status == "EXTERNAL_MISSING":
            missing.append({
                "image_index": img.get("image_index"),
                "image_name": img.get("image_name"),
                "resource_status": status,
            })

    if missing:
        return [RuleEvaluation(
            outcome=EvaluationOutcome.TRIGGERED,
            observed_value={"missing_images": missing, "count": len(missing)},
            expected_value={"acceptable_resource_status": sorted(acceptable)},
            message_context=f"{len(missing)}",
        )]
    return [RuleEvaluation(outcome=EvaluationOutcome.PASS)]


# ---------------------------------------------------------------------------
# 6.  TEXTURED_MESH_WITHOUT_UV
# ---------------------------------------------------------------------------
def evaluate_textured_mesh_without_uv(ctx: AssessmentContext, config: Dict[str, Any]) -> List[RuleEvaluation]:
    """Trigger when a mesh has a UV-dependent texture but no UV map.

    Only considers uv_mapping_source IN ('DEFAULT', 'EXPLICIT_UV_MAP').
    """
    uv_dependent_sources = set(config.get("uv_dependent_sources", ["DEFAULT", "EXPLICIT_UV_MAP"]))

    # Build a lookup:  material_id -> set of mesh_indexes using it
    mat_to_meshes = {}
    for mm in ctx.mesh_materials:
        mid = mm.get("material_id")
        mesh_idx = mm.get("mesh_index")
        mat_to_meshes.setdefault(mid, set()).add(mesh_idx)

    # Build UV lookup:  mesh_index -> has_uv
    uv_lookup = {uv.get("mesh_index"): uv.get("has_uv", 0) for uv in ctx.uv_summaries}

    # Find UV-dependent material-texture relationships
    issues = []
    seen = set()  # Dedup key: (mesh_index, material_id)
    for mt in ctx.material_textures:
        if mt.get("uv_mapping_source") not in uv_dependent_sources:
            continue
        mid = mt.get("material_id")
        mesh_indexes = mat_to_meshes.get(mid, set())
        for mesh_idx in mesh_indexes:
            dedup_key = (mesh_idx, mid)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            if uv_lookup.get(mesh_idx, 0) == 0:
                mesh_name = _mesh_name_for_index(ctx, mesh_idx)
                mat_name = _material_name_for_id(ctx, mid)
                issues.append(RuleEvaluation(
                    outcome=EvaluationOutcome.TRIGGERED,
                    observed_value={
                        "mesh_index": mesh_idx, "material_id": mid,
                        "has_uv": 0, "mesh_name": mesh_name,
                        "material_name": mat_name,
                    },
                    expected_value={"has_uv": 1},
                    message_context=f"mesh_name={mesh_name}, material_name={mat_name}",
                    subject_type="MESH",
                    subject_key=str(mesh_idx),
                ))

    if issues:
        return issues
    if not ctx.material_textures:
        return [RuleEvaluation(outcome=EvaluationOutcome.NOT_APPLICABLE)]
    return [RuleEvaluation(outcome=EvaluationOutcome.PASS)]


# ---------------------------------------------------------------------------
# 7.  EXPLICIT_UV_LAYER_MISSING
# ---------------------------------------------------------------------------
def evaluate_explicit_uv_layer_missing(ctx: AssessmentContext, config: Dict[str, Any]) -> List[RuleEvaluation]:
    """Trigger when a texture explicitly requests a UV map name that
    does not exist on the assigned mesh.

    Join path: asset_material_textures → material_id → asset_mesh_materials
    → mesh_index → asset_uv_summary.
    """
    # Build lookups
    mat_to_meshes = {}
    for mm in ctx.mesh_materials:
        mid = mm.get("material_id")
        mesh_idx = mm.get("mesh_index")
        mat_to_meshes.setdefault(mid, set()).add(mesh_idx)

    uv_layers_lookup = {}  # mesh_index -> set of layer names
    for uv in ctx.uv_summaries:
        mesh_idx = uv.get("mesh_index")
        names_json = uv.get("uv_layer_names_json", "[]")
        try:
            names = set(json.loads(names_json))
        except (json.JSONDecodeError, TypeError):
            names = set()
        uv_layers_lookup[mesh_idx] = names

    issues = []
    seen = set()  # Dedup: (mesh_index, material_id, uv_map_name)
    for mt in ctx.material_textures:
        if mt.get("uv_mapping_source") != "EXPLICIT_UV_MAP":
            continue
        requested_uv = mt.get("uv_map_name")
        if not requested_uv:
            continue
        mid = mt.get("material_id")
        mesh_indexes = mat_to_meshes.get(mid, set())
        for mesh_idx in mesh_indexes:
            dedup_key = (mesh_idx, mid, requested_uv)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            available = uv_layers_lookup.get(mesh_idx, set())
            if requested_uv not in available:
                mesh_name = _mesh_name_for_index(ctx, mesh_idx)
                issues.append(RuleEvaluation(
                    outcome=EvaluationOutcome.TRIGGERED,
                    observed_value={"requested_uv": requested_uv, "available_uvs": sorted(available)},
                    expected_value={"uv_present": True},
                    message_context=f"requested_uv={requested_uv}, mesh_name={mesh_name}, available_uvs={sorted(available)}",
                    subject_type="MESH",
                    subject_key=str(mesh_idx),
                ))

    if issues:
        return issues
    # Check if there are any EXPLICIT_UV_MAP textures at all
    has_explicit = any(mt.get("uv_mapping_source") == "EXPLICIT_UV_MAP" for mt in ctx.material_textures)
    if not has_explicit:
        return [RuleEvaluation(outcome=EvaluationOutcome.NOT_APPLICABLE)]
    return [RuleEvaluation(outcome=EvaluationOutcome.PASS)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mesh_name_for_index(ctx: AssessmentContext, mesh_index: int) -> str:
    for uv in ctx.uv_summaries:
        if uv.get("mesh_index") == mesh_index:
            return uv.get("mesh_name", f"mesh_{mesh_index}")
    return f"mesh_{mesh_index}"


def _material_name_for_id(ctx: AssessmentContext, material_id: int) -> str:
    for m in ctx.materials:
        if m.get("id") == material_id:
            return m.get("material_name", f"material_{material_id}")
    return f"material_{material_id}"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
EVALUATOR_REGISTRY = {
    "NO_MESH_OBJECTS": evaluate_no_mesh_objects,
    "ZERO_GEOMETRY": evaluate_zero_geometry,
    "INVALID_BOUNDING_BOX": evaluate_invalid_bounding_box,
    "NO_MATERIALS": evaluate_no_materials,
    "EXTERNAL_MISSING_TEXTURE": evaluate_external_missing_texture,
    "TEXTURED_MESH_WITHOUT_UV": evaluate_textured_mesh_without_uv,
    "EXPLICIT_UV_LAYER_MISSING": evaluate_explicit_uv_layer_missing,
}
