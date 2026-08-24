"""取得済みの国交省1時間値CSV → counts / stations parquet 変換。

様式2（常設トラカン）と様式4（CCTVトラカン）でカラム名が異なるため
（例: 上り・小型交通量 vs 上り・小型交通量（集計値））、ヘッダを実際に読んで
方向×車種のカラムを動的に解決する。
"""
from __future__ import annotations

import csv
from pathlib import Path

import duckdb

from config import Config

DIRS = {"上り": "up", "下り": "down"}


def _read_header(path: Path) -> list[str]:
    with open(path, encoding="utf-8", newline="") as f:
        return next(csv.reader(f))


def _class_columns(header: list[str], jp_dir: str) -> dict[str, str]:
    """方向 jp_dir の 車種→カラム名 を解決する。総量（自動車交通量）は除外。"""
    out: dict[str, str] = {}
    for col in header:
        if not col.startswith(jp_dir + "・"):
            continue
        if "交通量" not in col:
            continue
        if "自動車交通量" in col:
            continue  # 集計値の総量列。車種別と二重計上になるため使わない
        if "判別不能" in col:
            out["unknown"] = col
        elif "小型交通量" in col:
            out["small"] = col
        elif "大型交通量" in col:
            out["large"] = col
    return out


def _quality_expr(header: list[str], jp_dir: str, kind: str, vol_col: str) -> str:
    q = f"""CASE
        WHEN TRY_CAST("{vol_col}" AS INTEGER) IS NULL THEN 'missing'"""
    if kind == "tracan":
        checks = {
            "missing": f"{jp_dir}・欠測",
            "power_outage": f"{jp_dir}・停電",
            "sensor_ng": f"{jp_dir}・ループ異常",
            "sensor_ng2": f"{jp_dir}・超音波異常",
        }
        for label, col in checks.items():
            if col in header:
                q += f"""
        WHEN "{col}" = '1' THEN '{label.rstrip('2')}'"""
    else:  # cctv
        # 実レスポンスの品質列は方向別「5分欠測処理フラグ」（仕様書のカメラ品質フラグ群とは異なる）
        flag = f"{jp_dir}・5分欠測処理フラグ"
        if flag in header:
            q += f"""
        WHEN "{flag}" = '1' THEN 'partial_5m'"""
        if "カメラプリセット位置" in header:
            q += """
        WHEN "カメラプリセット位置" = '1' THEN 'camera_ng'"""
    q += """
        ELSE 'ok' END"""
    return q


def ingest_mlit(cfg: Config, yyyymm: str) -> None:
    d = cfg.mlit_api_dir(yyyymm)
    counts_path = d / "counts_mlit.parquet"
    stations_path = d / "stations_mlit.parquet"
    if counts_path.exists() and stations_path.exists():
        print(f"[ingest-mlit] skip (exists): {counts_path}")
        return

    con = duckdb.connect()
    con.execute("SET threads TO 8")
    union_parts: list[str] = []
    station_parts: list[str] = []

    for kind, source in (("tracan", "mlit_tracan"), ("cctv", "mlit_cctv")):
        files = sorted(p for p in d.glob(f"{kind}_1h_*.csv") if p.stat().st_size > 10)
        if not files:
            print(f"[ingest-mlit] no files for {kind}")
            continue
        header = _read_header(files[0])
        file_list = "[" + ", ".join("'" + str(p).replace("'", "''") + "'" for p in files) + "]"
        rel = f"read_csv({file_list}, header=true, all_varchar=true, nullstr='', union_by_name=true)"

        for jp_dir, direction in DIRS.items():
            for vclass, col in _class_columns(header, jp_dir).items():
                union_parts.append(
                    f"""
        SELECT
            'mlit:' || "常時観測点コード" AS station_uid,
            strptime("時間コード", '%Y%m%d%H%M') AS ts,
            '1h' AS interval,
            '{direction}' AS direction,
            '{vclass}' AS vehicle_class,
            TRY_CAST("{col}" AS INTEGER) AS volume,
            {_quality_expr(header, jp_dir, kind, col)} AS quality,
            '{source}' AS source
        FROM {rel}"""
                )
        station_parts.append(
            f"""
        SELECT
            'mlit:' || "常時観測点コード" AS station_uid,
            'mlit' AS source,
            "常時観測点コード" AS station_no,
            "開発建設部／都道府県コード" AS pref_code,
            "道路種別" AS road_class,
            '{kind}' AS observer_type,
            TRY_CAST("経度" AS DOUBLE) AS lon,
            TRY_CAST("緯度" AS DOUBLE) AS lat,
            'mlit_api' AS location_source,
            COUNT(*) AS n_records
        FROM {rel}
        GROUP BY ALL"""
        )

    if not union_parts:
        raise RuntimeError(f"no mlit csv found in {d} — run fetch-mlit first")

    print(f"[ingest-mlit] writing counts parquet ({len(union_parts)} slices) ...")
    con.execute(
        f"""COPY ({' UNION ALL '.join(union_parts)})
        TO '{str(counts_path).replace("'", "''")}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )
    print("[ingest-mlit] writing stations parquet ...")
    con.execute(
        f"""COPY (
            SELECT * FROM ({' UNION ALL '.join(station_parts)})
            QUALIFY row_number() OVER (PARTITION BY station_uid ORDER BY n_records DESC) = 1
        ) TO '{str(stations_path).replace("'", "''")}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )
    n_counts = con.execute(f"SELECT count(*) FROM '{counts_path}'").fetchone()[0]
    n_st = con.execute(f"SELECT count(*) FROM '{stations_path}'").fetchone()[0]
    print(f"[ingest-mlit] counts={n_counts:,} stations={n_st:,}")
    con.close()
