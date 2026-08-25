"""統合観測点マスタの生成。TMT座標CSV（購入データ）があれば警察地点に座標を結合する。

TMT詳細版CSVの実形式（2026-08 提供・R07リンクバージョン）:
- 文字コード: Shift_JIS
- 1行目: メタ行（例 `交通管理リンクバージョン: R07`）→ スキップが必要
- 2行目: ヘッダ `情報源コード,計測地点番号,計測地点名,２次メッシュ番号,交通管理リンク番号,経度,緯度`
- 配置: 注文フォルダ配下にネストするため rglob で探索する

※ この座標データは有償・譲渡禁止（data/private/ 配下・.gitignore対象）。
   詳細は DESIGN.md §3.5 を参照。
"""
from __future__ import annotations

import csv
from pathlib import Path

import duckdb
import pyarrow as pa

from config import Config, ensure_dir

TMT_ENCODING = "shift_jis"
TMT_REQUIRED_COLS = ("情報源コード", "計測地点番号", "経度", "緯度")


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def _to_float(v: str) -> float | None:
    try:
        return float(v.strip())
    except (ValueError, AttributeError):
        return None


def _read_tmt_csv(path: Path) -> list[dict[str, str]]:
    """TMT座標CSVを読む。ヘッダ行を自動検出してメタ行を読み飛ばす。"""
    with open(path, encoding=TMT_ENCODING, newline="") as f:
        rows = list(csv.reader(f))
    header_idx = next(
        (i for i, r in enumerate(rows) if set(TMT_REQUIRED_COLS) <= set(r)), None
    )
    if header_idx is None:
        raise RuntimeError(
            f"TMT csv header not found in {path.name}: "
            f"必須列 {TMT_REQUIRED_COLS} が見つかりません（先頭行={rows[0] if rows else '空'}）"
        )
    header = rows[header_idx]
    return [dict(zip(header, r)) for r in rows[header_idx + 1 :] if len(r) == len(header)]


def _load_tmt_coords(cfg: Config) -> list[dict[str, str]]:
    """data/private/tmt/ 配下（サブフォルダ含む）の全CSVを読み込む。"""
    tmt_dir = cfg.tmt_dir()
    if not tmt_dir.exists():
        return []
    records: list[dict[str, str]] = []
    for path in sorted(tmt_dir.rglob("*.csv")):
        rows = _read_tmt_csv(path)
        print(f"[stations] TMT csv {path.name}: {len(rows):,} rows")
        records.extend(rows)
    return records


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

    # TMT詳細版CSV（data/private/tmt/ 配下、サブフォルダ含む）があれば警察地点へ座標を結合する。
    tmt_rows = _load_tmt_coords(cfg)
    if tmt_rows:
        con.register(
            "tmt",
            pa.table(
                {
                    "station_uid": [
                        f"police:{r['情報源コード'].strip()}:{r['計測地点番号'].strip()}"
                        for r in tmt_rows
                    ],
                    "lon": [_to_float(r["経度"]) for r in tmt_rows],
                    "lat": [_to_float(r["緯度"]) for r in tmt_rows],
                }
            ),
        )
        con.execute(
            """
            UPDATE stations SET
                lon = t.lon, lat = t.lat, location_source = 'tmt_csv'
            FROM tmt t
            WHERE stations.source = 'police'
              AND stations.station_uid = t.station_uid
              AND t.lon IS NOT NULL AND t.lat IS NOT NULL
            """
        )
        # 結合率の内訳を出す（typeB側にしか無い地点／TMT側にしか無い地点の検知）
        matched, police_total = con.execute(
            """SELECT count(lon), count(*) FROM stations WHERE source = 'police'"""
        ).fetchone()
        orphan_tmt = con.execute(
            """SELECT count(*) FROM tmt t
               WHERE NOT EXISTS (SELECT 1 FROM stations s WHERE s.station_uid = t.station_uid)"""
        ).fetchone()[0]
        rate = 100.0 * matched / police_total if police_total else 0.0
        print(
            f"[stations] TMT結合: {matched:,}/{police_total:,} 地点 ({rate:.1f}%) / "
            f"typeBに存在しないTMT地点 {orphan_tmt:,}"
        )
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
