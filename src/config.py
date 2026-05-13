"""config.yaml 로딩 및 접근 헬퍼."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
TEMPLATES_DIR = ROOT / "templates"


class Config:
    def __init__(self, data: dict[str, Any], path: Path):
        self._data = data
        self.path = path

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Config":
        p = Path(path) if path else DEFAULT_CONFIG_PATH
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(data, p)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    @property
    def raw(self) -> dict[str, Any]:
        return self._data


def env(name: str, default: str | None = None) -> str | None:
    """환경변수 조회 (빈 문자열은 None 취급)."""
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    return val.strip()
