# 지식 체계 분석 세션 기록 — Nguyen et al. 2020 (Cell)

2026-09-05 세션에서 `knowledge-system-analysis` 스킬 첫 적용: Nguyen et al. 2020 (Cell) 본문 PMC whole-text 정독 + 628건 인용 논문 분석.

---

## 세션에서 확립된 실전 패턴

### 1. PMC whole-text web_extract → read_file 페이지 투 페이지 정독

```
web_extract("https://pmc.ncbi.nlm.nih.gov/articles/PMC7497728/")
→ 약 208K chars 추출
→ read_file(offset=1, limit=200) 로 페이지 투 페이지 정독
→ offset을 후속 호출하여 Results/Discussion까지 완전 독해
```

**왜 이 방식이 효과적인가**:
- PMC whole-text는 Introduction → Results(모든 figure legend 포함) → Discussion → Methods 전체가 하나의 HTML에 포함
- PDF와 달리 figure legend가 텍스트로 추출되어 figure의 논리적 역할을 텍스트만으로 파악 가능
- `read_file`의 offset/limit 페이징으로 큰 파일도 완전 정독 가능

**Pitfall**: web_extract의 char_limit 기본 15,000 — PMC whole-text는 이것의 10배 이상. 반드시 `char_limit=None` 또는 충분히 큰 값(250000)으로 호출해야 함.

### 2. 인과 사슬 추출 포맷

세션에서 유효성이 확인된 인과 사슬 메모 포맷:

```
[핵심 질문] 한 문장
[기존 지식 갭] 그 전까지 몰랐던 것
[인과 사슬]
  Step 1: ... → 증거: Figure X, 실험 Y
  Step 2: ... → 증거: Figure X, 실험 Y
  ...
[인과관계 확립 방식] LOF / GOF / Rescue / 상관관계
[한계]
```

### 3. 인용 논문 테마 분류 방법

OpenAlex 인용 200건을 수집한 후:

```python
# 각 인용 논문의 title + abstract를 읽어 키워드 기반 테마 분류
themes = {
    "ECM/PNN remodeling by microglia": ...,
    "IL-33의 신경생물학적 기능 확장": ...,
    "Microglia-synapse interaction 일반 원리": ...,
    "질병 맥락 (AD, aging)": ...,
    "발달기 시냅스 정제": ...,
}
for p in citing_papers:
    text = (p['title'] + ' ' + p['abstract']).lower()
    if any(kw in text for kw in ['extracellular matrix', 'perineuronal net', 'aggrecan', ...]):
        themes["ECM..."].append(p)
    ...
# 각 테마별로 인용순 상위 5개 출력
```

**핵심**: 단순 인용순 정렬이 아니라 **테마별 분류 후 각 테마 내 인용순 정렬**이 지식 지도 작성에 훨씬 유용함.

### 4. 인용 논문 개수 전략

- Nguyen 2020: 총 628건 인용 → OpenAlex `filter=cites:{id}&per_page=200`으로 200건만 수집
- 상위 200건만으로도 ECM/IL-33/시냅스 키워드가 충분한 대표성 확보
- 628건 전체 수집이 필요한 경우 page=3까지 수집 (200×3=600)
- 연도별 citation count 분포 확인으로 수집 충분성 판단

### 5. 인용 논문 분류의 정확도 한계

- abstract가 없는 논문(59건 내외)은 title만으로 분류 → 정확도 낮음 → `unknown` 또는 `classified_by_title_only` 라벨
- 분류 기준을 너무 세분화하면 빈 테마 발생 → 3~6개 테마로 유지

---

## Nguyen 2020 분석 결과 요약 (Obsidian 저장됨)

- **본문**: PMC7497728 whole-text 완전 정독 (208K chars)
- **인과 사슬**: 경험(EE/SI) → 뉴런 IL-33 → microglia ST2 → ECM protease (Adamts4/Mmp14) → CSPG 탐식 → perisynaptic ECM 제거 → spine 가소성 → 기억 정밀도
- **인과관계 확립**: IL-33 cKO (LOF) + IL1RL1 i-cKO (LOF) + IL-33ΔNLS (GOF) + ChABC rescue — 4중 인과 입증
- **독창적 기여 4가지**: (1) ECM을 능동적 remodeling 대상으로 전환 (2) 완전한 인과 사슬 최초 규명 (3) IL-33=경험 의존적 시냅스 가소성 분자 coupler (4) 노화-인지저하 새 기전
- **인용 확장 5방향**: ECM/PNN 상세화 / IL-33 기능 확장 / microglia-synapse 일반 원리 / 5-부분 시냅스 개념 / 노화·AD 병리

---

## Obsidian 저장 위치

`ObsidianVault/Inbox/scholar/Nguyen2020_Cell_ECM_microglia.md` (16,792 bytes, 260 lines)
