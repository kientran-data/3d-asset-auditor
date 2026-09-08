"""Centralized 3D format registry.

This is the single source of truth for all recognized 3D file extensions.
Do NOT duplicate these lists elsewhere in the codebase.
"""
from enum import Enum


class FormatStatus(Enum):
    """Classification of a file extension's support level for deep analysis."""
    MVP_SUPPORTED = "MVP_SUPPORTED"
    SUPPORTED_LATER = "SUPPORTED_LATER"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    NON_3D = "NON_3D"


# Extensions that Phase 2 will analyze via Blender headless
MVP_FORMATS = frozenset({".blend", ".fbx", ".obj", ".glb", ".gltf", ".stl"})

# Extensions Blender may support but are deferred beyond MVP
LATER_FORMATS = frozenset({".ply", ".dae", ".3ds"})

# Extensions that require proprietary tools and cannot be deeply analyzed
UNSUPPORTED_FORMATS = frozenset({".max", ".c4d"})

# Union of all recognized 3D extensions for quick membership tests
ALL_3D_FORMATS = MVP_FORMATS | LATER_FORMATS | UNSUPPORTED_FORMATS


def get_format_status(extension: str) -> FormatStatus:
    """Return the support classification for a file extension.

    Extension matching is case-insensitive.
    """
    ext = extension.lower()
    if ext in MVP_FORMATS:
        return FormatStatus.MVP_SUPPORTED
    if ext in LATER_FORMATS:
        return FormatStatus.SUPPORTED_LATER
    if ext in UNSUPPORTED_FORMATS:
        return FormatStatus.UNSUPPORTED_FORMAT
    return FormatStatus.NON_3D


def initial_analysis_status(format_status: FormatStatus) -> str:
    """Return the correct initial analysis_status for a given format classification.

    - MVP_SUPPORTED  → "PENDING" (will be analyzed by Blender)
    - SUPPORTED_LATER → "SUPPORTED_LATER" (deferred, not yet analyzable)
    - UNSUPPORTED_FORMAT → "UNSUPPORTED_FORMAT" (no analyzer available)
    """
    if format_status == FormatStatus.MVP_SUPPORTED:
        return "PENDING"
    if format_status == FormatStatus.SUPPORTED_LATER:
        return "SUPPORTED_LATER"
    if format_status == FormatStatus.UNSUPPORTED_FORMAT:
        return "UNSUPPORTED_FORMAT"
    return "PENDING"
