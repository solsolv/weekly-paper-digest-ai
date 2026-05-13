"""후보 풀에서 트랙별 최종 논문 선정 (인용수 상위 + 관심사 가산점)."""
from __future__ import annotations

import json
from pathlib import Path

from .collect import Paper
from .config import DATA_DIR, Config


def load_featured_ids() -> set[str]:
    """data/*.json 아카이브에 이미 등장한 arXiv ID 집합."""
    ids: set[str] = set()
    if not DATA_DIR.exists():
        return ids
    for fp in DATA_DIR.glob("*.json"):
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for p in payload.get("papers", []):
            if p.get("arxiv_id"):
                ids.add(p["arxiv_id"])
    return ids


def _score(paper: Paper) -> tuple:
    """정렬 키: (인용수, 영향력 인용수, 최신성). 클수록 우선."""
    cc = paper.citation_count or 0
    ic = paper.influential_citation_count or 0
    recency = paper.published.timestamp()
    return (cc, ic, recency)


def select_for_track(
    cfg: Config,
    track: str,
    candidates: list[Paper],
    featured_ids: set[str],
) -> list[Paper]:
    n = int(cfg.get(f"selection.per_track.{track}", 2))
    exclude = bool(cfg.get("selection.exclude_already_featured", True))

    pool = [p for p in candidates if not (exclude and p.arxiv_id in featured_ids)]
    pool.sort(key=_score, reverse=True)
    return pool[:n]


def trim_candidate_pool(cfg: Config, track: str, candidates: list[Paper]) -> list[Paper]:
    """인용수 조회 비용을 줄이기 위해, 최신순 상위 N개만 후보로 남긴다."""
    limit = int(cfg.get("selection.candidate_pool_per_track", 60))
    # candidates는 collect 단계에서 submittedDate 내림차순으로 들어옴
    return candidates[:limit]
