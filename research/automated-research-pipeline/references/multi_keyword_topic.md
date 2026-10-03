# 다중 키워드 주제 검색 패턴

## 생성일: 2026-08-19

## 개요

`RESEARCH_TOPIC` 환경 변수에 **세미콜론(`;`)이나 쉼표(,)`로 구분하여 여러 키워드를 설정**하면,
각 키워드로 개별 검색 후 결과를 병합 + 중복 제거하여 Slack에 전송하는 패턴입니다.

## 환경 변수 설정 예시

```ini
# .env — 세미콜론 구분
RESEARCH_TOPIC=Cancer Immunotherapy; Tumor Microenvironment

# .env — 쉼표 구분
RESEARCH_TOPIC=Cancer Immunotherapy, Tumor Microenvironment, Cancer Genomics
```

## 구현 패턴

### 1. 키워드 파싱 (paper_search.py)

```python
import re

def parse_topics(topic: str) -> List[str]:
    """세미콜론(;) 또는 쉼표(,)로 구분된 다중 키워드 파싱."""
    topics = [t.strip() for t in re.split(r"[;\n,]", topic) if t.strip()]
    return topics if topics else [topic.strip()]
```

### 2. 통합 검색 (search_all)

```python
def search_all(topic, max_results, lookback_days):
    topics = parse_topics(topic)
    all_papers = []

    for kw in topics:
        logger.info(f"[통합] 키워드 '{kw}' 검색 중...")
        all_papers.extend(search_pubmed(kw, ...))
        all_papers.extend(search_biorxiv(kw, ...))
        all_papers.extend(search_semantic_scholar(kw, ...))
        all_papers.extend(search_springer(kw, ...))
        all_papers.extend(search_elsevier(kw, ...))

    # 중복 제거 (title 정규화 후 비교)
    seen = []
    unique = []
    for p in all_papers:
        norm = re.sub(r"\s+", "", p.title.lower())
        if norm not in seen:
            seen.append(norm)
            unique.append(p)

    logger.info(f"[통합] {len(all_papers)}건 → {len(unique)}건 (중복 제거 후)")
    return unique
```

## 주의사항

1. **Rate limit 관리**: 각 키워드로 모든 5개 출처를 검색하므로, API 호출 횟수가 키워드 수에 비례합니다.
   - Semantic Scholar: 1req/s → 5개 출처 × N키워드 = 총 호출량 증가
   - Springer: 500 Hits/Day 제한 → 키워드 2개 × 5출처 = 일일 할당량 빨리 소진
   - Elsevier: 100 Hits/Min 제한 → 호출 간 0.7초 대기 권장

2. **결과 중복**: 동일 논문이 여러 키워드로 검색될 수 있음 → 반드시 title 정규화로 중복 제거 필요

3. **Slack 메시지 크기**: 다중 키워드 결과가 많을 경우 2,300자 청크로 분할 필요 (`split_large_message` 참조)

4. **검색어 가벼움**: "Cancer" 같은 일반어는 bioRxiv 클라이언트 필터링 시 많은 결과를 반환할 수 있음.
   - `max_results * 20` 페이지 크기로 후보를 넉넉히 잡고 필터링 권장

## 관련 패턴

- **bioRxiv OR 매칭**: `re.split(r"\s+", query.lower())`로 단어 분리 후 `any(term in combined ...)` 
- **Slack 메시지 분할**: `split_large_message()` 함수 참조 (SKILL.md §5.2)
- **Rate limit 재시기**: 429 응답 시 `Retry-After` 헤더 기반 재시도 (SKILL.md §2.2)
