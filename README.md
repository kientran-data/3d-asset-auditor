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

# With custom output paths
python -m asset_auditor scan "/path/to/models" \
  --db reports/catalog.db \
  --csv reports/inventory.csv \
  --json reports/inventory.json \
  --verbose
```

## CLI Usage

```
usage: asset_auditor [-h] {scan} ...

3D Asset Auditor — Local inventory scanner for 3D asset libraries.

positional arguments:
  {scan}      Available commands
    scan      Scan a directory for 3D assets

options:
  -h, --help  show this help message and exit
```

### `scan` command

```
usage: asset_auditor scan [-h] [--db DB] [--csv CSV] [--json JSON] [--verbose] path

positional arguments:
  path          Path to the 3D asset library

options:
  --db DB       Path to SQLite database (default: reports/catalog.db)
  --csv CSV     Path to output CSV (default: reports/inventory.csv)
  --json JSON   Path to output JSON (default: reports/inventory.json)
  --verbose     Enable verbose/debug logging
```

## Supported Formats

| Extension | Status | Deep Analysis |
|-----------|--------|---------------|
| `.blend`  | MVP_SUPPORTED | Phase 2A |
| `.fbx`    | MVP_SUPPORTED | Phase 2B |
| `.obj`    | MVP_SUPPORTED | Phase 2B |
| `.glb`    | MVP_SUPPORTED | Phase 2B |
| `.gltf`   | MVP_SUPPORTED | Phase 2B |
| `.stl`    | MVP_SUPPORTED | Phase 2B |
| `.ply`    | SUPPORTED_LATER | Future |
| `.dae`    | SUPPORTED_LATER | Future |
| `.3ds`    | SUPPORTED_LATER | Future |
| `.max`    | UNSUPPORTED_FORMAT | N/A |
| `.c4d`    | UNSUPPORTED_FORMAT | N/A |

All recognized formats appear in inventory regardless of deep-analysis support.

## Running Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

## Documentation
- [Project Context](PROJECT_CONTEXT.md)
- [Architecture](ARCHITECTURE.md)
- [Implementation Plan](IMPLEMENTATION_PLAN.md)
