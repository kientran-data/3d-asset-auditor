"""Dispatcher for Phase 3B Thumbnail Rendering."""
import json
import logging
import os
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image

from asset_auditor.config import (
    BLENDER_EXECUTABLE,
    BLENDER_SAFE_ARGS,
    RENDERER_VERSION,
    PREVIEW_SCHEMA_VERSION,
    ANALYSIS_TIMEOUT_SECONDS
)

logger = logging.getLogger(__name__)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def run_render(
    conn: sqlite3.Connection,
    asset_id: str,
    asset_path: str,
    source_root: str,
    timeout: int = ANALYSIS_TIMEOUT_SECONDS
):
    """Render a single asset and persist to DB."""
    
    # Check eligibility and source
    cursor = conn.cursor()
    cursor.execute("""
        SELECT is_present, analysis_status, extension, file_size_bytes, modified_time_ns 
        FROM assets WHERE asset_id = ?
    """, (asset_id,))
    row = cursor.fetchone()
    
    if not row:
        logger.error(f"Asset {asset_id} not found.")
        return
        
    is_present, analysis_status, extension, file_size, modified_time_ns = row
    
    if is_present != 1 or analysis_status != 'SUCCESS' or extension.lower() not in ('.glb', '.gltf'):
        logger.info(f"Asset {asset_id} ineligible for rendering (present={is_present}, status={analysis_status}, ext={extension}).")
        return
        
    # Generate IDs and Paths
    preview_id = str(uuid.uuid4())
    render_run_id = str(uuid.uuid4())
    started_at = _now_iso()
    
    previews_dir = os.path.join(source_root, "reports", "previews", asset_id, preview_id)
    os.makedirs(previews_dir, exist_ok=True)
    output_png = os.path.join(previews_dir, "hero.png")
    
    # Source fingerprint
    fingerprint = f"{file_size}:{modified_time_ns}"
    
    # Mark RENDERING (stale RENDERING should be recovered beforehand or handled if they are overwritten)
    # We will reset any previous preview status for this asset to RENDERING
    conn.execute("UPDATE assets SET preview_status = 'RENDERING' WHERE asset_id = ?", (asset_id,))
    conn.commit()

    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "blender",
        "render_preview.py",
    )
    
    cmd = [
        BLENDER_EXECUTABLE,
        *BLENDER_SAFE_ARGS,
        "--python", script_path,
        "--",
        "--input", asset_path,
        "--output", output_png,
        "--asset-id", asset_id,
        "--preview-id", preview_id
    ]
    
    start_time = time.monotonic()
    
    blender_version = "unknown"
    render_engine = "unknown"
    status = "FAILED_RENDER"
    error_message = None
    error_type = None
    width_px = None
    height_px = None
    render_settings_json = None
    
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        stdout = proc.stdout
        
        # Extract JSON
        json_str = None
        if "---RESULT_JSON_START---" in stdout and "---RESULT_JSON_END---" in stdout:
            parts = stdout.split("---RESULT_JSON_START---")
            if len(parts) > 1:
                json_part = parts[1].split("---RESULT_JSON_END---")[0].strip()
                json_str = json_part
                
        if json_str:
            try:
                data = json.loads(json_str)
                status = data.get("status", "FAILED_RENDER")
                error_message = data.get("error_message")
                error_type = data.get("error_type")
                blender_version = data.get("blender_version", "unknown")
                render_engine = data.get("render_engine", "unknown")
                width_px = data.get("width")
                height_px = data.get("height")
                render_settings_json = json.dumps(data.get("render_settings", {}))
            except json.JSONDecodeError:
                status = "FAILED_RENDER"
                error_type = "JSONDecodeError"
                error_message = "Could not parse stdout JSON"
        else:
            status = "FAILED_RENDER"
            error_type = "MissingJSON"
            error_message = f"Exit code {proc.returncode}"
            logger.error(f"Missing JSON. stdout: {stdout}\nstderr: {proc.stderr}")
            
    except subprocess.TimeoutExpired:
        status = "TIMEOUT"
        error_type = "TimeoutExpired"
        error_message = f"Exceeded {timeout}s"
    except Exception as e:
        status = "FAILED_RENDER"
        error_type = type(e).__name__
        error_message = str(e)
        
    duration_ms = int((time.monotonic() - start_time) * 1000)
    
    # Pillow Output Validation
    if status == "SUCCESS":
        if not os.path.exists(output_png):
            status = "FAILED_RENDER"
            error_type = "MissingOutput"
            error_message = "PNG not found on disk"
        elif os.path.getsize(output_png) == 0:
            status = "FAILED_RENDER"
            error_type = "ZeroByteOutput"
            error_message = "PNG is 0 bytes"
        else:
            try:
                with Image.open(output_png) as img:
                    img.verify()
                with Image.open(output_png) as img:
                    w, h = img.size
                    if w != 1024 or h != 1024:
                        status = "FAILED_RENDER"
                        error_type = "InvalidDimensions"
                        error_message = f"Expected 1024x1024, got {w}x{h}"
            except Exception as e:
                status = "FAILED_RENDER"
                error_type = "InvalidImage"
                error_message = str(e)

    # Persist
    finished_at = _now_iso()
    
    conn.execute("""
        INSERT INTO asset_previews (
            preview_id, asset_id, render_run_id, renderer_version, render_schema_version,
            blender_version, render_engine, status, preview_type, output_path,
            width_px, height_px, file_format, camera_mode, render_settings_json,
            source_file_size_bytes, source_modified_time_ns, source_fingerprint,
            started_at, finished_at, duration_ms, error_type, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        preview_id, asset_id, render_run_id, RENDERER_VERSION, PREVIEW_SCHEMA_VERSION,
        blender_version, render_engine, status, "HERO", output_png if status == "SUCCESS" else None,
        width_px if status == "SUCCESS" else None, height_px if status == "SUCCESS" else None,
        "PNG" if status == "SUCCESS" else None, "PERSPECTIVE" if status == "SUCCESS" else None,
        render_settings_json,
        file_size, modified_time_ns, fingerprint,
        started_at, finished_at, duration_ms, error_type, error_message
    ))
    
    # Only update preview_status!
    conn.execute("UPDATE assets SET preview_status = ? WHERE asset_id = ?", (status, asset_id))
    conn.commit()

def recover_stale_renders(conn: sqlite3.Connection):
    """Reset RENDERING status to PENDING on startup."""
    cursor = conn.cursor()
    cursor.execute("UPDATE assets SET preview_status = 'PENDING' WHERE preview_status = 'RENDERING'")
    count = cursor.rowcount
    conn.commit()
    if count > 0:
        logger.info(f"Recovered {count} stale RENDERING assets back to PENDING.")
    return count

def run_batch_render(
    conn: sqlite3.Connection,
    source_root: str = None,
    asset_id: str = None,
    include_failed: bool = False,
    timeout: int = ANALYSIS_TIMEOUT_SECONDS
) -> dict:
    """Run rendering on multiple eligible assets."""
    recover_stale_renders(conn)
    
    query = """
        SELECT asset_id, absolute_path, source_root, filename 
        FROM assets 
        WHERE is_present = 1 
          AND analysis_status = 'SUCCESS' 
          AND LOWER(extension) IN ('.glb', '.gltf')
    """
    
    if asset_id:
        query += f" AND asset_id = '{asset_id}'"
    elif not include_failed:
        query += " AND preview_status = 'PENDING'"
    
    if source_root:
        query += " AND source_root = ?"
        params = (source_root,)
    else:
        params = ()
        
    cursor = conn.execute(query, params)
    assets_to_render = cursor.fetchall()
    
    stats = {
        "total": len(assets_to_render),
        "success": 0,
        "failed_render": 0,
        "timeout": 0,
        "durations": []
    }
    
    print(f"Found {stats['total']} assets eligible for rendering.")
    
    for i, row in enumerate(assets_to_render, 1):
        a_id, absolute_path, s_root, filename = row
        print(f"[{i}/{stats['total']}] Rendering {filename} ({a_id})...")
        
        start_time = time.monotonic()
        run_render(conn, a_id, absolute_path, s_root, timeout)
        
        # Check result
        p_status = conn.execute("SELECT preview_status FROM assets WHERE asset_id = ?", (a_id,)).fetchone()[0]
        duration_ms = conn.execute("SELECT duration_ms FROM asset_previews WHERE asset_id = ? ORDER BY id DESC LIMIT 1", (a_id,)).fetchone()
        
        duration_str = ""
        if duration_ms and duration_ms[0]:
            stats["durations"].append(duration_ms[0])
            duration_str = f" in {duration_ms[0]/1000.0:.2f}s"
            
        if p_status == "SUCCESS":
            stats["success"] += 1
            print(f"  -> SUCCESS{duration_str}")
        elif p_status == "TIMEOUT":
            stats["timeout"] += 1
            print(f"  -> TIMEOUT{duration_str}")
        else:
            stats["failed_render"] += 1
            print(f"  -> FAILED_RENDER{duration_str}")
            
    return stats
