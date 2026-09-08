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
