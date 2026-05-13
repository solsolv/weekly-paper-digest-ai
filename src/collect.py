"""arXiv 논문 수집 + Semantic Scholar 인용수 조회."""
from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from .config import Config, env

ARXIV_API = "http://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper"
USER_AGENT = "weekly-paper-digest/1.0 (https://github.com/)"


@dataclass
class Paper:
    arxiv_id: str                 # 버전 제거된 ID (예: "2401.01234")
    title: str
    authors: list[str]
    summary: str                  # arXiv 초록
    categories: list[str]
    published: datetime
    updated: datetime
    pdf_url: str
    abs_url: str
    track: str = ""               # "ai" | "mech"
    citation_count: int | None = None
    influential_citation_count: int | None = None
    s2_url: str | None = None
    tldr: str | None = None       # Semantic Scholar TLDR (있으면)
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "authors": self.authors,
            "summary": self.summary,
            "categories": self.categories,
            "published": self.published.isoformat(),
            "updated": self.updated.isoformat(),
            "pdf_url": self.pdf_url,
            "abs_url": self.abs_url,
            "track": self.track,
            "citation_count": self.citation_count,
            "influential_citation_count": self.influential_citation_count,
            "s2_url": self.s2_url,
            "tldr": self.tldr,
            "matched_keywords": self.matched_keywords,
        }


def _parse_arxiv_datetime(value: str) -> datetime:
    # arXiv: "2024-01-15T12:34:56Z"
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _strip_version(arxiv_id_url: str) -> str:
    # "http://arxiv.org/abs/2401.01234v2" -> "2401.01234"
    tail = arxiv_id_url.rstrip("/").split("/")[-1]
    if "v" in tail:
        head, _, ver = tail.rpartition("v")
        if ver.isdigit():
            return head
    return tail


def _build_query(categories: list[str], keywords: list[str]) -> str:
    cat_clause = " OR ".join(f"cat:{c}" for c in categories)
    query = f"({cat_clause})"
    if keywords:
        kw_clause = " OR ".join(f'abs:"{k}"' for k in keywords)
        query = f"{query} AND ({kw_clause})"
    return query


def fetch_arxiv(categories: list[str], keywords: list[str], max_results: int) -> list[Paper]:
    """arXiv API에서 카테고리/키워드에 맞는 최신 논문을 가져온다 (제출일 내림차순)."""
    search_query = _build_query(categories, keywords)
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)

    papers: list[Paper] = []
    for entry in feed.entries:
        try:
            arxiv_id = _strip_version(entry.id)
            published = _parse_arxiv_datetime(entry.published)
            updated = _parse_arxiv_datetime(entry.updated)
            cats = [t["term"] for t in getattr(entry, "tags", [])] or [getattr(entry, "arxiv_primary_category", {}).get("term", "")]
            pdf_url = ""
            for link in getattr(entry, "links", []):
                if link.get("type") == "application/pdf":
                    pdf_url = link.get("href", "")
            papers.append(
                Paper(
                    arxiv_id=arxiv_id,
                    title=" ".join(entry.title.split()),
                    authors=[a.name for a in getattr(entry, "authors", [])],
                    summary=" ".join(entry.summary.split()),
                    categories=[c for c in cats if c],
                    published=published,
                    updated=updated,
                    pdf_url=pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
                    abs_url=f"https://arxiv.org/abs/{arxiv_id}",
                )
            )
        except Exception as exc:  # noqa: BLE001 - 개별 엔트리 파싱 실패는 건너뜀
            print(f"  [warn] arXiv 엔트리 파싱 실패: {exc}")
    return papers


def _within_lookback(paper: Paper, lookback_days: int, now: datetime) -> bool:
    cutoff = now - timedelta(days=lookback_days)
    return paper.published >= cutoff or paper.updated >= cutoff


def _matched_keywords(paper: Paper, keywords: list[str]) -> list[str]:
    text = f"{paper.title}\n{paper.summary}".lower()
    return [k for k in keywords if k.lower() in text]


def collect_candidates(cfg: Config, track: str, now: datetime | None = None) -> list[Paper]:
    """한 트랙(ai|mech)의 후보 논문 풀을 수집·필터링하여 반환."""
    now = now or datetime.now(timezone.utc)
    track_cfg = cfg.get(f"arxiv.tracks.{track}", {})
    categories = track_cfg.get("categories", [])
    keywords = track_cfg.get("keywords", []) or []
    max_results = cfg.get("arxiv.max_results_per_query", 200)
    lookback_days = cfg.get("selection.lookback_days", 30)
    min_abs = cfg.get("selection.min_abstract_chars", 0)

    raw = fetch_arxiv(categories, keywords, max_results)
    out: list[Paper] = []
    seen: set[str] = set()
    for p in raw:
        if p.arxiv_id in seen:
            continue
        if not _within_lookback(p, lookback_days, now):
            continue
        if len(p.summary) < min_abs:
            continue
        if keywords:
            mk = _matched_keywords(p, keywords)
            if not mk:
                continue
            p.matched_keywords = mk
        p.track = track
        seen.add(p.arxiv_id)
        out.append(p)
    return out


# --------------------------------------------------------------------------
# Semantic Scholar 인용수
# --------------------------------------------------------------------------
def enrich_citations(cfg: Config, papers: list[Paper]) -> None:
    """papers의 citation_count / tldr 등을 Semantic Scholar로 채운다 (in-place)."""
    if not cfg.get("semantic_scholar.enabled", True):
        for p in papers:
            p.citation_count = 0
        return

    api_key = env(cfg.get("semantic_scholar.api_key_env", "SEMANTIC_SCHOLAR_API_KEY"))
    delay = float(cfg.get("semantic_scholar.request_delay_sec", 1.1))
    max_retries = int(cfg.get("semantic_scholar.max_retries", 3))
    headers = {"User-Agent": USER_AGENT}
    if api_key:
        headers["x-api-key"] = api_key
        delay = max(delay, 0.05)
    fields = "citationCount,influentialCitationCount,url,tldr,title"

    for p in papers:
        url = f"{S2_API}/arXiv:{p.arxiv_id}?fields={fields}"
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, headers=headers, timeout=30)
                if resp.status_code == 404:
                    p.citation_count = 0
                    break
                if resp.status_code == 429:
                    wait = delay * (attempt + 2)
                    print(f"  [warn] S2 rate limit, {wait:.1f}s 대기")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                p.citation_count = data.get("citationCount") or 0
                p.influential_citation_count = data.get("influentialCitationCount") or 0
                p.s2_url = data.get("url")
                tldr = data.get("tldr")
                if isinstance(tldr, dict):
                    p.tldr = tldr.get("text")
                break
            except requests.RequestException as exc:
                if attempt == max_retries - 1:
                    print(f"  [warn] S2 조회 실패({p.arxiv_id}): {exc}")
                    p.citation_count = p.citation_count or 0
                else:
                    time.sleep(delay)
        time.sleep(delay)
