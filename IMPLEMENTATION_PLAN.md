# Implementation Phases

## Phase 0 — Foundation and documentation
- Establish repository structure (`src/`, `tests/`, `samples/`, `reports/`).
- Initialize `pyproject.toml`, `.gitignore`.
- Finalize `ARCHITECTURE.md` and `PROJECT_CONTEXT.md`.

## Phase 1 — File inventory ✅ VALIDATED
- Implement filesystem scanner (symlink safe, resilient to permission errors).
- Design and initialize the SQLite catalog (tables: `assets`).
- Generate lightweight fingerprints (`size` + `mtime`).
- Implement basic CSV and JSON inventory exporters.

## Phase 2A — GLB / GLTF Blender analysis
- Implement isolated Blender runner subprocess with timeout handling.
- Create Blender Python script to import and inspect `.glb`/`.gltf` files.
- Capture run metrics (duration, exit codes, Blender version).
- Extract scene, geometry, material/image counts, bounding box, units.
- Store results in `analysis_runs` + `asset_geometry` tables.

**Why GLB first:** Real library scan showed 13/13 assets are `.glb`.

## Phase 2B — BLEND
- Implement Blender Python script to open and inspect `.blend` files.

## Phase 2C — FBX / OBJ / STL
- Expand Blender Python script to reset scene and import standard 3D formats.

## Phase 3 — Deep metadata
- Implement database tables for deep metadata (`asset_materials`, `asset_textures`).
- Extract materials, texture paths (original vs resolved, missing textures), UV data.
- Extract rigging, animations, cameras, lights.

## Phase 4 — Batch resilience and re-analysis
- Complete the resume and retry logic.
- Implement changed-file detection triggering re-analysis.
- Implement analyzer version invalidation.

## Phase 5 — Automatic thumbnails
- Implement headless rendering in Blender to generate preview images.
- Store results and manage `preview_status`.

## Phase 6 — Sell-readiness assessment
- Implement business logic to assess the quality and completeness of an asset.
- Manage `assessment_status`.

## Phase 7 — HTML catalog
- Generate a static HTML site for browsing the local library.

## Phase 8 — Future AI layer
- Integrate visual/category classification.
- Normalize raw folder labels into standardized brands/categories.
- Generate listings, descriptions, tags, and suggested pricing.
