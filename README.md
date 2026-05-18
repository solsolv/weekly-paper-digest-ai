# 주간 AI · AI 활용 기계공학 논문 브리핑

매주 월요일 오전 8시(KST), 최근 한 달간 arXiv에 등록된 논문 중 **인용수 상위** 논문을 골라
**AI 분야 2편 + AI 활용 기계공학 2편**을 한국어로 요약해 GitHub Pages에 게시합니다.

- 논문 수집: arXiv API (카테고리 + 키워드)
- 인용수: Semantic Scholar API
- 요약: LLM — 기본 **OpenAI 호환 API (Google Gemini 무료 등급)**, 설정으로 **Claude API** 또는 **로컬 LLM(Ollama)** 전환 가능
- 사이트: 정적 HTML (`docs/`), GitHub Actions cron으로 주간 자동 갱신

## 디렉토리 구조

```
config.yaml                      # 모든 설정 (provider, 카테고리/키워드, 편수 등)
requirements.txt
.github/workflows/weekly-briefing.yml
src/
  main.py        # 엔트리포인트 (수집→인용수→선정→요약→사이트)
  config.py      # config.yaml 로딩
  collect.py     # arXiv 수집 + Semantic Scholar 인용수
  select.py      # 후보 풀 → 트랙별 상위 N편 선정 (과거 소개 논문 제외)
  summarize.py   # LLM 한국어 요약 (10줄 불릿 + 태그)
  render.py      # 주별 JSON 저장 + Jinja2 → docs/ 사이트
  providers/     # LLM provider 추상화 (claude / openai_compat / ollama)
templates/       # base.html, index.html, week.html
data/            # 주별 JSON 아카이브 (중복 추천 방지에도 사용)
docs/            # 생성된 정적 사이트 (GitHub Pages 루트)
```

## 로컬 실행

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 1) 파이프라인 점검 (LLM 호출 없음, arXiv/Semantic Scholar는 호출)
python -m src.main --dry-run

# 2) 실제 요약 생성 (기본 provider = Gemini 사용 시)
#    Google AI Studio에서 키 발급: https://aistudio.google.com/
set GEMINI_API_KEY=AIza...          # PowerShell: $env:GEMINI_API_KEY="AIza..."
set SEMANTIC_SCHOLAR_API_KEY=s2k-...  # (선택) 인용수 조회 rate limit 완화
python -m src.main

# 3) 이미 만든 data/로 사이트만 다시 그리기
python -m src.main --render-only

# 생성 결과: docs/index.html 을 브라우저로 열어 확인
```

추가 옵션: `--no-citations`(Semantic Scholar 생략, 최신순으로 선정), `--week-id 2026-05-11`(주차 강제 지정).

## LLM provider 바꾸기

`config.yaml`의 `llm.provider` 값을 바꾸고, 해당 섹션의 모델명을 조정합니다.

| provider | 설정 키 | 필요한 환경변수 | 비고 |
|---|---|---|---|
| `openai_compat` (기본) | `llm.openai_compat.model`, `.base_url` | `GEMINI_API_KEY` (또는 `OPENAI_API_KEY` 등) | `pip install openai`. 현재 기본은 Google Gemini OpenAI 호환 엔드포인트. 키마다 별도 `api_key_env`로 매핑 가능 |
| `claude` | `llm.claude.model` | `ANTHROPIC_API_KEY` | `pip install anthropic` |
| `ollama` | `llm.ollama.model`, `.host` | (없음) | 로컬에 `ollama serve` 실행 + `ollama pull <model>` |

## GitHub Pages 배포 설정 (최초 1회)

1. **새 저장소 생성** 후 이 폴더 내용을 push
   ```bash
   git init
   git add .
   git commit -m "init: weekly paper briefing"
   git branch -M main
   git remote add origin https://github.com/<USERNAME>/<REPO>.git
   git push -u origin main
   ```
2. **Pages 활성화**: 저장소 → Settings → Pages → *Build and deployment* → Source = **Deploy from a branch**, Branch = **main** / 폴더 = **/docs** → Save
3. **API 키 등록**: 저장소 → Settings → Secrets and variables → Actions → *New repository secret*
   - `GEMINI_API_KEY` (필수, 현재 기본 provider)
   - `SEMANTIC_SCHOLAR_API_KEY` (선택 — 없어도 동작하나 rate limit이 낮음)
   - `ANTHROPIC_API_KEY` (선택, Claude provider 전환 시)
4. **Actions 권한**: Settings → Actions → General → *Workflow permissions* → **Read and write permissions** 체크 (워크플로가 `docs/`·`data/`를 커밋 푸시함)
5. **첫 실행**: Actions 탭 → "Weekly Paper Briefing" → *Run workflow* (원하면 `dry_run`으로 먼저 점검). 이후 매주 일요일 23:00 UTC(= 월요일 08:00 KST)에 자동 실행됩니다.

> 게시 URL: `https://<USERNAME>.github.io/<REPO>/` — 필요하면 `config.yaml`의 `site.base_url`에 적어두세요(현재 내비게이션은 상대경로라 없어도 동작).

## 동작 방식 요약

1. `collect.py` — 트랙별로 arXiv 최신순 N개 후보 수집 → 최근 30일 + (mech는) 키워드 필터
2. Semantic Scholar로 후보들의 `citationCount` 조회
3. `select.py` — 인용수(→ 영향력 인용수 → 최신성) 순 정렬, 과거 소개 논문 제외, 트랙별 상위 2편 선정
4. `summarize.py` — 각 논문 제목·초록(+TLDR)으로 LLM에 한국어 10줄 불릿 요약 + 태그 생성
5. `render.py` — `data/<월요일>.json` 저장, `docs/index.html` & `docs/weeks/<월요일>.html` 생성
6. GitHub Actions가 결과를 커밋·푸시 → Pages 갱신

## 커스터마이즈 포인트 (`config.yaml`)

- `selection.lookback_days` — "최신" 기간 (기본 30일)
- `selection.per_track.{ai,mech}` — 트랙별 편수 (기본 2/2)
- `arxiv.tracks.*.categories` / `.keywords` — 수집 대상 분야·키워드
- `llm.summary_lines` — 요약 줄 수 (기본 10)
- `interests.*` — 관심 세부 주제 (현재는 표시/문서용; 가중치 로직 확장 여지)
