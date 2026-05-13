"""선정된 논문을 LLM으로 한국어 요약."""
from __future__ import annotations

from .collect import Paper
from .config import Config
from .providers import LLMProvider

SYSTEM_PROMPT = (
    "당신은 AI/머신러닝과 'AI를 활용한 기계공학' 연구를 깊이 이해하는 한국어 과학 리뷰어입니다. "
    "주어진 논문의 제목과 초록(필요시 TLDR)만으로, 비전문가도 핵심을 파악할 수 있도록 "
    "정확하고 군더더기 없는 한국어 요약을 작성합니다. 과장·추측은 피하고, 초록에 없는 수치는 지어내지 않습니다."
)

PROMPT_TEMPLATE = """다음 논문을 한국어로 요약하세요.

[제목] {title}
[저자] {authors}
[arXiv 분류] {categories}
[arXiv 초록]
{summary}
{tldr_block}

요구사항:
- 정확히 {n_lines}개의 불릿(- 로 시작)으로 작성. 각 불릿은 한 문장, 25~40자 내외.
- 다음 흐름을 포함: ① 문제/배경 ② 기존 한계 ③ 제안 방법(핵심 아이디어) ④ 방법의 작동 방식 ⑤ 실험/데이터 설정 ⑥ 주요 결과 ⑦ 정량적 성과(초록에 있으면) ⑧ 차별점/기여 ⑨ 한계 또는 향후 과제 ⑩ 한 줄 총평.
- 불릿 외에 다른 텍스트(머리말, 맺음말, 제목 반복)는 출력하지 마세요.
- 전문 용어는 필요하면 영어를 괄호로 병기.

이어서 마지막 줄에 정확히 다음 형식으로 한 줄을 추가하세요:
TAGS: <쉼표로 구분한 1~2개 키워드>  (예: TAGS: LLM 추론, 효율적 학습)
"""


def _format_tldr(paper: Paper) -> str:
    if paper.tldr:
        return f"[Semantic Scholar TLDR]\n{paper.tldr}\n"
    return ""


def _split_summary_and_tags(text: str) -> tuple[str, list[str]]:
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    tags: list[str] = []
    body: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s.upper().startswith("TAGS:"):
            raw = s.split(":", 1)[1]
            tags = [t.strip() for t in raw.replace("，", ",").split(",") if t.strip()]
            continue
        body.append(ln)
    # 선행/후행 빈 줄 정리
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body).strip(), tags


def summarize_paper(provider: LLMProvider, paper: Paper, n_lines: int) -> tuple[str, list[str]]:
    prompt = PROMPT_TEMPLATE.format(
        title=paper.title,
        authors=", ".join(paper.authors[:8]) + (" 외" if len(paper.authors) > 8 else ""),
        categories=", ".join(paper.categories),
        summary=paper.summary,
        tldr_block=_format_tldr(paper),
        n_lines=n_lines,
    )
    raw = provider.generate(SYSTEM_PROMPT, prompt)
    return _split_summary_and_tags(raw)


def summarize_all(cfg: Config, provider: LLMProvider, papers: list[Paper]) -> list[dict]:
    """papers 각각을 요약하여 [{paper..., summary, tags}] 형태로 반환."""
    n_lines = int(cfg.get("llm.summary_lines", 10))
    out: list[dict] = []
    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{len(papers)}] 요약 중: {paper.title[:60]}...")
        try:
            summary, tags = summarize_paper(provider, paper, n_lines)
        except Exception as exc:  # noqa: BLE001
            print(f"    [warn] 요약 실패: {exc}")
            summary, tags = "(요약 생성에 실패했습니다. 원문을 참고하세요.)", []
        item = paper.to_dict()
        item["summary_ko"] = summary
        item["tags"] = tags
        out.append(item)
    return out
