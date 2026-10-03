# 거래명세서 PDF → 업체별 견적서·전자세금계산서 요청 초안

스캔 거래명세서에서 업체·품목·수량을 뽑아 Gmail 임시보관함 초안을 만드는 절차.
`automation` 스킬의 `statement_pdf_inspector.py`가 이 작업을 자동화하지만,
**provider chain이 죽으면 아래 수동 경로로 직접 처리한다.**

## 언제 수동 경로를 고르는가

대형 배치(6개 파일)를 스크립트에 맡겼는데 로그가 아래처럼 반복되면 즉시 중단하고
직접 경로로 전환한다. 기다려도 회복되지 않는다.

```
[vision] Groq Chat API Vision 429 (attempt 1/3) … (attempt 3/3)
[vision] NVIDIA NIM 폴백 호출… HTTP 503
[vision] Local 호출 중 (타임아웃 900초)…   ← 여기서 15분씩 소모
```

판단 순서:

1. **각 provider를 직접 probe**한다 (스크립트 로그만 믿지 않는다):
   - Groq 채팅 최소 호출 → 200이어도 **Vision 쿼터는 별개**다. 이미지 요청을
     한 번 실제로 쏴봐야 안다.
   - NVIDIA `POST /v1/chat/completions`에 60~90초 타임아웃을 걸어 본다.
   - llama.cpp는 `/v1/models`가 200이어도 추론이 멈출 수 있다. **텍스트 전용
     최소 호출**로 추론 경로까지 확인한다.
2. 셋 다 죽었으면 스크립트 재시도·대기는 무의미하다. **에이전트 자신의
   `vision_analyze`는 별개 경로이며 정상 동작한다.**
3. 사용자에게 "기다릴까요 / 지금 처리할까요"를 물어보되, 에이전트가 직접
   처리할 수 있음을 먼저 밝힌다. 스크립트만 가능한 것처럼 오해시키지 않는다.

## 타임아웃 규칙 (스크립트를 계속 쓸 경우)

폴백 호출에 `timeout=1800`을 하드코딩하면 무응답 티어 하나당 30분이 소모된다.
티어별로 분리한다:

```python
LLM_TIMEOUT_REMOTE = int(os.getenv("LLM_TIMEOUT_REMOTE", "150"))
LLM_TIMEOUT_ALT    = int(os.getenv("LLM_TIMEOUT_ALT",    "300"))
LLM_TIMEOUT_LOCAL  = int(os.getenv("LLM_TIMEOUT_LOCAL",  "1800"))
# LOCAL_VISION_TIMEOUT: 3600 → 900 (15분)
```

CPU 기반 72B 로컬 모델은 정상에도 분 단위가 걸리지만, 900초보다 크면
서버 다운 시 파이프라인이 1시간씩 멈춘다.

## 수동 경로 절차

1. **페이지 렌더링** — 스캔 PDF는 텍스트 레이어가 0자다. 전 페이지를
   200 DPI로 뽑고 긴 변 1600px 이하로 줄여 JPEG로 저장:

   ```python
   pix = pg.get_pixmap(dpi=200)
   im = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
   if max(im.size) > 1600: im.thumbnail((1600, 1600))
   im.save(fp, quality=88)
   ```

2. **파일별 1페이지 + 나머지 페이지로 나눠 `vision_analyze` 호출.**
   1페이지엔 업체명·사업자번호·발행일·품목행 전체를, 나머지 페이엔
   "추가 품목행 있으면 행별로, 없으면 '없음'"을 묻는다.
   - **2페이지 이후는 보통 "없음"**이므로 짧은 프롬프트로 시간을 아낀다.
   - 타임아웃되면 같은 질문을 그대로 재요청하지 말고 **축소본(950px)으로
     바꿔서** 다시 부른다. 1131×1600이 실패하고 672×950이 성공한다.
   - 같은 인자를 반복하면 안 된다 — 전략을 바꿔야 한다.

3. **업체 이메일을 3곳에서 찾는다** (우선순위 순):
   - 거래명세서에 인쇄된 E-mail (가장 신뢰할 수 있음)
   - `DEFAULT_SUPPLIERS` 매핑
   - Google Sheets 전수 검색 (비시스템 시트 전부 훑어 업체명 행 찾기)

4. **업체별로 묶어 초안을 만든다.** 거래명세서 파일 1개에 여러 업체 거래가
   몰려 있을 수 있으므로 **페이지별 업체명을 따로 추출**한다.

## 초안 생성 시 반드시 지키는 것

- **To 헤더가 비면 `HttpError 400 "Invalid To header"`로 초안 생성 자체가
  실패한다.** `undisclosed-recipients:;`로도 안 된다. 수신자 이메일을 못 찾은
  업체는 `users().getProfile(userId="me")`의 본인 주소로 To를 채운다.
  대신 **본문 상단에 `[수신자 미상]` 경로를 눈에 띄게 넣고**, 최종 보고에서
  "발송 전 To 지정 필요"로 명시한다. 주소를 지어내지 않는다.
- **HTML + plain-text 병행**: `msg.set_content(plain)` +
  `msg.add_alternative(html, subtype="html")`. 품목표가 들어가면 어느
  클라이언트에서 열어도 깨지지 않아야 한다.
- **중복 초안 정리**: 부분 실패 후 재시도하면 같은 제목·To의 초안이 남는다.
  생성 직후 `users().drafts().list()`로 확인하고 `drafts().delete()`로 정리.
- **임의 값 금지**: 품목 추출이 안 됐으면 초안을 만들지 않는다. 비워둔 채
  사용자에게 낼 판단을 넘긴다.

## 판독 시 자주 어긋나는 것

- **도장 연도**: 인쇄 발행일(2026)과 보라색 스탬프 필기(`25. 8. 18`)가
  1년 어긋나는 사례가 반복된다. 임의로 같게 만들지 말고 불일치를 그대로
  보고한다.
- **파일명과 다른 품목**: `20260818_Target-G..._거래명세서.pdf` 안에 렌즈
  (Nikon/ Kenko)가 들어 있는 사례가 있었다. 페이지별 업체·품목을 믿고
  별도 업체 후보로 분리해 확인받는다.
- **품목코드에 정보가 몰려 있음**: `C57BL/6NCrlOri_4w_F` = 계통/주령/성별.
  제조사·Cat.No 열이 없는 문서에서는 추정임을 표시하고 원문을 보존한다.
- **`단가` 열이 비어 있고 금액만 채워진** 문서가 있다. 표 맨 아래 합계와
  행별 금액을 대조해 어느 열인지 확인한다.

## 검증

```python
r = svc.users().drafts().list(userId="me", maxResults=30).execute()
for d in r.get("drafts", []):
    m = svc.users().messages().get(userId="me", id=d["message"]["id"],
        format="metadata", metadataHeaders=["To", "Subject"]).execute()
    h = {x["name"]: x["value"] for x in m["payload"]["headers"]}
    print(d["id"], "|", h.get("Subject", ""), "|", h.get("To", ""))
```

성공 보고에는 **실제 생성 개수·수신자·품목 수·합계**를 포함하고, 수신자
미상 건은 별도로 명시한다.
