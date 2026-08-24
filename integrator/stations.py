"""統合観測点マスタの生成。TMT座標CSV（購入データ）があれば警察地点に座標を結合する。"""
from __future__ import annotations

from pathlib import Path

import duckdb

from .config import Config, ensure_dir


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def build_stations(cfg: Config, regions: list[str], yyyymm: str) -> None:
    out_dir = ensure_dir(cfg.output_dir(yyyymm))
    out_path = out_dir / "stations.parquet"

    police_files = [
        cfg.police_dir(r, yyyymm) / "stations_police.parquet" for r in regions
    ]
    police_files = [p for p in police_files if p.exists()]
    mlit_path = cfg.mlit_api_dir(yyyymm) / "stations_mlit.parquet"

    con = duckdb.connect()
    parts = []
    for p in police_files:
        parts.append(f"""
        SELECT station_uid, source, name, pref_code, direction_hint,
               CAST(NULL AS VARCHAR) AS road_class, CAST(NULL AS VARCHAR) AS observer_type,
               drm_mesh, drm_link_kind, drm_link_no, drm_dist_from_end, drm_version,
               lon, lat, location_source
        FROM '{_q(p)}'""")
    if mlit_path.exists():
        parts.append(f"""
        SELECT station_uid, source, CAST(NULL AS VARCHAR) AS name, pref_code,
               CAST(NULL AS VARCHAR) AS direction_hint,
               road_class, observer_type,
               NULL AS drm_mesh, NULL AS drm_link_kind, NULL AS drm_link_no,
               NULL AS drm_dist_from_end, NULL AS drm_version,
               lon, lat, location_source
        FROM '{_q(mlit_path)}'""")
    if not parts:
        raise RuntimeError("no station inputs found — run parse-police / ingest-mlit first")

    con.execute(f"CREATE TABLE stations AS {' UNION ALL '.join(parts)}")

    # TMT詳細版CSV（data/private/tmt/*.csv）があれば警察地点へ座標を結合する。
    # 実データ入手後にカラム名を確認して調整すること（想定: 情報源コード, 計測地点番号, 緯度, 経度）。
    tmt_files = sorted(cfg.tmt_dir().glob("*.csv")) if cfg.tmt_dir().exists() else []
    if tmt_files:
        file_list = "[" + ", ".join("'" + _q(p) + "'" for p in tmt_files) + "]"
        con.execute(
            f"""CREATE TABLE tmt AS
            SELECT * FROM read_csv({file_list}, header=true, all_varchar=true, union_by_name=true)"""
        )
        cols = {r[0] for r in con.execute("DESCRIBE tmt").fetchall()}
        need = {"情報源コード", "計測地点番号", "緯度", "経度"}
        if need <= cols:
            con.execute(
                """
                UPDATE stations SET
                    lon = TRY_CAST(t."経度" AS DOUBLE),
                    lat = TRY_CAST(t."緯度" AS DOUBLE),
                    location_source = 'tmt_csv'
                FROM tmt t
                WHERE stations.source = 'police'
                  AND stations.station_uid = 'police:' || t."情報源コード" || ':' || t."計測地点番号"
                """
            )
            print("[stations] joined TMT coordinates")
        else:
            print(f"[stations] TMT csv found but columns differ: {sorted(cols)} — 手動でマッピング調整が必要")
    else:
        print("[stations] no TMT csv (data/private/tmt/) — police stations remain without coordinates")

    con.execute(
        f"COPY stations TO '{_q(out_path)}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    for row in con.execute(
        """SELECT source, count(*), count(lon) FROM stations GROUP BY source ORDER BY source"""
    ).fetchall():
        print(f"[stations] {row[0]}: {row[1]:,} stations ({row[2]:,} with coords)")
    con.close()
