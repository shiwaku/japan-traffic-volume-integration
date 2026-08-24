"""JARTIC オープンデータカタログ（opendata.json）の取得と typeB リンク解決。"""
from __future__ import annotations

import requests

from config import Config


def fetch_catalog(cfg: Config) -> list[dict]:
    r = requests.get(cfg.pipeline["catalog_url"], timeout=60)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.json()


def resolve_typeb_url(cfg: Config, region_roman: str, yyyymm: str) -> str | None:
    """指定地域・年月の typeB zip の完全URLを返す。カタログに無ければ None。

    カタログの link は "/202608010000/typeB_sapporo_2026_06.zip" 形式。
    """
    wanted = f"typeB_{region_roman}_{yyyymm[:4]}_{yyyymm[4:]}.zip"
    for entry in fetch_catalog(cfg):
        if entry.get("type") != "typeB":
            continue
        for t in entry.get("targetList", []):
            link = t.get("link", "")
            if link.endswith("/" + wanted):
                return cfg.pipeline["police_download_base"] + link
    return None
