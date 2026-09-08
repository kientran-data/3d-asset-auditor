"""Blender subprocess runner with timeout and process isolation.

Each asset is analyzed in its own Blender subprocess.
The runner creates a temporary work directory, spawns Blender with safe
security flags, captures stdout/stderr, enforces a timeout, reads the
structured JSON result, and cleans up.
"""
import json
import logging
import os
import signal
import subprocess
import tempfile
import uuid
from datetime import datetime, UTC
from typing import Optional, Dict, Any

from ..config import (
    BLENDER_SAFE_ARGS,
    ANALYSIS_TIMEOUT_SECONDS,
    ANALYZER_VERSION,
    ANALYSIS_SCHEMA_VERSION,
    MAX_LOG_TAIL_BYTES,
    get_blender_executable,
    get_blender_script_path,
)

logger = logging.getLogger(__name__)


class AnalysisResult:
    """Container for a single asset analysis outcome."""

    def __init__(
        self,
        analysis_run_id: str,
        asset_id: str,
        status: str,
        blender_version: Optional[str] = None,
        analyzer_version: str = ANALYZER_VERSION,
        analysis_schema_version: str = ANALYSIS_SCHEMA_VERSION,
        started_at: str = "",
        finished_at: str = "",
        duration_ms: int = 0,
        blender_exit_code: Optional[int] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        stdout_tail: Optional[str] = None,
        stderr_tail: Optional[str] = None,
        result_data: Optional[Dict[str, Any]] = None,
    ):
        self.analysis_run_id = analysis_run_id
        self.asset_id = asset_id
        self.status = status
        self.blender_version = blender_version
        self.analyzer_version = analyzer_version
        self.analysis_schema_version = analysis_schema_version
        self.started_at = started_at
        self.finished_at = finished_at
        self.duration_ms = duration_ms
        self.blender_exit_code = blender_exit_code
        self.error_type = error_type
        self.error_message = error_message
        self.stdout_tail = stdout_tail
        self.stderr_tail = stderr_tail
        self.result_data = result_data


def run_blender_analysis(
    asset_id: str,
    asset_path: str,
    timeout: int = ANALYSIS_TIMEOUT_SECONDS,
) -> AnalysisResult:
    """Run Blender headless analysis on a single asset.

    Returns an AnalysisResult regardless of success or failure.
    Never raises exceptions that would stop the batch.
    """
    analysis_run_id = str(uuid.uuid4())
    started_at = datetime.now(UTC).isoformat()

    try:
        blender_exe = get_blender_executable()
    except FileNotFoundError as e:
        return AnalysisResult(
            analysis_run_id=analysis_run_id,
            asset_id=asset_id,
            status="FAILED_ANALYSIS",
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
            duration_ms=0,
            error_type="BlenderNotFound",
            error_message=str(e),
        )

    script_path = get_blender_script_path()
    if not os.path.isfile(script_path):
        return AnalysisResult(
            analysis_run_id=analysis_run_id,
            asset_id=asset_id,
            status="FAILED_ANALYSIS",
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
            duration_ms=0,
            error_type="ScriptNotFound",
            error_message=f"Analysis script not found: {script_path}",
        )

    # Create temporary work directory
    temp_dir = tempfile.mkdtemp(prefix="asset_auditor_")
    result_json_path = os.path.join(temp_dir, "result.json")

    cmd = [
        blender_exe,
        *BLENDER_SAFE_ARGS,
        "--python", script_path,
        "--",
        "--input", asset_path,
        "--output", result_json_path,
        "--asset-id", asset_id,
    ]

    logger.debug("Running: %s", " ".join(cmd))

    try:
        start_time = datetime.now(UTC)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Graceful terminate
            proc.terminate()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()

            end_time = datetime.now(UTC)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            return AnalysisResult(
                analysis_run_id=analysis_run_id,
                asset_id=asset_id,
                status="TIMEOUT",
                started_at=started_at,
                finished_at=end_time.isoformat(),
                duration_ms=duration_ms,
                blender_exit_code=-1,
                error_type="Timeout",
                error_message=f"Blender process exceeded {timeout}s timeout",
                stdout_tail=_tail(b"", MAX_LOG_TAIL_BYTES),
                stderr_tail=_tail(b"", MAX_LOG_TAIL_BYTES),
            )

        end_time = datetime.now(UTC)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        exit_code = proc.returncode

        stdout_tail = _tail(stdout_bytes, MAX_LOG_TAIL_BYTES)
        stderr_tail = _tail(stderr_bytes, MAX_LOG_TAIL_BYTES)

        # Read and validate result JSON
        if not os.path.isfile(result_json_path):
            return AnalysisResult(
                analysis_run_id=analysis_run_id,
                asset_id=asset_id,
                status="FAILED_ANALYSIS",
                started_at=started_at,
                finished_at=end_time.isoformat(),
                duration_ms=duration_ms,
                blender_exit_code=exit_code,
                error_type="MissingResult",
                error_message="Blender did not produce result JSON",
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )

        try:
            with open(result_json_path, "r", encoding="utf-8") as f:
                result_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            return AnalysisResult(
                analysis_run_id=analysis_run_id,
                asset_id=asset_id,
                status="FAILED_ANALYSIS",
                started_at=started_at,
                finished_at=end_time.isoformat(),
                duration_ms=duration_ms,
                blender_exit_code=exit_code,
                error_type="MalformedResult",
                error_message=f"Cannot parse result JSON: {e}",
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )

        # Validate result contract
        validation_error = _validate_result(result_data, asset_id)
        if validation_error:
            return AnalysisResult(
                analysis_run_id=analysis_run_id,
                asset_id=asset_id,
                status="FAILED_ANALYSIS",
                started_at=started_at,
                finished_at=end_time.isoformat(),
                duration_ms=duration_ms,
                blender_exit_code=exit_code,
                error_type="InvalidResult",
                error_message=validation_error,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )

        # Map Blender-side status
        blender_status = result_data.get("status", "FAILED_ANALYSIS")
        blender_version = result_data.get("blender_version")

        if blender_status == "FAILED_IMPORT":
            err = result_data.get("error", {})
            return AnalysisResult(
                analysis_run_id=analysis_run_id,
                asset_id=asset_id,
                status="FAILED_IMPORT",
                blender_version=blender_version,
                started_at=started_at,
                finished_at=end_time.isoformat(),
                duration_ms=duration_ms,
                blender_exit_code=exit_code,
                error_type=err.get("type", "ImportError"),
                error_message=err.get("message", "Unknown import error"),
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )

        return AnalysisResult(
            analysis_run_id=analysis_run_id,
            asset_id=asset_id,
            status="SUCCESS",
            blender_version=blender_version,
            started_at=started_at,
            finished_at=end_time.isoformat(),
            duration_ms=duration_ms,
            blender_exit_code=exit_code,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            result_data=result_data,
        )

    except Exception as e:
        end_time = datetime.now(UTC)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        return AnalysisResult(
            analysis_run_id=analysis_run_id,
            asset_id=asset_id,
            status="FAILED_ANALYSIS",
            started_at=started_at,
            finished_at=end_time.isoformat(),
            duration_ms=duration_ms,
            error_type=type(e).__name__,
            error_message=str(e),
        )
    finally:
        # Cleanup temp directory
        try:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def _tail(data: bytes, max_bytes: int) -> str:
    """Return the last max_bytes of data as a string."""
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return data.decode("utf-8", errors="replace")


def _validate_result(data: dict, expected_asset_id: str) -> Optional[str]:
    """Validate the Blender result JSON contract. Returns error string or None."""
    if not isinstance(data, dict):
        return "Result is not a JSON object"
    if "schema_version" not in data:
        return "Missing schema_version"
    if "status" not in data:
        return "Missing status"
    if data.get("asset_id") != expected_asset_id:
        return f"asset_id mismatch: expected {expected_asset_id}, got {data.get('asset_id')}"
    if data["status"] == "SUCCESS":
        for section in ("scene", "geometry", "bounding_box", "units"):
            if section not in data or data[section] is None:
                return f"Missing required section '{section}' on SUCCESS"
    return None
