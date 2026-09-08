import hashlib
import json
import sqlite3
from typing import Optional, Tuple, Dict
from .models import Lineage

def compute_input_signature(
    source_fingerprint: str,
    basic_analysis_run_id: str,
    deep_analysis_run_id: str,
    preview_id: str,
    ruleset_version: str,
    ruleset_hash: str,
    assessor_version: str
) -> str:
    payload = {
        "assessor_version": assessor_version,
        "basic_analysis_run_id": basic_analysis_run_id,
        "deep_analysis_run_id": deep_analysis_run_id,
        "preview_id": preview_id,
        "ruleset_hash": ruleset_hash,
        "ruleset_version": ruleset_version,
        "source_fingerprint": source_fingerprint
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()

def resolve_asset_lineage(conn: sqlite3.Connection, asset_id: str) -> Tuple[Optional[Lineage], Optional[str]]:
    """Resolves upstream lineage and returns (Lineage, blocked_reason)."""
    conn.row_factory = sqlite3.Row
    asset_row = conn.execute(
        "SELECT is_present, analysis_status, deep_analysis_status, preview_status, file_size_bytes, modified_time_ns FROM assets WHERE asset_id = ?",
        (asset_id,)
    ).fetchone()
    
    if not asset_row:
        return None, "ASSET_NOT_FOUND"
        
    if not asset_row['is_present']:
        return None, "ASSET_NOT_PRESENT"
        
    source_fingerprint = f"{asset_row['file_size_bytes']}:{asset_row['modified_time_ns']}"
    
    # Check basic analysis
    if asset_row['analysis_status'] != 'SUCCESS':
        return None, "BASIC_ANALYSIS_NOT_READY"
        
    basic_run = conn.execute("""
        SELECT analysis_run_id 
        FROM analysis_runs 
        WHERE asset_id = ? AND status = 'SUCCESS' AND analysis_profile = 'BASIC' 
        ORDER BY finished_at DESC, id DESC LIMIT 1
    """, (asset_id,)).fetchone()
    
    if not basic_run:
        return None, "MISSING_BASIC_LINEAGE"
        
    # Check deep analysis
    if asset_row['deep_analysis_status'] != 'SUCCESS':
        return None, "DEEP_ANALYSIS_NOT_READY"
        
    deep_run = conn.execute("""
        SELECT analysis_run_id 
        FROM analysis_runs 
        WHERE asset_id = ? AND status = 'SUCCESS' AND analysis_profile = 'DEEP' 
        ORDER BY finished_at DESC, id DESC LIMIT 1
    """, (asset_id,)).fetchone()
    
    if not deep_run:
        return None, "MISSING_DEEP_LINEAGE"
        
    # Check preview
    if asset_row['preview_status'] != 'SUCCESS':
        return None, "PREVIEW_NOT_READY"
        
    preview = conn.execute("""
        SELECT preview_id, source_fingerprint 
        FROM asset_previews 
        WHERE asset_id = ? AND status = 'SUCCESS' AND preview_type = 'HERO' 
        ORDER BY finished_at DESC, id DESC LIMIT 1
    """, (asset_id,)).fetchone()
    
    if not preview:
        return None, "MISSING_PREVIEW_LINEAGE"
        
    if preview['source_fingerprint'] != source_fingerprint:
        return None, "PREVIEW_SOURCE_MISMATCH"
        
    # Resolve render_run_id from preview
    preview_render = conn.execute(
        "SELECT render_run_id FROM asset_previews WHERE preview_id = ?",
        (preview['preview_id'],)
    ).fetchone()

    return Lineage(
        asset_id=asset_id,
        source_fingerprint=source_fingerprint,
        source_file_size_bytes=asset_row['file_size_bytes'],
        source_modified_time_ns=asset_row['modified_time_ns'],
        basic_analysis_run_id=basic_run['analysis_run_id'],
        deep_analysis_run_id=deep_run['analysis_run_id'],
        preview_id=preview['preview_id'],
        render_run_id=preview_render['render_run_id'] if preview_render else None,
    ), None
