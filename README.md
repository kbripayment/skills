# kbripayment/skills

업무 자동화에서 축적한 **운영 스킬 문서** 저장소입니다.
각 스킬은 하나의 업무 영역을 다루며, `SKILL.md`가 진입점이고 `references/`가 상세 기록입니다.

카테고리별 디렉터리(`productivity/`) 아래에 스킬을 모아 두었습니다.
카테고리를 늘리려면 같은 방식으로 하위 디렉터리를 추가하면 됩니다.

## 스킬 목록

### `productivity/` — 사무·행정 자동화

| 스킬 | 다루는 영역 |
|---|---|
| [`gmail-draft-automation`](productivity/gmail-draft-automation/SKILL.md) | Gmail 초안 생성 — 첨부 크기 제한, Sheets 행 검증, 벤더별 초안 작성 |
| [`gmail-transaction-document-retrieval`](productivity/gmail-transaction-document-retrieval/SKILL.md) | 거래 문서 수집 — 홈택스 전자세금계산서 매칭, 검수사진 회수 |
| [`gmail-ocr-vision-pipeline`](productivity/gmail-ocr-vision-pipeline/SKILL.md) | OCR/Vision 파이프라인 — 모델 출력 정규화, Vision 서명, 날짜별 검수사진 판별 |
| [`html-pin-protected-viewer`](productivity/html-pin-protected-viewer/SKILL.md) | PIN 보호 HTML 문서 — Ceri PDF 추출, 지급신청 검증, 스크립트 연동 |

## 구조

```
<카테고리>/
  <스킬명>/
    SKILL.md          진입점 — 핵심 규칙과 트러블슈팅
    references/*.md   상세 기록 — 실제 장애 사례와 해결 방법
```

`SKILL.md` 는 그 스킬을 처음 만났을 때 읽는 문서이고,
세부 상황별 판단 기준은 `references/` 로 나눠둡니다.

## 문서 성격

`references/` 문서는 대부분 **실제 장애 사례에서 얻은 교훈**을 담고 있습니다.
초안 생성 규칙, 매칭 검증 방법, 실패 원인과 로그 해석 같은 재사용 가능한 지식을
목적별로 정리한 것이므로, 실제 스크립트와 함께 읽어야 이해할 수 있습니다.

문서 안에 시트 행 번호·금액 같은 구체적인 값이 자주 등장하는데, 이는
오매칭·실패를 **재현 가능한 사례로** 설명하기 위한 예시 값입니다.
값 자체에 의미가 있는 것이 아니라 "이런 차이가 나면 걸러져야 한다"는 데모입니다.

## 공개 시 비식별 처리

이 저장소는 공개(public)되므로, 문서 작성 당시 사용된 조직 내부 식별자를 예시값으로
치환했습니다. 기술적 의미와 회귀 예시 값은 유지했습니다.

- 실명·부서·기관 → 예시 조직명
- 계정 이메일 → `example.com` 도메인
- 내부 시트/프로젝트 코드 → 예시 코드
- 거래처·브랜드·제품 카탈로그 번호 → 예시 벤더명·카탈로그 번호

원본은 비공개 환경에 있고, 공개 시점의 복사본에만 이 치환을 적용했습니다.
