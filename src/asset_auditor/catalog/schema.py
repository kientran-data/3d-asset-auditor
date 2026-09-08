"""SQLite schema definitions.

Phase 1: assets table
Phase 2A: analysis_runs + asset_geometry tables
"""

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT UNIQUE NOT NULL,
    source_root TEXT NOT NULL,
    absolute_path TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    stem TEXT NOT NULL,
    extension TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    file_size_mb REAL NOT NULL,
    modified_time_ns INTEGER NOT NULL,
    modified_at DATETIME NOT NULL,
    parent_directory TEXT NOT NULL,
    top_level_directory TEXT NOT NULL,
    directory_depth INTEGER NOT NULL,
    format_status TEXT NOT NULL,
    scan_status TEXT NOT NULL,
    analysis_status TEXT NOT NULL,
    preview_status TEXT NOT NULL,
    assessment_status TEXT NOT NULL,
    discovered_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    is_present INTEGER NOT NULL DEFAULT 1,
    UNIQUE(source_root, absolute_path)
);

CREATE INDEX IF NOT EXISTS idx_assets_extension ON assets(extension);
CREATE INDEX IF NOT EXISTS idx_assets_format_status ON assets(format_status);
CREATE INDEX IF NOT EXISTS idx_assets_scan_status ON assets(scan_status);
CREATE INDEX IF NOT EXISTS idx_assets_analysis_status ON assets(analysis_status);
CREATE INDEX IF NOT EXISTS idx_assets_source_root ON assets(source_root);
"""

SCHEMA_V2_ANALYSIS = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_run_id TEXT UNIQUE NOT NULL,
    asset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    blender_version TEXT,
    analyzer_version TEXT NOT NULL,
    analysis_schema_version TEXT NOT NULL,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    duration_ms INTEGER,
    blender_exit_code INTEGER,
    error_type TEXT,
    error_message TEXT,
    stdout_tail TEXT,
    stderr_tail TEXT,
    FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_asset_id ON analysis_runs(asset_id);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_status ON analysis_runs(status);

CREATE TABLE IF NOT EXISTS asset_geometry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_run_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    objects_count INTEGER,
    mesh_objects_count INTEGER,
    empty_count INTEGER,
    camera_count INTEGER,
    light_count INTEGER,
    armature_count INTEGER,
    vertices INTEGER,
    edges INTEGER,
    faces INTEGER,
    triangles INTEGER,
    materials_count INTEGER,
    images_count INTEGER,
    bbox_min_x REAL,
    bbox_min_y REAL,
    bbox_min_z REAL,
    bbox_max_x REAL,
    bbox_max_y REAL,
    bbox_max_z REAL,
    width REAL,
    depth REAL,
    height REAL,
    unit_system TEXT,
    unit_scale_length REAL,
    FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs(analysis_run_id),
    FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);

CREATE INDEX IF NOT EXISTS idx_asset_geometry_asset_id ON asset_geometry(asset_id);
CREATE INDEX IF NOT EXISTS idx_asset_geometry_run_id ON asset_geometry(analysis_run_id);
"""
