"""Centralized configuration for the 3D Asset Auditor."""
import os
import shutil

# Analyzer versioning
ANALYZER_VERSION = "0.2.0"
ANALYSIS_SCHEMA_VERSION = "1"

# Blender configuration
BLENDER_EXECUTABLE = os.environ.get("BLENDER_EXECUTABLE", "blender")
ANALYSIS_TIMEOUT_SECONDS = int(os.environ.get("ANALYSIS_TIMEOUT", "120"))

# Blender subprocess security arguments
BLENDER_SAFE_ARGS = [
    "--background",
    "--factory-startup",
    "--disable-autoexec",
]

# Maximum bytes of stdout/stderr to store in database
MAX_LOG_TAIL_BYTES = 8192


def get_blender_executable() -> str:
    """Return the Blender executable path, validating it exists."""
    exe = BLENDER_EXECUTABLE
    resolved = shutil.which(exe)
    if resolved:
        return resolved
    if os.path.isfile(exe) and os.access(exe, os.X_OK):
        return exe
    raise FileNotFoundError(
        f"Blender executable not found: '{exe}'. "
        f"Set BLENDER_EXECUTABLE environment variable or install Blender."
    )


def get_blender_script_path() -> str:
    """Return the path to the Blender analysis script."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "blender",
        "analyze_asset.py",
    )
