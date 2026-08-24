"""設定ロードとパス解決。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(name: str) -> dict:
    with open(REPO_ROOT / "configs" / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class Config:
    pipeline: dict
    regions: dict

    @property
    def data_dir(self) -> Path:
        return REPO_ROOT / self.pipeline["paths"]["data_dir"]

    @property
    def reports_dir(self) -> Path:
        return REPO_ROOT / self.pipeline["paths"]["reports_dir"]

    @property
    def mlit_local_dir(self) -> Path:
        return (REPO_ROOT / self.pipeline["paths"]["mlit_local_dir"]).resolve()

    def police_dir(self, region: str, yyyymm: str) -> Path:
        return self.data_dir / "police" / region / yyyymm

    def mlit_api_dir(self, yyyymm: str) -> Path:
        return self.data_dir / "mlit_api" / yyyymm

    def output_dir(self, yyyymm: str) -> Path:
        return self.data_dir / "output" / yyyymm

    def tmt_dir(self) -> Path:
        return self.data_dir / "private" / "tmt"

    def region(self, name: str) -> dict:
        return self.regions["regions"][name]


def load_config() -> Config:
    return Config(pipeline=_load_yaml("pipeline.yaml"), regions=_load_yaml("regions.yaml"))


def ensure_dir(p: Path) -> Path:
    os.makedirs(p, exist_ok=True)
    return p
