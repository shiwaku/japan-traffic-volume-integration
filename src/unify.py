"""counts の統合と、断面1時間合計への正規化（counts_unified_1h）。

- 警察5分値: 12スロットを1時間に集計（欠測スロットがあれば quality を落とす）
- 国交省1時間値: 方向×車種を断面合計に合算
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from config import Config, ensure_dir


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def _hive(p: Path) -> str:
    """source= でパーティション分割されたディレクトリを横断して読む。"""
    return f"read_parquet('{_q(p)}/**/*.parquet', hive_partitioning=true)"


def unify(cfg: Config, regions: list[str], yyyymm: str) -> None:
    out_dir = ensure_dir(cfg.output_dir(yyyymm))
    counts_out = out_dir / "counts"
    unified_out = out_dir / "counts_unified_1h"

    police_files = [
        p for r in regions
        if (p := cfg.police_dir(r, yyyymm) / "counts_police.parquet").exists()
    ]
    mlit_path = cfg.mlit_api_dir(yyyymm) / "counts_mlit.parquet"

    srcs = [f"SELECT * FROM '{_q(p)}'" for p in police_files]
    if mlit_path.exists():
        srcs.append(f"SELECT * FROM '{_q(mlit_path)}'")
    if not srcs:
        raise RuntimeError("no counts inputs found")

    con = duckdb.connect()
    con.execute("SET threads TO 8")
    # source= の Hive パーティションで物理分割する（DESIGN.md §3.5(c) 軸1）。
    # 警察と国交省は別系統の機器であり、同一列に並べたままだと誤って合算されうる。
    # 横断クエリは read_parquet('counts/**/*.parquet', hive_partitioning=true) で可能。
    print("[unify] writing counts/ (partitioned by source) ...")
    con.execute(
        f"""COPY ({' UNION ALL '.join(srcs)})
        TO '{_q(counts_out)}'
        (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (source), OVERWRITE_OR_IGNORE)"""
    )

    print("[unify] writing counts_unified_1h/ (partitioned by source) ...")
    con.execute(
        f"""
        COPY (
            -- 警察: 5分値×12 → 1時間断面合計
            SELECT
                station_uid,
                date_trunc('hour', ts) AS ts_hour,
                SUM(volume) AS volume_1h,
                COUNT(volume) AS n_obs,
                CASE WHEN COUNT(volume) = 12 THEN 'ok'
                     WHEN COUNT(volume) = 0 THEN 'missing'
                     ELSE 'partial' END AS quality,
                'police' AS source
            FROM {_hive(counts_out)}
            WHERE source = 'police'
            GROUP BY station_uid, date_trunc('hour', ts)

            UNION ALL

            -- 国交省: 方向×車種（最大6系列）→ 断面合計
            SELECT
                station_uid,
                ts AS ts_hour,
                SUM(volume) AS volume_1h,
                COUNT(volume) AS n_obs,
                CASE WHEN COUNT(*) = COUNT(volume) THEN 'ok'
                     WHEN COUNT(volume) = 0 THEN 'missing'
                     ELSE 'partial' END AS quality,
                ANY_VALUE(source) AS source
            FROM {_hive(counts_out)}
            WHERE source LIKE 'mlit%'
            GROUP BY station_uid, ts
        ) TO '{_q(unified_out)}'
        (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (source), OVERWRITE_OR_IGNORE)
        """
    )
    for row in con.execute(
        f"""SELECT source, count(*), round(avg(volume_1h), 1)
        FROM {_hive(unified_out)} GROUP BY source ORDER BY source"""
    ).fetchall():
        print(f"[unify] {row[0]}: {row[1]:,} station-hours, mean volume {row[2]}")
    con.close()
