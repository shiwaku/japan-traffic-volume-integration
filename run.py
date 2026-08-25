"""統合交通量データ パイプラインランナー。

例:
    python run.py --step all --regions sapporo --month 2026-06
    python run.py --step fetch-police,parse-police --regions sapporo --month 2026-06
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from config import load_config  # noqa: E402

STEPS = [
    "fetch-police",
    "parse-police",
    "fetch-mlit",
    "ingest-mlit",
    "stations",
    "unify",
    "export",
    "export-viewer",
    "verify",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", required=True, help="カンマ区切り、または all")
    ap.add_argument("--regions", default="sapporo", help="カンマ区切りの地域名（configs/regions.yaml のキー）")
    ap.add_argument("--month", required=True, help="YYYY-MM")
    args = ap.parse_args()

    cfg = load_config()
    yyyymm = args.month.replace("-", "")
    regions = [r.strip() for r in args.regions.split(",")]
    steps = STEPS if args.step == "all" else [s.strip() for s in args.step.split(",")]
    unknown = set(steps) - set(STEPS)
    if unknown:
        sys.exit(f"unknown steps: {unknown} (choose from {STEPS})")

    for step in steps:
        print(f"\n===== {step} ({args.month}, regions={regions}) =====")
        if step == "fetch-police":
            from fetch_police import fetch_police
            for r in regions:
                fetch_police(cfg, r, yyyymm)
        elif step == "parse-police":
            from parse_police import parse_police
            for r in regions:
                parse_police(cfg, r, yyyymm)
        elif step == "fetch-mlit":
            from fetch_mlit import fetch_mlit
            for r in regions:
                fetch_mlit(cfg, r, yyyymm)
        elif step == "ingest-mlit":
            from ingest_mlit import ingest_mlit
            ingest_mlit(cfg, yyyymm)
        elif step == "stations":
            from stations import build_stations
            build_stations(cfg, regions, yyyymm)
        elif step == "unify":
            from unify import unify
            unify(cfg, regions, yyyymm)
        elif step == "export":
            from export import export
            export(cfg, yyyymm)
        elif step == "export-viewer":
            from export_viewer import export_viewer
            export_viewer(cfg, yyyymm)
        elif step == "verify":
            from verify import verify
            verify(cfg, regions, yyyymm)


if __name__ == "__main__":
    main()
