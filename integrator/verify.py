"""検証レポート生成（reports/{yyyymm}_verify.json、コミット対象）。

- ソース別の地点数・レコード数・欠測率・期間カバレッジ
- 警察×国交省の近接ペア相関は、警察側座標（TMT結合）取得後に有効になる
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import duckdb

from .config import Config, ensure_dir

JST = timezone(timedelta(hours=9))


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def verify(cfg: Config, regions: list[str], yyyymm: str) -> None:
    out_dir = cfg.output_dir(yyyymm)
    counts = out_dir / "counts.parquet"
    unified = out_dir / "counts_unified_1h.parquet"
    stations = out_dir / "stations.parquet"
    con = duckdb.connect()
    report: dict = {
        "対象年月": yyyymm,
        "対象地域": regions,
        "生成日時": datetime.now(JST).isoformat(timespec="seconds"),
    }

    report["stations"] = {
        r[0]: {"地点数": r[1], "座標あり": r[2]}
        for r in con.execute(
            f"SELECT source, count(*), count(lon) FROM '{_q(stations)}' GROUP BY source"
        ).fetchall()
    }

    report["counts"] = {
        r[0]: {
            "レコード数": r[1],
            "欠測率": r[2],
            "期間": [str(r[3]), str(r[4])],
            "地点数": r[5],
        }
        for r in con.execute(
            f"""SELECT source, count(*),
                round(100.0 * count(*) FILTER (quality <> 'ok') / count(*), 3),
                min(ts), max(ts), count(DISTINCT station_uid)
                FROM '{_q(counts)}' GROUP BY source ORDER BY source"""
        ).fetchall()
    }

    report["unified_1h"] = {
        r[0]: {
            "station_hours": r[1],
            "quality_ok率": r[2],
            "平均断面交通量_台h": r[3],
        }
        for r in con.execute(
            f"""SELECT source, count(*),
                round(100.0 * count(*) FILTER (quality = 'ok') / count(*), 2),
                round(avg(volume_1h) FILTER (quality = 'ok'), 1)
                FROM '{_q(unified)}' GROUP BY source ORDER BY source"""
        ).fetchall()
    }

    # 日別カバレッジ（取得漏れ検知）: ソース×日のレコード数が極端に少ない日を列挙
    low_days = con.execute(
        f"""WITH daily AS (
                SELECT source, CAST(ts AS DATE) AS d, count(*) AS n
                FROM '{_q(counts)}' GROUP BY source, d
            ), med AS (
                SELECT source, median(n) AS m FROM daily GROUP BY source
            )
            SELECT daily.source, d, n, m FROM daily JOIN med USING (source)
            WHERE n < m * 0.5 ORDER BY source, d"""
    ).fetchall()
    report["低カバレッジ日"] = [
        {"source": r[0], "date": str(r[1]), "records": r[2], "median": r[3]} for r in low_days
    ]

    # 近接ペア相関（警察側に座標がある場合のみ）
    n_police_coords = con.execute(
        f"SELECT count(*) FROM '{_q(stations)}' WHERE source='police' AND lon IS NOT NULL"
    ).fetchone()[0]
    if n_police_coords == 0:
        report["近接ペア相関"] = "警察地点に座標なし（TMT詳細版の結合後に有効化）"
    else:
        pairs = con.execute(
            f"""
            WITH p AS (SELECT * FROM '{_q(stations)}' WHERE source='police' AND lon IS NOT NULL),
                 m AS (SELECT * FROM '{_q(stations)}' WHERE source='mlit'),
                 pair AS (
                    SELECT p.station_uid AS police_uid, m.station_uid AS mlit_uid,
                           2 * 6371000 * asin(sqrt(
                               sin(radians(m.lat - p.lat) / 2) ^ 2 +
                               cos(radians(p.lat)) * cos(radians(m.lat)) *
                               sin(radians(m.lon - p.lon) / 2) ^ 2)) AS dist_m
                    FROM p, m
                    WHERE abs(p.lat - m.lat) < 0.002 AND abs(p.lon - m.lon) < 0.003
                 )
            SELECT pair.police_uid, pair.mlit_uid, round(dist_m, 1) AS dist_m,
                   corr(a.volume_1h, b.volume_1h) AS r,
                   count(*) AS n_hours
            FROM pair
            JOIN '{_q(unified)}' a ON a.station_uid = pair.police_uid AND a.quality = 'ok'
            JOIN '{_q(unified)}' b ON b.station_uid = pair.mlit_uid
                 AND b.ts_hour = a.ts_hour AND b.quality = 'ok'
            WHERE dist_m <= 150
            GROUP BY ALL HAVING count(*) >= 24
            ORDER BY dist_m
            """
        ).fetchall()
        report["近接ペア相関"] = [
            {"police": r[0], "mlit": r[1], "dist_m": r[2],
             "corr": round(r[3], 3) if r[3] is not None else None, "n_hours": r[4]}
            for r in pairs
        ]

    con.close()
    ensure_dir(cfg.reports_dir)
    out = cfg.reports_dir / f"{yyyymm}_verify.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[verify] wrote {out}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str)[:2000])
