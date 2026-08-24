"""国交省交通量API（JARTIC WFS）から1時間値（様式2/4）を月次・BBOX指定で取得。

- 5分値レイヤは保持期間1ヶ月のため月次バッチ対象外（必要なら japan-jartic-traffic-data の蓄積を使う）
- レスポンスCSVは「外側ダブルクォート + リテラル\\r\\n」形式なのでアンエスケープする
- ジオメトリ列 MULTIPOINT ((lon lat)) は 経度/緯度 の2列に分割して保存
  （japan-jartic-traffic-data の保存形式と互換）
"""
from __future__ import annotations

import csv
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import requests

from config import Config, ensure_dir

MULTIPOINT_RE = re.compile(r"MULTIPOINT\s*\(\(\s*([0-9.]+)\s+([0-9.]+)\s*\)\)")


def _unescape_payload(raw: bytes) -> str:
    text = raw.decode("utf-8").strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return text.replace("\\r\\n", "\n").replace("\r\n", "\n")


def _split_geometry(csv_text: str) -> str:
    """ジオメトリ列を除去し 経度・緯度 列を追加したCSVテキストを返す。"""
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return ""
    header = rows[0]
    if "ジオメトリ" not in header:
        return csv_text
    gi = header.index("ジオメトリ")
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow([c for i, c in enumerate(header) if i != gi] + ["経度", "緯度"])
    for row in rows[1:]:
        if len(row) <= gi:
            continue
        m = MULTIPOINT_RE.search(row[gi])
        lon, lat = (m.group(1), m.group(2)) if m else ("", "")
        w.writerow([c for i, c in enumerate(row) if i != gi] + [lon, lat])
    return out.getvalue()


def _fetch_one(cfg: Config, layer: str, day: date, bbox: list[float], out_path: Path) -> str:
    if out_path.exists():
        return f"skip {out_path.name}"
    api = cfg.pipeline["api"]
    t_from = day.strftime("%Y%m%d") + "0000"
    t_to = day.strftime("%Y%m%d") + "2300"
    cql = (
        f"道路種別={api['road_type']} AND 時間コード>={t_from} AND 時間コード<={t_to} "
        f"AND BBOX(ジオメトリ,{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},'EPSG:4326')"
    )
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": layer,
        "srsName": "EPSG:4326",
        "outputFormat": "csv",
        "exceptions": "application/json",
        "cql_filter": cql,
    }
    last_err: Exception | None = None
    for attempt in range(api["retries"]):
        try:
            r = requests.get(api["endpoint"], params=params, timeout=300)
            r.raise_for_status()
            text = _split_geometry(_unescape_payload(r.content))
            tmp = out_path.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8", newline="")
            tmp.replace(out_path)
            n = max(text.count("\n") - 1, 0)
            return f"ok   {out_path.name} rows={n}"
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(api["retry_delay_sec"])
    raise RuntimeError(f"failed after retries: {layer} {day}: {last_err}")


def fetch_mlit(cfg: Config, region: str, yyyymm: str) -> None:
    reg = cfg.region(region)
    bbox = reg["mlit_bbox"]
    out_dir = ensure_dir(cfg.mlit_api_dir(yyyymm))
    year, month = int(yyyymm[:4]), int(yyyymm[4:])
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    days = [first + timedelta(days=i) for i in range((nxt - first).days)]

    layers = cfg.pipeline["api"]["layers_1h"]
    tasks = []
    for kind, layer in layers.items():  # tracan / cctv
        for day in days:
            out = out_dir / f"{kind}_1h_{day.strftime('%Y%m%d')}.csv"
            tasks.append((layer, day, out))

    print(f"[fetch-mlit] {len(tasks)} requests (bbox={bbox})")
    with ThreadPoolExecutor(max_workers=cfg.pipeline["api"]["max_workers"]) as ex:
        futs = [ex.submit(_fetch_one, cfg, layer, day, bbox, out) for layer, day, out in tasks]
        for f in as_completed(futs):
            print("[fetch-mlit]", f.result())
