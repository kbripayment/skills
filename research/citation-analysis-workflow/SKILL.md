---
name: citation-analysis-workflow
description: >
  논문 인용 분석을 OpenAlex API로 수행하고 Obsidian에 저장하는 워크플로우.
version: 1.0.0
last_updated: 2026-09-08
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Citation, OpenAlex, Pipeline]
    category: research
    related_skills: [scholar-citation-search, obsidian]
    requires:
      tools: [web_extract, terminal, write_file]
    env: []
---

# Citation Analysis Workflow (OpenAlex 기반)

논문 인용 논문(Cited by) 목록을 OpenAlex API로 수집·분석하여 Obsidian에 저장하는 워크플로우.
Scholar 차단 시 대체 경로로 활용 가능.

## 언제 사용

- "이 논문을 인용한 논문들 정리해줘" / "이 논문 후속 연구 동향을 알고 싶어"
- Google Scholar 접근이 차단되었거나 캡차/봇 감지로 Cited by 페이지 접근 실패
- 논문 제목/DOI/PMID 중 하나만으로 인용 분석을 시작하고 싶을 때
- scite 검증 토큰 없이도 OpenAlex만으로 인용 분석을 수행하고 싶을 때
- 논문 인용 통계를 빠르게 CSV/JSON으로 확보하고 싶을 때

> Scholar가 정상 동작하면 `scholar-citation-search` 스킬을 우선 사용. 이 스킬은 OpenAlex 직접 수집에 특화된 경량 워크플로우다.

## 빠른 시작 (스크립트 사용)

가장 간단한 방법 — `scripts/fetch_openalex_citations.py`를 사용:

```bash
# 1. 스크립트 실행 (openalex_id만 필요)
python scripts/fetch_openalex_citations.py W4284973934

# 2. 결과 → JSON 파일에서 분석
# 스크립트는 stdout에 JSON 출력. 파일로 저장 가능:
python scripts/fetch_openalex_citations.py W4284973934 > citations.json

# 3. 상위 20편 확인
python -c "import json; d=json.load(open('citations.json')); [print(f\"{s['rank']}. [{s['year']}] {s['title'][:70]} ({s['cited_by_count']}회)\") for s in d['summary']['top_n']]"
```

이 스크립트는 API 키 없이 동작하며, `citation-analysis-workflow` 스킬의 ②단계(인용 수집)를 수행한다. ③~④단계(분석·저장)는 별도 처리.

---

## 파이프라인 (4단계)

```
[입력: title | doi | openalex_id]
        │
        ▼
┌─────────────────────────────────────┐
│ ① 대상 논문 식별 (OpenAlex 조회)   │
│  - DOI/제목으로 OpenAlex 검색      │
│  - OpenAlex ID 확보                │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ ② 인용 논문 목록 수집              │
│  - /works?filter=cites:{openalex_id}│
│  - per_page=200, 정렬=cited_by_..  │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ ③ 분석 & 분류                     │
│  - 연도별/테마별 분류, Top N 추출  │
│  - 동향 요약                       │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ ④ Obsidian 저장                   │
│  - 논문 노트 + 분석 리포트          │
│  - YAML frontmatter 메타데이터      │
└─────────────────────────────────────┘
```

## ② 인용 논문 수집 (핵심 API)

**올바른 엔드포인트:**
```
GET /works?filter=cites:{openalex_id}&per_page=200&sort=cited_by_count:desc
```

**잘못된 엔드포인트 (사용 금지):**
```
GET /works/{openalex_id}/cited_by → 원 논문 메타데이터만 반환 (2026-09-05, 09-08 확인)
```

**Python urllib 스크립트 예시:**
스크립트 파일로 작성 후 `python 스크립트.py` 실행 (`python3`은 Windows에서 없을 수 있음):
```python
import urllib.request, json

def fetch_citations(oa_id, per_page=200):
    results, page = [], 1
    while len(results) < 300:
        url = f"https://api.openalex.org/works?filter=cites:{oa_id}&per_page={per_page}&page={page}&sort=cited_by_count:desc"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        batch = data.get("results", [])
        if not batch: break
        results.extend(batch); page += 1
        if len(batch) < per_page: break
    # DOI 기준 중복 제거
    seen, uniq = set(), []
    for r in results:
        doi = r.get("doi") or ""
        if doi not in seen: seen.add(doi); uniq.append(r)
    return uniq
```

## 실행 환경 주의사항 (2026-09-08 세션)

1. **python3 없음**: Windows/Git Bash → `python` 사용 (Python 3.11.9)
2. **heredoc 실패 가능**: `python3 << 'PYEOF'` 대신 스크립트 파일 작성 후 실행
3. **web_extract JSON 파싱 실패 가능**: control character 오류 시 `terminal` + `urllib` 스크립트로 대체
4. **스크립트 파일 패턴 권장**: write_file → terminal 실행이 execute_code보다 안정적

## ③ 분석 & 분류

- **연도별 분포**: 연도별 논문 수 + 신규 인용 수
- **상위 10~20편**: 인용 수 기준, 표 형태로 정리
- **테마별 분류**: 직접 후속/확장/방법론/질환 연관/비관련
- **동향 요약**: 핵심 개념 확산 경로, 가장 영향력 있는 후속 논문

## ④ Obsidian 저장

`obsidian` 스킬 패턴 사용. Inbox/scholar/에 저장.

**논문 노트 frontmatter:**
```yaml
---
title: 논문 제목
doi: 10.xxxx/...
year: 2022
openalex_id: WXXXX
oa_url: 링크
retrieval_status: abstract_only
tags: [태그]
---
```

**분석 리포트:** 대상 논문 정보 + 인용 통계 + Top 10 표 + 테마별 분류 + 동향 요약 + 저장 메타데이터.

## scite 검증 (선택)

`SCITE_ACCESS_TOKEN` 없으면 OpenAlex만으로 진행. Obsidian에 `scite_unreachable` 라벨 기록.
scite는 보강 계층이지 필수가 아님.

## 제한 사항

| 상황 | 대응 |
|------|------|
| 인용 200건 초과 | page 파라미터 페이지네이션 |
| DOI 없음 | 제목 검색으로 식별 시도 |
| JSON 파싱 실패 | terminal + urllib 스크립트로 대체 |
| 저자 정보 누락 | OpenAlex authorships 필드 확인 |

## 변경 이력

- **1.0.0 (2026-09-08)**: 최초 생성. OpenAlex 인용 수집 중심, 실행 환경 주의사항, scite graceful degradation 포함.
