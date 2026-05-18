"""엔트리포인트: 논문 수집(슬롯별) → 인용수·기관 → 선정 → 요약 → 사이트 생성.

사용 예:
    python -m src.main                 # 정상 실행 (요약 LLM 호출)
    python -m src.main --dry-run       # LLM 호출 없이 파이프라인만 점검
    python -m src.main --no-citations  # Semantic Scholar 호출 생략(최신순으로 선정)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_env_local() -> None:
    """프로젝트 루트의 `.env.local`을 KEY=VALUE 형식으로 환경변수에 주입.
    이미 셸에 설정된 키는 덮어쓰지 않는다 (CI/Actions의 secrets 우선)."""
    fp = Path(__file__).resolve().parent.parent / ".env.local"
    if not fp.exists():
        return
    for line in fp.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env_local()

from .collect import (
    Paper,
    collect_candidates,
    enrich_citations,
    fetch_arxiv_by_ids,
    fetch_huggingface_weekly,
)
from .config import Config
from .relevance import filter_by_relevance
from .render import TRACK_LABEL, render_site, save_week_data
from .select import (
    impact_score,
    latest_score,
    load_featured_ids,
    select_impact,
    select_latest,
    trim_candidate_pool,
)


def _tz(name: str):
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - tzdata 미설치 등
        if name == "Asia/Seoul":
            return timezone(timedelta(hours=9))
        return timezone.utc


def compute_week_id(tz_name: str) -> str:
    """현재 주(ISO)의 월요일 날짜를 YYYY-MM-DD로 반환 (배포 타임존 기준)."""
    now_local = datetime.now(_tz(tz_name))
    monday = now_local - timedelta(days=now_local.weekday())
    return monday.strftime("%Y-%m-%d")


def _placeholder_summary(paper: Paper, n_lines: int) -> tuple[str, str, list[str]]:
    bullets = ["- (dry-run 모드: 실제 요약은 생성되지 않았습니다.)"]
    bullets += [f"- 초록 발췌: {paper.summary[:60]}..."]
    bullets += ["- 자세한 내용은 원문 링크를 참고하세요."] * max(0, n_lines - 2)
    return paper.title, "\n".join(bullets[:n_lines]), ["dry-run"]


def _collect_latest_for_ai_via_hf(cfg: Config) -> list[Paper]:
    """AI 최신 슬롯 후보를 HF Papers trending에서 수집 → arXiv 본문 보강."""
    top_n = int(cfg.get("huggingface.top_n", 10))
    hf_items = fetch_huggingface_weekly(top_n=top_n, days_back=7)
    if not hf_items:
        print("  [info] HF Papers 결과 없음")
        return []
    arxiv_ids = [it["arxiv_id"] for it in hf_items]
    print(f"  HF Papers 후보 {len(arxiv_ids)}편 → arXiv 본문 보강")
    papers = fetch_arxiv_by_ids(arxiv_ids)
    # HF upvote 정보 매핑
    upv_map = {it["arxiv_id"]: it["upvotes"] for it in hf_items}
    for p in papers:
        p.source = "huggingface"
        p.track = "ai"
        p.hf_upvotes = upv_map.get(p.arxiv_id)
    return papers


def run(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    tz_name = cfg.get("site.timezone", "Asia/Seoul")
    week_id = args.week_id or compute_week_id(tz_name)
    print(f"== 주간 브리핑 빌드: {week_id} (tz={tz_name}) ==")

    featured = load_featured_ids() if cfg.get("selection.exclude_already_featured", True) else set()
    if featured:
        print(f"  과거 소개 논문 {len(featured)}편 제외 대상")

    impact_lookback = int(cfg.get("selection.slots.impact.lookback_days", 365))
    latest_lookback = int(cfg.get("selection.slots.latest.lookback_days", 14))
    latest_source_cfg = cfg.get("selection.latest_source", {}) or {}
    hf_enabled = bool(cfg.get("huggingface.enabled", True))
    hf_fallback = bool(cfg.get("huggingface.fallback_to_arxiv", True))

    # LLM 게이트 + 요약 공유용 provider — dry_run에서는 None
    provider = None
    if not args.dry_run:
        from .providers import build_provider  # noqa: PLC0415

        provider = build_provider(cfg)
        print(f"  provider={provider.name}, model={provider.model}")

    tracks = ["ai", "mech"]
    selected: list[Paper] = []
    for idx, track in enumerate(tracks):
        if idx > 0:
            time.sleep(15)  # arXiv rate limit 회피용 트랙 간 대기

        impact_s2_sort = cfg.get("s2_search.sort_impact", "citationCount:desc")
        latest_s2_sort = cfg.get("s2_search.sort_latest", "publicationDate:desc")

        print(f"\n[{TRACK_LABEL[track]}] === 임팩트 슬롯 ({impact_lookback}일 lookback) ===")
        impact_pool = collect_candidates(cfg, track, lookback_days=impact_lookback, s2_sort=impact_s2_sort)
        impact_pool = trim_candidate_pool(cfg, impact_pool)
        print(f"  후보 {len(impact_pool)}편")
        if not args.no_citations:
            print("  인용수·소속기관 조회(Semantic Scholar)...")
            enrich_citations(cfg, impact_pool)
        else:
            for c in impact_pool:
                c.citation_count = 0
        impact_pool.sort(key=impact_score, reverse=True)
        if provider is not None:
            impact_pool = filter_by_relevance(cfg, provider, track, impact_pool)
        impact_pick = select_impact(cfg, impact_pool, featured)
        if impact_pick:
            impact_pick.slot = "impact"
            cc = impact_pick.citation_count if impact_pick.citation_count is not None else "?"
            icc = impact_pick.influential_citation_count if impact_pick.influential_citation_count is not None else "?"
            print(f"  임팩트 선정: [cc={cc}, infl={icc}] {impact_pick.title[:70]}")

        time.sleep(15)

        latest_source = latest_source_cfg.get(track, "arxiv")
        print(f"\n[{TRACK_LABEL[track]}] === 최신 슬롯 ({latest_lookback}일 lookback, source={latest_source}) ===")
        latest_pool: list[Paper] = []
        if latest_source == "huggingface_weekly" and hf_enabled:
            latest_pool = _collect_latest_for_ai_via_hf(cfg)
            if not latest_pool and hf_fallback:
                print("  [info] HF 결과 없음 → arXiv 14일 fallback")
                latest_pool = collect_candidates(cfg, track, lookback_days=latest_lookback, s2_sort=latest_s2_sort)
        else:
            latest_pool = collect_candidates(cfg, track, lookback_days=latest_lookback, s2_sort=latest_s2_sort)
        latest_pool = trim_candidate_pool(cfg, latest_pool)
        print(f"  후보 {len(latest_pool)}편")
        if not args.no_citations:
            print("  인용수·소속기관 조회(Semantic Scholar)...")
            enrich_citations(cfg, latest_pool)
        else:
            for c in latest_pool:
                c.citation_count = 0
        latest_pool.sort(key=latest_score, reverse=True)
        if provider is not None:
            latest_pool = filter_by_relevance(cfg, provider, track, latest_pool)
        impact_id = {impact_pick.arxiv_id} if impact_pick else set()
        latest_pick = select_latest(cfg, latest_pool, featured, exclude_ids=impact_id)
        if latest_pick:
            latest_pick.slot = "latest"
            upv = f", hf_upvotes={latest_pick.hf_upvotes}" if latest_pick.hf_upvotes is not None else ""
            print(f"  최신 선정: [pub={latest_pick.published.date()}{upv}] {latest_pick.title[:70]}")

        for p in [impact_pick, latest_pick]:
            if p is not None:
                selected.append(p)

    if not selected:
        print("\n선정된 논문이 없습니다. (쿼리/기간 설정을 확인하세요)")
        return 1

    print(f"\n총 {len(selected)}편 요약 시작...")
    n_lines = int(cfg.get("llm.summary_lines", 5))
    items: list[dict] = []
    if args.dry_run:
        for p in selected:
            title_ko, summary, tags = _placeholder_summary(p, n_lines)
            d = p.to_dict()
            d["title_ko"], d["summary_ko"], d["tags"] = "", summary, tags
            items.append(d)
    else:
        from .summarize import summarize_all  # noqa: PLC0415

        items = summarize_all(cfg, provider, selected)

    payload = {
        "week_id": week_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "site_title": cfg.get("site.title", ""),
        "provider": cfg.get("llm.provider", ""),
        "impact_lookback_days": impact_lookback,
        "latest_lookback_days": latest_lookback,
        "tracks": {t: [it for it in items if it.get("track") == t] for t in tracks},
        "papers": items,
    }
    fp = save_week_data(week_id, payload)
    print(f"  데이터 저장: {fp}")

    render_site(cfg)
    print("\n완료.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="주간 논문 브리핑 빌더")
    parser.add_argument("--config", default=None, help="config.yaml 경로")
    parser.add_argument("--week-id", default=None, help="주차 ID(YYYY-MM-DD) 강제 지정")
    parser.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 실행")
    parser.add_argument("--no-citations", action="store_true", help="Semantic Scholar 호출 생략")
    parser.add_argument("--render-only", action="store_true", help="수집/요약 없이 기존 data/로 사이트만 재생성")
    args = parser.parse_args(argv)

    if args.render_only:
        cfg = Config.load(args.config)
        render_site(cfg)
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
