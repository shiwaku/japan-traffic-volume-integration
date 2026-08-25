"""ビューワが読むデータを生成する。

出力先は viewer/public/data/。**TMT座標（譲渡禁止）を含むためコミット・公開しない**
（.gitignore 対象）。ビューワはローカル閲覧専用。

- stations.geojson  観測点（属性はビューワが使うものだけに絞る）
- traffic_1h.json.gz 1時間値・全期間（ページロード時に一括フェッチ）
- traffic_5m/YYYYMMDD.json.gz 5分値・日別（日付切替時にフェッチ・警察のみ）
- meta.json         期間・地点数・常時ゼロ地点など、ビューワが最初に読む索引
"""
from __future__ import annotations

import gzip
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

from config import Config, REPO_ROOT, ensure_dir

VIEWER_DATA = REPO_ROOT / "viewer" / "public" / "data"

# ビューワが使う観測点の属性だけを載せる（DRM参照列などは落とす）
STATION_PROPS = (
    "station_uid, source, name, direction_hint, observer_type, location_source"
)


def _q(p: Path) -> str:
    return str(p).replace("'", "''")


def _hive(p: Path) -> str:
    return f"read_parquet('{_q(p)}/**/*.parquet', hive_partitioning=true)"


def _write_gz_json(obj: object, path: Path) -> int:
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    with gzip.open(path, "wb", compresslevel=6) as f:
        f.write(raw)
    return path.stat().st_size


def export_viewer(cfg: Config, yyyymm: str) -> None:
    out_dir = cfg.output_dir(yyyymm)
    stations_path = out_dir / "stations_all_restricted.parquet"
    unified = out_dir / "counts_unified_1h"
    counts = out_dir / "counts"
    if not stations_path.exists():
        raise RuntimeError("run stations step first")

    dst = ensure_dir(VIEWER_DATA)
    con = duckdb.connect()
    con.execute("SET threads TO 8")

    # ---- 観測点 GeoJSON ----
    rows = con.execute(
        f"""SELECT {STATION_PROPS}, lon, lat FROM '{_q(stations_path)}'
            WHERE lon IS NOT NULL AND lat IS NOT NULL
            ORDER BY station_uid"""
    ).fetchall()
    cols = [d[0] for d in con.description]
    features = []
    for r in rows:
        props = dict(zip(cols, r))
        lon, lat = props.pop("lon"), props.pop("lat")
        # 座標は6桁（約10cm）に丸めて軽くする
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                "properties": {k: v for k, v in props.items() if v is not None},
            }
        )
    gj = dst / "stations.geojson"
    gj.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False,
                   separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"[export-viewer] stations.geojson : {len(features):,} 地点 / {gj.stat().st_size/1024:.0f} KB")

    # ---- 1時間値・全期間 ----
    # {時刻コード: {station_uid: 交通量}}。欠測・partial は載せない（地図で灰色にする）
    rows = con.execute(
        f"""SELECT strftime(ts_hour, '%Y%m%d%H%M'), station_uid, CAST(volume_1h AS INTEGER)
            FROM {_hive(unified)} WHERE quality = 'ok' AND volume_1h IS NOT NULL
            ORDER BY ts_hour"""
    ).fetchall()
    by_time: dict[str, dict[str, int]] = {}
    for t, uid, v in rows:
        by_time.setdefault(t, {})[uid] = v
    size = _write_gz_json(by_time, dst / "traffic_1h.json.gz")
    print(
        f"[export-viewer] traffic_1h.json.gz : {len(by_time)} ステップ / "
        f"{len(rows):,} 値 / {size/1024/1024:.1f} MB"
    )
    hours = sorted(by_time.keys())

    # ---- 5分値・日別（警察のみ。国交省の5分値は保持期間の都合で未取得） ----
    days_written: list[str] = []
    dst_5m = ensure_dir(dst / "traffic_5m")
    year, month = int(yyyymm[:4]), int(yyyymm[4:])
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    for i in range((nxt - first).days):
        day = first + timedelta(days=i)
        ymd = day.strftime("%Y%m%d")
        rows = con.execute(
            f"""SELECT strftime(ts, '%Y%m%d%H%M'), station_uid, CAST(volume AS INTEGER)
                FROM {_hive(counts)}
                WHERE source = 'police' AND volume IS NOT NULL
                  AND CAST(ts AS DATE) = DATE '{day.isoformat()}'
                ORDER BY ts"""
        ).fetchall()
        if not rows:
            continue
        d: dict[str, dict[str, int]] = {}
        for t, uid, v in rows:
            d.setdefault(t, {})[uid] = v
        _write_gz_json(d, dst_5m / f"{ymd}.json.gz")
        days_written.append(ymd)
    total_5m = sum((dst_5m / f"{d}.json.gz").stat().st_size for d in days_written)
    print(
        f"[export-viewer] traffic_5m/       : {len(days_written)} 日 / "
        f"計 {total_5m/1024/1024:.1f} MB"
    )

    # ---- メタ情報（ビューワが最初に読む） ----
    src_stats = {
        r[0]: {"stations": r[1]}
        for r in con.execute(
            f"""SELECT source, count(*) FROM '{_q(stations_path)}'
                GROUP BY source ORDER BY source"""
        ).fetchall()
    }
    # 統合1時間値のソース名（police / mlit_tracan / mlit_cctv）ごとの地点数
    unified_sources = {
        r[0]: r[1]
        for r in con.execute(
            f"""SELECT source, count(DISTINCT station_uid) FROM {_hive(unified)}
                GROUP BY source ORDER BY source"""
        ).fetchall()
    }
    zero_uids = [
        r[0]
        for r in con.execute(
            f"""SELECT station_uid FROM {_hive(unified)} WHERE quality = 'ok'
                GROUP BY station_uid HAVING max(volume_1h) = 0"""
        ).fetchall()
    ]
    # 色スケールの上限は上位1%点（外れ値で潰れないように）。
    # 1時間値と5分値で桁が違うため、モードごとに別の上限を持たせる
    # （共通にすると5分モードで全点が低い側に張り付いて変化が見えない）。
    p99 = con.execute(
        f"""SELECT quantile_cont(volume_1h, 0.99) FROM {_hive(unified)} WHERE quality='ok'"""
    ).fetchone()[0]
    p99_5m = con.execute(
        f"""SELECT quantile_cont(volume, 0.99) FROM {_hive(counts)}
            WHERE source = 'police' AND volume IS NOT NULL"""
    ).fetchone()[0]

    meta = {
        "target_month": yyyymm,
        "target_month_label": f"{yyyymm[:4]}年{int(yyyymm[4:])}月",
        "hours": hours,
        "days_5m": days_written,
        "stations_by_source": src_stats,
        "unified_stations_by_source": unified_sources,
        "zero_stations": zero_uids,
        "scale_max_1h": int(p99) if p99 else 1000,
        "scale_max_5m": int(p99_5m) if p99_5m else 100,
        "attribution": [
            "「断面交通量情報」（公益財団法人日本道路交通情報センター）を加工して作成",
            "国土交通省API機能による交通量(参考値)を加工して作成",
            "計測地点位置情報：（公財）日本交通管理技術協会",
        ],
    }
    (dst / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(
        f"[export-viewer] meta.json         : {len(hours)} 時刻ステップ / "
        f"常時ゼロ {len(zero_uids)} 地点 / 色スケール上限 "
        f"{meta['scale_max_1h']} 台/h・{meta['scale_max_5m']} 台/5分"
    )
    con.close()
    print(f"[export-viewer] → {dst}（.gitignore対象・公開しないこと）")
