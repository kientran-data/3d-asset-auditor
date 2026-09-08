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

SCHEMA_V3_PHASE3A = """
CREATE TABLE IF NOT EXISTS asset_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_run_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    material_index INTEGER NOT NULL,
    material_name TEXT,
    use_nodes INTEGER,
    node_count INTEGER,
    image_texture_node_count INTEGER,
    principled_bsdf_count INTEGER,
    UNIQUE(analysis_run_id, material_index),
    FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs(analysis_run_id),
    FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);

CREATE TABLE IF NOT EXISTS asset_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_run_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    image_index INTEGER NOT NULL,
    image_name TEXT,
    width INTEGER,
    height INTEGER,
    channels INTEGER,
    file_format TEXT,
    source_type TEXT,
    colorspace_name TEXT,
    packed INTEGER,
    original_filepath TEXT,
    resolved_filepath TEXT,
    exists_on_disk INTEGER,
    resource_status TEXT,
    UNIQUE(analysis_run_id, image_index),
    FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs(analysis_run_id),
    FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);

CREATE TABLE IF NOT EXISTS asset_material_textures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_run_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    material_id INTEGER NOT NULL,
    image_id INTEGER NOT NULL,
    node_name TEXT,
    texture_role TEXT,
    uv_mapping_source TEXT,
    uv_map_name TEXT,
    FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs(analysis_run_id),
    FOREIGN KEY(asset_id) REFERENCES assets(asset_id),
    FOREIGN KEY(material_id) REFERENCES asset_materials(id),
    FOREIGN KEY(image_id) REFERENCES asset_images(id)
);

CREATE TABLE IF NOT EXISTS asset_uv_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_run_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    mesh_index INTEGER NOT NULL,
    mesh_name TEXT,
    uv_layer_count INTEGER,
    uv_layer_names_json TEXT,
    active_uv_layer TEXT,
    has_uv INTEGER,
    UNIQUE(analysis_run_id, mesh_index),
    FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs(analysis_run_id),
    FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);

CREATE TABLE IF NOT EXISTS asset_mesh_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_run_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    object_index INTEGER NOT NULL,
    object_name TEXT,
    mesh_index INTEGER NOT NULL,
    mesh_name TEXT,
    material_id INTEGER NOT NULL,
    material_slot_index INTEGER,
    material_link_mode TEXT,
    FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs(analysis_run_id),
    FOREIGN KEY(asset_id) REFERENCES assets(asset_id),
    FOREIGN KEY(material_id) REFERENCES asset_materials(id)
);

CREATE INDEX IF NOT EXISTS idx_asset_materials_asset_id ON asset_materials(asset_id);
CREATE INDEX IF NOT EXISTS idx_asset_images_asset_id ON asset_images(asset_id);
CREATE INDEX IF NOT EXISTS idx_asset_material_textures_asset_id ON asset_material_textures(asset_id);
CREATE INDEX IF NOT EXISTS idx_asset_uv_summary_asset_id ON asset_uv_summary(asset_id);
CREATE INDEX IF NOT EXISTS idx_asset_mesh_materials_asset_id ON asset_mesh_materials(asset_id);
"""

SCHEMA_V4_PHASE3B = """
CREATE TABLE IF NOT EXISTS asset_previews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preview_id TEXT UNIQUE NOT NULL,
    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    render_run_id TEXT UNIQUE NOT NULL,
    renderer_version TEXT NOT NULL,
    render_schema_version TEXT NOT NULL,
    blender_version TEXT NOT NULL,
    render_engine TEXT NOT NULL,
    status TEXT NOT NULL,
    preview_type TEXT NOT NULL,
    output_path TEXT,
    width_px INTEGER,
    height_px INTEGER,
    file_format TEXT,
    camera_mode TEXT,
    render_settings_json TEXT,
    source_file_size_bytes INTEGER,
    source_modified_time_ns INTEGER,
    source_fingerprint TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER,
    error_type TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_asset_previews_asset_id ON asset_previews(asset_id);
CREATE INDEX IF NOT EXISTS idx_asset_previews_status ON asset_previews(status);
CREATE INDEX IF NOT EXISTS idx_asset_previews_preview_type ON asset_previews(preview_type);
"""

SCHEMA_V5_PHASE4A = """
CREATE TABLE IF NOT EXISTS assessment_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_run_id TEXT UNIQUE NOT NULL,
    assessor_version TEXT NOT NULL,
    ruleset_version TEXT,
    ruleset_hash TEXT,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    status TEXT NOT NULL,
    requested_asset_count INTEGER,
    assessed_asset_count INTEGER,
    skipped_asset_count INTEGER,
    blocked_asset_count INTEGER,
    failed_asset_count INTEGER
);

CREATE TABLE IF NOT EXISTS asset_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    assessment_id TEXT UNIQUE NOT NULL,
    assessment_run_id TEXT NOT NULL REFERENCES assessment_runs(assessment_run_id),
    asset_id TEXT NOT NULL REFERENCES assets(asset_id),

    assessment_status TEXT NOT NULL,
    assessor_version TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    ruleset_hash TEXT NOT NULL,

    basic_analysis_run_id TEXT NOT NULL,
    deep_analysis_run_id TEXT NOT NULL,
    preview_id TEXT NOT NULL,
    render_run_id TEXT NOT NULL,

    analysis_schema_version TEXT NOT NULL,
    deep_analysis_schema_version TEXT NOT NULL,
    render_schema_version TEXT NOT NULL,

    source_file_size_bytes INTEGER NOT NULL,
    source_modified_time_ns INTEGER NOT NULL,
    source_fingerprint TEXT NOT NULL,

    assessment_input_signature TEXT NOT NULL,

    geometry_score REAL,
    material_score REAL,
    texture_score REAL,
    preview_score REAL,
    naming_score REAL,
    packaging_score REAL,
    overall_score REAL,

    readiness_status TEXT,

    blocking_reasons_json TEXT NOT NULL DEFAULT '[]',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    assessment_details_json TEXT NOT NULL DEFAULT '{}',

    assessed_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS assessment_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id TEXT NOT NULL REFERENCES asset_assessments(assessment_id),
    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    
    rule_code TEXT NOT NULL,
    
    severity TEXT NOT NULL,
    disposition TEXT NOT NULL,
    
    category TEXT,
    message TEXT NOT NULL,
    
    observed_value_json TEXT,
    expected_value_json TEXT,
    details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_asset_assessments_asset ON asset_assessments(asset_id);
CREATE INDEX IF NOT EXISTS idx_asset_assessments_signature ON asset_assessments(asset_id, assessment_input_signature);
CREATE INDEX IF NOT EXISTS idx_asset_assessments_status ON asset_assessments(assessment_status);
CREATE INDEX IF NOT EXISTS idx_asset_assessments_readiness ON asset_assessments(readiness_status);
CREATE INDEX IF NOT EXISTS idx_asset_assessments_run ON asset_assessments(assessment_run_id);

CREATE INDEX IF NOT EXISTS idx_assessment_issues_assessment ON assessment_issues(assessment_id);
CREATE INDEX IF NOT EXISTS idx_assessment_issues_asset ON assessment_issues(asset_id);
CREATE INDEX IF NOT EXISTS idx_assessment_issues_rule ON assessment_issues(rule_code);
CREATE INDEX IF NOT EXISTS idx_assessment_issues_severity ON assessment_issues(severity);
CREATE INDEX IF NOT EXISTS idx_assessment_issues_disposition ON assessment_issues(disposition);
"""

SCHEMA_V6_PHASE4B2 = """
CREATE TABLE IF NOT EXISTS assessment_run_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_run_id TEXT NOT NULL REFERENCES assessment_runs(assessment_run_id),
    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    decision TEXT NOT NULL,
    execution_status TEXT,
    blocked_reason TEXT,
    assessment_id TEXT,
    assessment_input_signature TEXT,
    started_at DATETIME,
    finished_at DATETIME,
    error_type TEXT,
    error_message TEXT,
    UNIQUE(assessment_run_id, asset_id)
);

CREATE INDEX IF NOT EXISTS idx_assessment_run_items_run ON assessment_run_items(assessment_run_id);
CREATE INDEX IF NOT EXISTS idx_assessment_run_items_asset ON assessment_run_items(asset_id);
CREATE INDEX IF NOT EXISTS idx_assessment_run_items_decision ON assessment_run_items(decision);
CREATE INDEX IF NOT EXISTS idx_assessment_run_items_status ON assessment_run_items(execution_status);
"""
