"""엔트리포인트: 논문 수집 → 인용수 → 선정 → 요약 → 사이트 생성.

사용 예:
    python -m src.main                 # 정상 실행 (요약 LLM 호출)
    python -m src.main --dry-run       # LLM 호출 없이 파이프라인만 점검
    python -m src.main --no-citations  # Semantic Scholar 호출 생략(최신순으로 선정)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from .collect import Paper, collect_candidates, enrich_citations
from .config import Config
from .render import TRACK_LABEL, render_site, save_week_data
from .select import load_featured_ids, select_for_track, trim_candidate_pool


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


def _placeholder_summary(paper: Paper, n_lines: int) -> tuple[str, list[str]]:
    bullets = ["- (dry-run 모드: 실제 요약은 생성되지 않았습니다.)"]
    bullets += [f"- 초록 발췌: {paper.summary[:60]}..."]
    bullets += ["- 자세한 내용은 원문 링크를 참고하세요."] * max(0, n_lines - 2)
    return "\n".join(bullets[:n_lines]), ["dry-run"]


def run(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    tz_name = cfg.get("site.timezone", "Asia/Seoul")
    week_id = args.week_id or compute_week_id(tz_name)
    print(f"== 주간 다이제스트 빌드: {week_id} (tz={tz_name}) ==")

    featured = load_featured_ids() if cfg.get("selection.exclude_already_featured", True) else set()
    if featured:
        print(f"  과거 소개 논문 {len(featured)}편 제외 대상")

    tracks = ["ai", "mech"]
    selected: list[Paper] = []
    for track in tracks:
        print(f"\n[{TRACK_LABEL[track]}] 후보 수집...")
        candidates = collect_candidates(cfg, track)
        candidates = trim_candidate_pool(cfg, track, candidates)
        print(f"  후보 {len(candidates)}편")
        if not args.no_citations:
            print("  인용수 조회(Semantic Scholar)...")
            enrich_citations(cfg, candidates)
        else:
            for c in candidates:
                c.citation_count = 0
        picks = select_for_track(cfg, track, candidates, featured)
        for p in picks:
            cc = p.citation_count if p.citation_count is not None else "?"
            print(f"  선정: [{cc} cites] {p.title[:70]}")
        selected.extend(picks)

    if not selected:
        print("\n선정된 논문이 없습니다. (쿼리/기간 설정을 확인하세요)")
        return 1

    print(f"\n총 {len(selected)}편 요약 시작...")
    n_lines = int(cfg.get("llm.summary_lines", 10))
    items: list[dict] = []
    if args.dry_run:
        for p in selected:
            summary, tags = _placeholder_summary(p, n_lines)
            d = p.to_dict()
            d["summary_ko"], d["tags"] = summary, tags
            items.append(d)
    else:
        from .providers import build_provider  # noqa: PLC0415
        from .summarize import summarize_all  # noqa: PLC0415

        provider = build_provider(cfg)
        print(f"  provider={provider.name}, model={provider.model}")
        items = summarize_all(cfg, provider, selected)

    payload = {
        "week_id": week_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "site_title": cfg.get("site.title", ""),
        "provider": cfg.get("llm.provider", ""),
        "lookback_days": cfg.get("selection.lookback_days", 30),
        "tracks": {t: [it for it in items if it.get("track") == t] for t in tracks},
        "papers": items,
    }
    fp = save_week_data(week_id, payload)
    print(f"  데이터 저장: {fp}")

    render_site(cfg)
    print("\n완료.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="주간 논문 다이제스트 빌더")
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
