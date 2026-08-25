"""エクスポート: 観測点をライセンスの出所別に分割して出力する。

DESIGN.md §3.5(c) 軸2 のとおり、TMT由来の座標（譲渡禁止）と国交省API由来の座標
（CC BY互換）を同一ファイルに混ぜない。混ぜると、本来公開できる国交省地点まで
TMTの制約に巻き込まれるため。

- stations_open.{parquet,geojson} : location_source='mlit_api' のみ → 公開可
- stations_restricted.parquet     : TMT座標を含む全地点 → 公開不可（要事前承認）

PMTiles出力は tippecanoe 導入後に追加する（現状未インストール）。
counts/unified の Parquet は unify ステップで出力済み。
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from config import Config

# 再配布可能な座標の出所。ここに無い出所は restricted 扱いにする（fail-safe）。
OPEN_LOCATION_SOURCES = ("mlit_api",)

PROPS = (
    "station_uid, source, name, pref_code, direction_hint, road_class, "
    "observer_type, location_source"
)


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def _write_geojson(con: duckdb.DuckDBPyConnection, sql: str, path: Path) -> int:
    rows = con.execute(sql).fetchall()
    cols = [d[0] for d in con.description]
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
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False)
    return len(features)


def export(cfg: Config, yyyymm: str) -> None:
    out_dir = cfg.output_dir(yyyymm)
    stations = out_dir / "stations_all_restricted.parquet"
    if not stations.exists():
        raise RuntimeError(
            "stations_all_restricted.parquet not found — run stations step first"
        )

    src = _q(stations)
    open_list = ", ".join(f"'{s}'" for s in OPEN_LOCATION_SOURCES)
    con = duckdb.connect()

    # --- 公開可: 国交省API由来の座標のみ ---
    n_open = _write_geojson(
        con,
        f"""SELECT {PROPS}, lon, lat FROM '{src}'
            WHERE lon IS NOT NULL AND lat IS NOT NULL
              AND location_source IN ({open_list})""",
        out_dir / "stations_open.geojson",
    )
    con.execute(
        f"""COPY (SELECT * FROM '{src}' WHERE location_source IN ({open_list}))
            TO '{_q(out_dir / "stations_open.parquet")}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )

    # 全地点マスタ（stations_all_restricted.parquet）は stations ステップが出力済み。
    # ここで複製すると同内容のファイルが2つでき、どちらが正本か分からなくなるため作らない。
    n_all, n_tmt = con.execute(
        f"""SELECT count(*),
                   count(*) FILTER (lon IS NOT NULL
                                    AND location_source NOT IN ({open_list}))
            FROM '{src}'"""
    ).fetchone()

    # 旧世代の紛らわしいファイルが残っていると誤って公開しかねないので削除する
    for name in ("stations.geojson", "stations.parquet", "stations_restricted.parquet"):
        legacy = out_dir / name
        if legacy.exists():
            legacy.unlink()
            print(f"[export] removed legacy file: {name}")

    print(f"[export] stations_open.{{parquet,geojson}}   : {n_open:,} 地点（公開可・出典表記のうえ）")
    print(
        f"[export] stations_all_restricted.parquet   : "
        f"{n_all:,} 地点（うち{n_tmt:,}がTMT座標・公開不可）"
    )
    con.close()
