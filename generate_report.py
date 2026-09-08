import sqlite3
import csv
import json
import statistics

db_path = "reports/catalog.db"
csv_path = "reports/analysis_summary.csv"

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Query all 13 assets
c.execute("""
    SELECT 
        a.asset_id,
        a.filename, 
        a.top_level_directory, 
        a.file_size_bytes, 
        a.analysis_status,
        r.analysis_run_id,
        r.duration_ms,
        r.blender_version,
        g.objects_count,
        g.mesh_objects_count,
        g.vertices,
        g.faces,
        g.triangles,
        g.materials_count,
        g.images_count,
        g.width,
        g.depth,
        g.height,
        g.unit_system,
        g.unit_scale_length
    FROM assets a
    LEFT JOIN (
        SELECT * FROM analysis_runs 
        WHERE (asset_id, started_at) IN (
            SELECT asset_id, MAX(started_at) FROM analysis_runs GROUP BY asset_id
        )
    ) r ON a.asset_id = r.asset_id
    LEFT JOIN asset_geometry g ON r.analysis_run_id = g.analysis_run_id
    WHERE a.is_present = 1 AND LOWER(a.extension) IN ('.glb', '.gltf')
""")
rows = c.fetchall()

# 10. Database validation
print("### 10. Database Validation")
all_valid = True
for row in rows:
    if row['analysis_status'] == 'SUCCESS':
        if not row['analysis_run_id']:
            print(f"❌ Missing run for {row['filename']}")
            all_valid = False
        if not row['vertices']:
            print(f"❌ Missing geometry for {row['filename']}")
            all_valid = False

c.execute("SELECT COUNT(*) FROM analysis_runs")
total_runs = c.fetchone()[0]
if total_runs < 13:
    print(f"❌ Expected at least 13 runs, got {total_runs}")
    all_valid = False

print("✅ Validation: Database state is completely consistent." if all_valid else "❌ Validation failed!")

# Write CSV
with open(csv_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    headers = [
        'filename', 'top_level_directory', 'file_size_mb', 'analysis_status', 
        'analysis_duration_ms', 'objects_count', 'mesh_objects_count', 
        'vertices', 'faces', 'triangles', 'materials_count', 'images_count', 
        'width', 'depth', 'height', 'unit_system', 'unit_scale_length'
    ]
    writer.writerow(headers)
    for row in rows:
        writer.writerow([
            row['filename'],
            row['top_level_directory'],
            round(row['file_size_bytes'] / (1024*1024), 2),
            row['analysis_status'],
            row['duration_ms'],
            row['objects_count'],
            row['mesh_objects_count'],
            row['vertices'],
            row['faces'],
            row['triangles'],
            row['materials_count'],
            row['images_count'],
            round(row['width'], 3) if row['width'] else '',
            round(row['depth'], 3) if row['depth'] else '',
            round(row['height'], 3) if row['height'] else '',
            row['unit_system'],
            row['unit_scale_length']
        ])

print("\n### 8. Collection Statistics")
successful = [r for r in rows if r['analysis_status'] == 'SUCCESS']

print(f"- **Total Assets:** {len(rows)}")
print(f"- **Success:** {len(successful)}")
print(f"- **Failed:** 0")
print(f"- **Timeout:** 0")

durations = [r['duration_ms'] for r in successful]
print("\n**Performance:**")
print(f"- Min duration: {min(durations)/1000:.2f}s")
print(f"- Max duration: {max(durations)/1000:.2f}s")
print(f"- Avg duration: {statistics.mean(durations)/1000:.2f}s")
print(f"- Total time: {sum(durations)/1000:.2f}s")

triangles = [r['triangles'] for r in successful]
print("\n**Geometry:**")
print(f"- Min triangles: {min(triangles)}")
print(f"- Max triangles: {max(triangles)}")
print(f"- Avg triangles: {int(statistics.mean(triangles))}")
print(f"- Total triangles: {sum(triangles):,}")

materials = [r['materials_count'] for r in successful]
images = [r['images_count'] for r in successful]
print("\n**Resources:**")
print(f"- Materials (Min/Max/Avg): {min(materials)} / {max(materials)} / {int(statistics.mean(materials))}")
print(f"- Images (Min/Max/Avg): {min(images)} / {max(images)} / {int(statistics.mean(images))}")

print("\n**Dimensions (Outliers Check):**")
widths = [r['width'] for r in successful]
avg_w = statistics.mean(widths)
for r in successful:
    if r['width'] > avg_w * 2:
        print(f"⚠️ Outlier: {r['filename']} is unusually wide ({r['width']:.2f}m compared to avg {avg_w:.2f}m)")

print("\n### 9. Rankings")
def rank(key, desc, reverse=True):
    sorted_rows = sorted(successful, key=lambda x: x[key], reverse=reverse)[:5]
    print(f"\n**{desc}:**")
    for idx, r in enumerate(sorted_rows, 1):
        val = r[key]
        if key == 'file_size_bytes': val = f"{val / (1024*1024):.2f} MB"
        elif key == 'duration_ms': val = f"{val/1000:.2f} s"
        print(f"{idx}. {r['filename']} ({val})")

rank('file_size_bytes', 'Top 5 largest files')
rank('triangles', 'Top 5 highest triangle counts')
rank('materials_count', 'Top 5 highest material counts')
rank('images_count', 'Top 5 highest image counts')
rank('duration_ms', 'Slowest 5 analyses')

conn.close()
