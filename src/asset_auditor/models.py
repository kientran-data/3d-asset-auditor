import dataclasses

@dataclasses.dataclass
class AssetRecord:
    asset_id: str
    source_root: str
    absolute_path: str
    relative_path: str
    filename: str
    stem: str
    extension: str
    file_size_bytes: int
    file_size_mb: float
    modified_time_ns: int
    modified_at: str
    parent_directory: str
    top_level_directory: str
    directory_depth: int
    format_status: str
    scan_status: str
    analysis_status: str
    preview_status: str
    assessment_status: str
    discovered_at: str
    updated_at: str
    is_present: int = 1
