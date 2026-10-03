---
name: html-pin-protected-viewer
description: Hometax/CERI 보안메일 HTML을 PIN 인증해 실제 세금계산서 PDF로 변환·추출하거나, 반대로 PDF를 PIN 뷰어로 감쌀 때.
---

# Hometax CERI 보안메일 — PIN 인증 PDF 변환 & PIN 보호 뷰어

두 방향을 다룬다.

- **추출(본문)**: 홈택스 보안메일 HTML 첨부 → PIN 인증 → 실제 전자세금계산서 PDF로 저장
- **감싸기(뒤 절반)**: 이미 확보한 PDF를 PIN 입력 iframe 뷰어로 제공

## When to use
- 홈택스(국세청) 전자세금계산서 보안 메일 HTML 첨부파일이 `NTS_eTaxInvoice.html` 형태로 왔을 때
- 그 HTML을 열었더니 "보안메일 비밀번호 인증창"만 보이고 금액·품목이 전혀 없을 때
- 홈택스 HTML을 `printToPDF`로 뽑았는데 인증창만 인쇄돼 실문서가 안 나올 때
- `statement_pdf_inspector.py` 스크립트에서 `--pin-protect` 옵션으로 뷰어를 만들 때

## Pattern
```html
<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>#viewer{{width:100%;height:100vh;display:none}}
.overlay{{position:fixed;top:0;left:0;width:100%;height:100%;background:#000;z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}}</style>
</head><body>
<iframe id="viewer" src="문서.pdf"></iframe>
<div class="overlay" id="overlay">
  <input type="password" id="pin" maxlength="10" autocomplete="one-time-code">
  <button onclick="go()">확인</button>
</div>
<script>const PIN="5148280611";
document.getElementById('pin').addEventListener('keyup',e=>{if(e.key==='Enter')go();}});
function go(){{const v=document.getElementById('pin').value;
 if(v===PIN){{document.getElementById('overlay').style.display='none';document.getElementById('viewer').style.display='block';}}
 else{{alert('잘못된 PIN입니다.');document.getElementById('pin').value='';document.getElementById('pin').focus();}}}}
document.getElementById('pin').focus();</script>
</body></html>
```

## Script integration
```bash
python statement_pdf_inspector.py --folder Y:\\ --pattern "*거래명세서.pdf" --pin-protect
python statement_pdf_inspector.py --folder Y:\\ --pattern "*거래명세서.pdf" --pin-off
```

전체 추출 절차(CDP 기동, 인증, 캡처, 검증)는 `references/ceri-pdf-extraction.md` 참고.

전자세금계산서를 확보한 **이후의 지급신청 단계**(시트 매칭 검증·기안일 기록·초안 생성)는
`references/payment-claim-verification.md` 참고. 핵심: `apply_payment_skill.py`는 자동화일
뿐 최종 판단은 사람이 하므로 `--dry-run` 로그의 행합계·매칭 방식을 읽고, 시트 행을
**금액으로 독립 대조**한 뒤에 실실행한다.

## Reuse before re-deriving

이 절차(CDP 기동 → PIN 인증 → iframe 캡처 → 교차검증)는 이미 스크립트로 구현돼 있다. **CDP/PIN 흐름을 직접 다시 만들지 말고 그것을 쓸 것.**

`automation` 스킬의 `scripts/hometax_export.py`가 하는 일: PIN 입력 → `Page.printToPDF` → iframe/PDF 양쪽에서 승인번호·공급자·공급가액·세액·합계금액·작성일자·품목명 추출 → 거래명세서 기준과 **4조건(공급자·금액·품목·승인번호) 교차검증** → 통과분만 정상 파일명으로 저장. 회귀는 `--selftest`.

```bash
python scripts/hometax_export.py --pin "<PIN>"
python scripts/hometax_export.py --pair "거래명세서stem=홈택스.html"   # 기대값 연결
python scripts/hometax_export.py --selftest
```

**Gmail 메시지 ID로 저장한 홈택스 HTML은 파일명만으로 거래명세서를 알 수 없다.** 그래서 기대값 조립이 `기준=missing` 으로 끝나 검증 없이 저장된다. `--pair "거래명세서stem=홈택스.html"` 로 명시적으로 연결하거나 `--expect-json` 으로 기대값을 직접 준다.

## Pitfalls
- **보안메일 HTML은 문서가 아니라 암호문 컨테이너다.** 헤더·본문 텍스트를 뽑거나 headless로 `--print-to-pdf`를 돌리면 "보안메일 비밀번호 인증창"만 인쇄된다(금액·품목 0자). 복호화 키는 국세청 서버가 withhold하므로 로컬 파싱으로는 열 수 없다.
- **PIN은 `InputPwd()`를 호출해야 한다.** 버튼 클릭이나 Enter 이벤트만 재현하지 말고 `document.getElementById('idPcPwd').value = PIN` 후 `InputPwd()`를 직접 부른다. 성공하면 본문 텍스트가 `인쇄 / 첨부보기`로 바뀌고 iframe(`#CriMsgPosition`)에 세금계산서가 렌더된다.
- **인증 전 로드를 기다려라.** `document.readyState`만 보지 말고 `InitRun`/`InputPwd` 함수가 `typeof === 'function'`인지 확인한 뒤 PIN을 넣는다. 스크립트가 `defer` 로드라 즉시 넣으면 인증이 조용히 실패한다.
- **PDF는 iframe가 아니라 바깥 탭에서 인쇄한다.** `Page.printToPDF`는 최상위 문서를 인쇄하므로 인증 전에는 인증창만 나온다. 인증 후 iframe 렌더가 끝난 상태에서 캡처한다.
- **같은 홈택스 메일을 두 거래명세서에 붙이지 말 것.** 메일 1건 = 세금계산서 1장이므로, 발신자가 같다고 여러 건에 재사용하면 다른 거래명세서 내용이 복제된다. **hidden input(`idCriPcContents`)을 SHA-256으로 해싱해 동일 여부를 먼저 확인**하고, 추출 후 PDF 텍스트의 공급자·품목·금액이 대상 거래명세서와 일치하는지 대조한다.
- **“성공 N건” 집계는 정답 개수가 아니다.** 본문 문자열이 존재하기만 하면 통과하므로 복제본도 OK로 집계된다(승인번호가 동일한 다른 건의 PDF가 ‘성공’으로 세어진 사례가 있다). **실행 결과 전체의 승인번호 중복을 반드시 검사**하고, 승인번호·공급자·합계·품목을 거래명세서 기준정보와 대조한 뒤에만 정상 파일명으로 저장한다. 상세 절차는 `references/ceri-pdf-extraction.md`의 교차검증 루프 참고.
- **세금을 임의로 계산하지 말 것.** 일부 전자계산서는 부가세 세액을 별도 표기하지 않고 합계만 적는다(공급가액=합계금액). 기본 10%를 얹어 제목·본문 금액을 만들면 문서와 어긋난다. **세금계산서에 적힌 합계금액을 그대로 사용**하고, 세액 표기가 없음을 본문에 한 줄 밝혀 둔다.
- **4종 세트의 검수 파일명은 두 가지다.** `_검수사진.pdf` 와 `_검수.pdf` 가 실제로 섞여 있다. 붙는 쪽이 정해져 있지 않으므로 찾을 때는 두 접미사를 모두 본다. 한쪽만 찾으면 세트가 불완전하다고 오판해 지급신청 단계가 진행되지 않는다.
- **지급신청 본문을 늘리지 말 것.** 본문은 `안녕하세요, 연구지원부의 홍길동입니다.` / `첨부 화일의 건에 대해 지급신청을 요청드립니다.` / `감사합니다.` / `홍길동 드림` 4행, plain-text 단독이다. 품목 표·총액·시트 행·첨부 목록을 본문에 반복하면 안 된다 — 제목과 첨부에 이미 있고, 지급신청은 회신 절차가 없어 그 정보가 필요하지 않다.
- HTML과 PDF가 같은 폴더에 있어야 iframe이 작동합니다
- Electron 앱에서 prompt()는 불안정 → JS overlay 방식 사용
- PIN 하드코딩은 보안에 취약 → 환경 변수로 분리 권장
