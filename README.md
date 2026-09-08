# 3D Asset Auditor

A local-first application designed to recursively scan, audit, and catalog massive local libraries of 3D assets without modifying the source files.

## Quick Start

```bash
# Install in development mode
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Scan a directory
python -m asset_auditor scan "/path/to/your/3d-models"

# Analyze pending GLB/GLTF assets (requires Blender)
python -m asset_auditor analyze "/path/to/your/3d-models"

# Analyze a single asset by UUID
python -m asset_auditor analyze --asset-id <uuid>

# Retry failed analyses
python -m asset_auditor analyze --retry-failed
```

## Prerequisites

- Python ≥ 3.10
- Blender (for Phase 2+ analysis) — set `BLENDER_EXECUTABLE` if not in PATH

## CLI Commands

### `scan` — Inventory scan (no Blender required)

```bash
python -m asset_auditor scan "/path/to/models" \
  --db reports/catalog.db \
  --csv reports/inventory.csv \
  --json reports/inventory.json \
  --verbose
```

### `analyze` — Blender headless analysis

```bash
python -m asset_auditor analyze "/path/to/models" \
  --db reports/catalog.db \
  --asset-id <uuid>        # optional: single asset
  --retry-failed           # optional: include previously failed
  --timeout 120            # optional: per-asset timeout (seconds)
  --verbose
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BLENDER_EXECUTABLE` | `blender` | Path to Blender binary |
| `ANALYSIS_TIMEOUT` | `120` | Per-asset timeout in seconds |

## Supported Formats

| Extension | Scan Status | Analysis Phase |
|-----------|-------------|----------------|
| `.glb`    | MVP_SUPPORTED | Phase 2A ← current |
| `.gltf`   | MVP_SUPPORTED | Phase 2A ← current |
| `.blend`  | MVP_SUPPORTED | Phase 2B |
| `.fbx`    | MVP_SUPPORTED | Phase 2C |
| `.obj`    | MVP_SUPPORTED | Phase 2C |
| `.stl`    | MVP_SUPPORTED | Phase 2C |
| `.ply`    | SUPPORTED_LATER | Future |
| `.dae`    | SUPPORTED_LATER | Future |
| `.3ds`    | SUPPORTED_LATER | Future |
| `.max`    | UNSUPPORTED_FORMAT | N/A |
| `.c4d`    | UNSUPPORTED_FORMAT | N/A |

## Running Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

## Documentation
- [Project Context](PROJECT_CONTEXT.md)
- [Architecture](ARCHITECTURE.md)
- [Implementation Plan](IMPLEMENTATION_PLAN.md)
