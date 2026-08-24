"""typeB（警察断面交通量）月次ZIPの取得。既存ファイルはスキップ（レジューム対応）。"""
from __future__ import annotations

from pathlib import Path

import requests

from .catalog import resolve_typeb_url
from .config import Config, ensure_dir


def fetch_police(cfg: Config, region: str, yyyymm: str) -> Path:
    reg = cfg.region(region)
    out_dir = ensure_dir(cfg.police_dir(region, yyyymm))
    zip_path = out_dir / f"typeB_{reg['roman']}_{yyyymm[:4]}_{yyyymm[4:]}.zip"
    if zip_path.exists() and zip_path.stat().st_size > 0:
        print(f"[fetch-police] skip (exists): {zip_path}")
        return zip_path

    url = resolve_typeb_url(cfg, reg["roman"], yyyymm)
    if url is None:
        raise RuntimeError(
            f"typeB link not found in catalog: region={region} month={yyyymm} "
            "(公開ラグは約2ヶ月。カタログに載っている月か確認)"
        )
    print(f"[fetch-police] GET {url}")
    tmp = zip_path.with_suffix(".zip.part")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    tmp.replace(zip_path)
    print(f"[fetch-police] saved {zip_path} ({zip_path.stat().st_size:,} bytes)")
    return zip_path
