"""typeB CSV（Shift_JIS）→ counts / stations parquet 変換。

手順:
1. ZIP内CSVをストリームでUTF-8に変換（DuckDBはSJISを直接読めないため）
2. DuckDBで counts long format と stations（地点マスタ）を生成
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import duckdb

from config import Config

CHUNK = 1 << 22  # 4MB


def _to_utf8(zip_path: Path, utf8_path: Path) -> None:
    if utf8_path.exists() and utf8_path.stat().st_size > 0:
        print(f"[parse-police] skip re-encode (exists): {utf8_path}")
        return
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
        if len(members) != 1:
            raise RuntimeError(f"expected 1 csv in zip, got {members}")
        print(f"[parse-police] re-encoding {members[0]} -> utf-8")
        tmp = utf8_path.with_suffix(".tmp")
        with zf.open(members[0]) as src, open(tmp, "w", encoding="utf-8", newline="") as dst:
            buf = b""
            while True:
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                buf += chunk
                # マルチバイト文字の途中で切らないよう、最後の改行までをデコード
                cut = buf.rfind(b"\n")
                if cut < 0:
                    continue
                dst.write(buf[: cut + 1].decode("shift_jis"))
                buf = buf[cut + 1 :]
            if buf:
                dst.write(buf.decode("shift_jis"))
        tmp.replace(utf8_path)


def parse_police(cfg: Config, region: str, yyyymm: str) -> None:
    reg = cfg.region(region)
    d = cfg.police_dir(region, yyyymm)
    zip_path = d / f"typeB_{reg['roman']}_{yyyymm[:4]}_{yyyymm[4:]}.zip"
    utf8_path = d / "raw_utf8.csv"
    counts_path = d / "counts_police.parquet"
    stations_path = d / "stations_police.parquet"

    if counts_path.exists() and stations_path.exists():
        print(f"[parse-police] skip (exists): {counts_path}")
        return

    _to_utf8(zip_path, utf8_path)

    con = duckdb.connect()
    con.execute(f"SET threads TO 8")
    src = str(utf8_path).replace("'", "''")
    con.execute(
        f"""
        CREATE VIEW raw AS
        SELECT * FROM read_csv('{src}', header=true, all_varchar=true, nullstr='')
        """
    )

    print("[parse-police] writing counts parquet ...")
    con.execute(
        f"""
        COPY (
            SELECT
                'police:' || "情報源コード" || ':' || "計測地点番号" AS station_uid,
                strptime("時刻", '%Y/%m/%d %H:%M') AS ts,
                '5m' AS interval,
                'section' AS direction,
                'all' AS vehicle_class,
                TRY_CAST("断面交通量" AS INTEGER) AS volume,
                CASE WHEN TRY_CAST("断面交通量" AS INTEGER) IS NULL
                     THEN 'missing' ELSE 'ok' END AS quality,
                'police' AS source
            FROM raw
        ) TO '{str(counts_path).replace("'", "''")}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )

    print("[parse-police] writing stations parquet ...")
    con.execute(
        f"""
        COPY (
            SELECT * FROM (
                SELECT
                    'police:' || "情報源コード" || ':' || "計測地点番号" AS station_uid,
                    'police' AS source,
                    "情報源コード" AS joho_gen_code,
                    "計測地点番号" AS station_no,
                    "計測地点名称" AS name,
                    '{reg["pref_code"]}' AS pref_code,
                    regexp_extract("計測地点名称", '(..)$', 1) AS direction_hint,
                    "2次メッシュコード" AS drm_mesh,
                    "リンク区分" AS drm_link_kind,
                    "リンク番号" AS drm_link_no,
                    "リンク終端からの距離（×10m）" AS drm_dist_from_end,
                    "リンクバージョン" AS drm_version,
                    CAST(NULL AS DOUBLE) AS lon,
                    CAST(NULL AS DOUBLE) AS lat,
                    'none' AS location_source,
                    COUNT(*) AS n_records,
                    MIN(strptime("時刻", '%Y/%m/%d %H:%M')) AS first_ts,
                    MAX(strptime("時刻", '%Y/%m/%d %H:%M')) AS last_ts
                FROM raw
                GROUP BY ALL
            )
            QUALIFY row_number() OVER (
                PARTITION BY station_uid ORDER BY drm_version DESC, n_records DESC
            ) = 1
        ) TO '{str(stations_path).replace("'", "''")}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    n_counts = con.execute(f"SELECT count(*) FROM '{counts_path}'").fetchone()[0]
    n_st = con.execute(f"SELECT count(*) FROM '{stations_path}'").fetchone()[0]
    print(f"[parse-police] counts={n_counts:,} stations={n_st:,}")
    con.close()

    if cfg.pipeline.get("police", {}).get("delete_utf8_temp", True):
        utf8_path.unlink(missing_ok=True)
        print("[parse-police] removed utf-8 temp csv")
