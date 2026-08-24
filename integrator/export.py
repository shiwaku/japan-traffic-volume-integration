"""エクスポート: 観測点GeoJSON（座標を持つ地点のみ）。

PMTiles出力は tippecanoe 導入後に追加する（現状未インストール）。
counts/unified の Parquet は unify ステップで出力済み。
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .config import Config


def export(cfg: Config, yyyymm: str) -> None:
    out_dir = cfg.output_dir(yyyymm)
    stations = out_dir / "stations.parquet"
    geojson_path = out_dir / "stations.geojson"
    if not stations.exists():
        raise RuntimeError("stations.parquet not found — run stations step first")

    con = duckdb.connect()
    rows = con.execute(
        f"""SELECT station_uid, source, name, pref_code, direction_hint, road_class,
                   observer_type, location_source, lon, lat
            FROM '{str(stations).replace("'", "''")}'
            WHERE lon IS NOT NULL AND lat IS NOT NULL"""
    ).fetchall()
    cols = [d[0] for d in con.description]
    n_total = con.execute(
        f"SELECT count(*) FROM '{str(stations).replace(chr(39), chr(39)*2)}'"
    ).fetchone()[0]
    con.close()

    features = []
    for r in rows:
        props = dict(zip(cols, r))
        lon, lat = props.pop("lon"), props.pop("lat")
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": props,
            }
        )
    with open(geojson_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False)
    print(f"[export] {geojson_path} : {len(features):,} / {n_total:,} stations with coords")
