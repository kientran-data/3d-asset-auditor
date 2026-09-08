import csv
from typing import Iterable
from ..models import AssetRecord
import dataclasses

def export_to_csv(assets: Iterable[AssetRecord], output_path: str):
    fields = [f.name for f in dataclasses.fields(AssetRecord)]
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for asset in assets:
            writer.writerow(dataclasses.asdict(asset))
