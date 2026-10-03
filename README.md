# kbripayment/skills

업무·연구 자동화에서 축적한 **운영 스킬 문서** 저장소입니다.
각 스킬은 하나의 업무 영역을 다루며, `SKILL.md`가 진입점이고 `references/`가 상세 기록입니다.

카테고리별 디렉터리 아래에 스킬을 모아 두었습니다.
카테고리를 늘리려면 같은 방식으로 하위 디렉터리를 추가하면 됩니다.

## 스킬 목록

### `productivity/` — 사무·행정 자동화

| 스킬 | 다루는 영역 |
|---|---|
| [`gmail-draft-automation`](productivity/gmail-draft-automation/SKILL.md) | Gmail 초안 생성 — 첨부 크기 제한, Sheets 행 검증, 벤더별 초안 작성 |
| [`gmail-transaction-document-retrieval`](productivity/gmail-transaction-document-retrieval/SKILL.md) | 거래 문서 수집 — 홈택스 전자세금계산서 매칭, 검수사진 회수 |
| [`gmail-ocr-vision-pipeline`](productivity/gmail-ocr-vision-pipeline/SKILL.md) | OCR/Vision 파이프라인 — 모델 출력 정규화, Vision 서명, 날짜별 검수사진 판별 |
| [`html-pin-protected-viewer`](productivity/html-pin-protected-viewer/SKILL.md) | PIN 보호 HTML 문서 — Ceri PDF 추출, 지급신청 검증, 스크립트 연동 |

### `research/` — 학술 연구·정보 수집

논문 검색, 문헌 검토, 인용 분석, 지식관리, 모니터링 등 연구 workflows 18종입니다.

| 스킬 | 다루는 영역 |
|---|---|
| [`academic-api-integration`](research/academic-api-integration/SKILL.md) | Springer/Elsevier API의 검증된 엔드포인트·인증·파싱 패턴 |
| [`arxiv`](research/arxiv/SKILL.md) | arXiv 논문 검색 — 키워드·저자·카테고리·ID |
| [`automated-research-pipeline`](research/automated-research-pipeline/SKILL.md) | 일일 논문 검색 → LLM 요약 → Slack 알림 자동화 |
| [`blogwatcher`](research/blogwatcher/SKILL.md) | 블로그 및 RSS/Atom 피드 모니터링 |
| [`citation-analysis-workflow`](research/citation-analysis-workflow/SKILL.md) | 인용 분석 워크플로 |
| [`competitor-news-monitor`](research/competitor-news-monitor/SKILL.md) | 특정 기업 중요 뉴스 감시 및 다이제스트 |
| [`grounded-citations`](research/grounded-citations/SKILL.md) | 답변·문서를 인용 가능한 출처에 근거화 |
| [`knowledge-system-analysis`](research/knowledge-system-analysis/SKILL.md) | 지식 시스템 구조 분석 |
| [`knowledge_base_update`](research/knowledge_base_update/SKILL.md) | 위키/원문 갱신 및 RAG 동기화 |
| [`llm-wiki`](research/llm-wiki/SKILL.md) | 상호 링크된 마크다운 지식베이스 구축·질의 |
| [`notebooklm-wiki`](research/notebooklm-wiki/SKILL.md) | NotebookLM 연동 연구 자동화 |
| [`paper-review`](research/paper-review/SKILL.md) | 논문 reviewer 비평·요약을 Slack에 순차 공유 |
| [`paper-summary`](research/paper-summary/SKILL.md) | 논문 원문·코멘트·요약 분할 전송 스크립트 |
| [`polymarket`](research/polymarket/SKILL.md) | Polymarket 시세·호가창·이력 조회 |
| [`pubmed-mcp-server`](research/pubmed-mcp-server/README.md) | PubMed/Europe PMC 검색 MCP 서버 |
| [`research-paper-writing`](research/research-paper-writing/SKILL.md) | NeurIPS/ICML/ICLR 투고 논문 작성 |
| [`research_new`](research/research_new/SKILL.md) | 주제 설정 → 다중 소스 검색 → Local LLM 요약 → Slack 알림 |
| [`scholar-citation-search`](research/scholar-citation-search/SKILL.md) | Scholar 인용 검색·원문 확보 파이프라인 |

## 구조

```
<카테고리>/
  <스킬명>/
    SKILL.md          진입점 — 핵심 규칙과 트러블슈팅
    references/*.md   상세 기록 — 실제 장애 사례와 해결 방법
    scripts/·src/     실행 코드 (해당 스킬에 한정)
```

`SKILL.md` 는 그 스킬을 처음 만났을 때 읽는 문서이고,
세부 상황별 판단 기준은 `references/` 로 나눠둡니다.

각 스킬의 구성은 제각각입니다. 문서만 있는 스킬이 있고, 파이썬·타입스크립트
스크립트를 함께 포함하는 스킬도 있습니다. `DESCRIPTION.md` 는 해당 카테고리의
frontmatter 설명입니다.

## 문서 성격

`references/` 문서는 대부분 **실제 장애 사례에서 얻은 교훈**을 담고 있습니다.
초안 생성 규칙, 매칭 검증 방법, 실패 원인과 로그 해석 같은 재사용 가능한 지식을
목적별로 정리한 것이므로, 실제 스크립트와 함께 읽어야 이해할 수 있습니다.

문서 안에 시트 행 번호·금액 같은 구체적인 값이 자주 등장하는데, 이는
오매칭·실패를 **재현 가능한 사례로** 설명하기 위한 예시 값입니다.
값 자체에 의미가 있는 것이 아니라 "이런 차이가 나면 걸러져야 한다"는 데모입니다.

## 공개 시 비식별 처리

이 저장소는 공개(public)되므로, 문서 작성 당시 사용된 조직 내부 식별자와
라이브 시크릿을 예시값으로 치환했습니다. 기술적 의미와 회귀 예시 값은 유지했습니다.

- 실명·부서·기관 → 예시 조직명
- 계정 이메일 → `example.com` 도메인
- 내부 시트/프로젝트 코드 → 예시 코드
- 거래처·브랜드·제품 카탈로그 번호 → 예시 벤더명·카탈로그 번호
- API 키·봇 토큰 → `your_..._here` 플레이스홀더
- 사내 LLM 서버 주소 → `*.example.local`

원본은 비공개 환경에 있고, 공개 시점의 복사본에만 이 치환을 적용했습니다.
`.env`, `*.pyc`, `*.log`, `*.bak`, `__pycache__/` 는 커밋 대상에서 제외됩니다.
