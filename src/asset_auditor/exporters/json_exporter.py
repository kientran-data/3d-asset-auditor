import json
from typing import Iterable, Dict, Any
from ..models import AssetRecord
import dataclasses
from datetime import datetime, UTC

def export_to_json(assets: Iterable[AssetRecord], source_root: str, stats: Dict[str, Any], output_path: str):
    data = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_root": source_root,
        "summary": stats,
        "assets": [dataclasses.asdict(a) for a in assets]
    }
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
