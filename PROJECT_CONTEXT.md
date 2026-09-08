# Project Context

**Project Name:** 3d-asset-auditor
**Purpose:** A local-first application designed to recursively scan, audit, and catalog massive local libraries of 3D assets without modifying the source files.

## Product Goal
The tool crawls directories containing thousands of unorganized 3D models and generates a structured catalog. It identifies basic filesystem information and performs deep analysis using Blender in a headless environment to extract detailed metadata (geometry, materials, textures, animations) and generate thumbnails.

## Core Principles & Constraints
1. **Local-First & Private:** All processing happens locally. No assets are committed to Git or uploaded.
2. **Read-Only / Immutable Sources:** The scanner and analyzer must NEVER modify original source assets.
3. **Resiliency:** The system must handle thousands of files. A corrupt model must crash only its isolated worker process, not the entire batch.
4. **Resumable:** Every file has its own independent processing state and fingerprint. Interrupted scans can resume exactly where they left off.
5. **Architectural Separation:**
   - **Scanner:** infers facts about files on disk.
   - **Analyzer:** infers facts contained inside 3D assets.
   - **Classifier:** infers meaning/brand/category.
   - **Assessment:** determines commercial/sell-readiness quality.
   - **Renderer:** generates visual representations.
6. **Blender Security:** Blender subprocesses must run with auto-execution of embedded scripts disabled by default from startup.

## Real Library Findings
- **Total 3D assets:** 13
- **Total size:** 351.7 MB
- **Format distribution:** 100% `.glb`
- **Top-level directories:** AUDI (3), BMW (2), MERC (6), PORCHE (1), VW (1)
- **Conclusion:** Phase 2A revised to target GLB/GLTF first (originally planned for .blend)

## Current Phase
**Phase 2A — GLB / GLTF Blender Analysis**

**Status:** IMPLEMENTED — awaiting Blender installation for real library pilot

## Phase History
| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Architecture & documentation | ✅ DONE |
| Phase 1 | File inventory scanner | ✅ VALIDATED |
| Phase 1.1 | Validation & hardening | ✅ VALIDATED |
| Phase 2A | GLB / GLTF Blender analysis | IMPLEMENTED |

## Next Phase
**Phase 2B — BLEND analysis** (after Phase 2A pilot approval)
