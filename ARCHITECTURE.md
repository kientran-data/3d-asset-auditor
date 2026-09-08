# System Architecture

## 1. Core Architectural Boundaries

The system is strictly separated into the following domains to prevent mixing of concerns:

- **Scanner:** Determines **"What is on the disk?"** (Filesystem facts only, no business inference).
- **Analyzer:** Determines **"What is inside the model?"** (Raw 3D metadata extracted via Blender).
- **Classifier:** Determines **"What is this model likely to be?"** (Inferred meaning, category, brand).
- **Assessment:** Determines **"Is this model ready to sell?"** (Business quality and scoring).
- **Renderer:** Determines **"What does this model look like?"** (Visual representation/thumbnails).

## 2. Processing States & Lifecycle

Assets do not share a single generic status. Their lifecycle is tracked across multiple distinct states:

- `scan_status`: Tracks the initial discovery and filesystem metadata extraction.
- `analysis_status`: Tracks deep 3D inspection (`PENDING`, `ANALYZING`, `SUCCESS`, `FAILED_IMPORT`, `FAILED_ANALYSIS`, `TIMEOUT`, `UNSUPPORTED_FORMAT`).
- `preview_status`: Tracks thumbnail generation.
- `assessment_status`: Tracks sell-readiness scoring.

## 3. Resumability & File Change Detection

The system uses a lightweight fingerprint to detect changes rather than relying solely on absolute paths.

- **Fingerprint:** Composed of `file_size_bytes` + `modified_time_ns`.
- **Change Detection:** If an asset path exists but its fingerprint has changed, it is marked for re-analysis. SHA256 deduplication is reserved for future enhancements.

## 4. Stable Asset Identifiers

Each asset is assigned a stable identifier:
- `id` (INTEGER PRIMARY KEY) for fast internal database joins.
- `asset_id` (TEXT UNIQUE NOT NULL) formatted as a UUID for stable references in generated reports, JSONs, and external artifacts.

## 5. Source Path Model

Filesystem metadata records raw facts without altering names (e.g., preserving raw folder labels like `PORCHE`).
Fields include: `source_root`, `absolute_path`, `relative_path`, `filename`, `stem`, `extension`, `parent_directory`, `top_level_directory`, `directory_depth`.

## 6. Database Design

The schema avoids a single monolithic `assets` table. It is separated into focused entities:

- `assets`: File facts, stable UUIDs, lifecycle states, and source paths.
- `analysis_runs`: Timing, timeouts, Blender version, analyzer version.
- `asset_geometry`: Vertices, faces, objects, world-space bounding boxes.
- `asset_materials`: Material names and metadata.
- `asset_textures`: Texture file paths (original vs. resolved paths), existence on disk, packed status.
- `asset_rigging`, `asset_animation`, `asset_previews`, `asset_assessments`: Reserved for deep analysis capabilities.

## 7. Blender Process Isolation & Security

Blender is used as a headless worker to inspect supported formats (`.blend`, `.obj`, `.fbx`, `.glb`, `.gltf`, `.stl`). 

**Security:**
The process is strictly isolated and spawned with safe defaults from the command line:
`blender --background --factory-startup --disable-autoexec --python script.py`

**Process Isolation:**
- Each asset gets its own temporary work directory.
- `stdout` and `stderr` are captured separately.
- Strict configurable timeouts force-kill hanging processes.
- The system logs `analysis_started_at`, `analysis_finished_at`, `analysis_duration_ms`, and `blender_exit_code`.

**Import Workflow Differences:**
- `.blend` files: Factory startup → safely open the `.blend` file → inspect scene.
- Imported formats (`.fbx`, etc.): Factory startup → clean scene → run import operator → inspect scene.

## 8. Geometry & Bounding Box Semantics

- **Geometry:** Triangle counts and mesh metrics represent **raw mesh datablocks** (base vertices/faces without evaluated modifiers), clearly documented.
- **Bounding Box:** Calculated in **world space** across visible/imported mesh geometry to derive accurate width, depth, height, and min/max coordinates.
- **Scale:** Scene unit settings are recorded when available.

## 9. Pinning Blender Version
The project will support a documented/tested Blender version. Every analysis run must record `blender_version`, `analyzer_version`, `analysis_schema_version`, and `analyzed_at`.

## 10. Symlink and Filesystem Safety
The scanner will never modify source assets, will not follow symlink loops, and gracefully handles broken symlinks, permission errors, and Unicode paths without crashing the batch.
