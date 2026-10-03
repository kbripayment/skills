# 홈택스 보안메일 HTML → 전자세금계산서 PDF 추출

보안메일 HTML에서 실제 세금계산서를 꺼내는 절차. 브라우저(CDP)를 직접 띄워 PIN 인증을 재현하고 `printToPDF`로 캡처한다.

## 내부 구조

| 요소 | 역할 |
|---|---|
| `<script src=srtk.hometax.go.kr/.../aes.js,md5.js,enc-cp949-min.js,cri_ems_nt.js>` | 복호화 + 국세청 인증 통신 |
| `input#idCriPcContents`, `#idCriMobileContents`, `#idCriHeader`, `#idCriAttachContents0` (hidden) | Base64 암호문 |
| `input#idPcPwd`, `#idMobilePwd` (password) | PIN 입력 |
| `iframe#CriMsgPosition` | 인증 성공 후 세금계산서 렌더 위치 |

복호화 키는 국세청 서버가 withhold하므로 로컬에서는 열 수 없다.

## 절차

### 1. Chrome을 원격 디버깅으로 띄운다
```bash
"C:/Program Files/Google/Chrome/Application/chrome.exe" \
  --remote-debugging-port=9333 \
  --user-data-dir="C:/Users/user/AppData/Local/Temp/chrome_hometax" \
  --no-first-run --no-default-browser-check about:blank
```
헬스체크: `requests.get("http://127.0.0.1:9333/json/version")` → 200.

`browser_exec` harness는 `DevToolsActivePort`를 못 찾아 기동에 실패할 수 있다. CDP 포트를 직접 열어 `websockets`로 제어하는 경로가 확실하다.

### 2. 탭 열기
```python
url = "file:///" + path.replace("\\", "/")   # 공백은 %20 인코딩
tab = requests.put(f"{CDP}/json/new?{requests.utils.quote(url)}", timeout=10).json()
ws = tab["webSocketDebuggerUrl"]
```

### 3. 로드 대기 → PIN 인증
```python
await cdp("Page.enable"); await cdp("Runtime.enable")
await cdp("Page.reload", {"ignoreCache": True})
await asyncio.sleep(8)
# 스크립트가 defer 로드되므로 함수 존재를 확인한 뒤 진행
await ev("typeof InputPwd")                      # 'function' 이어야 함
await ev("document.getElementById('idPcPwd').value = '5148280611'")
await ev("InputPwd()")
await asyncio.sleep(12)
```

### 4. 인증 성공 판정 (인증만 확인한다)

```python
text = await ev("(()=>{const f=document.getElementById('CriMsgPosition');"
                "return f&&f.contentDocument?f.contentDocument.body.innerText:document.body.innerText;})()")
authenticated = "인쇄" in text and "첨부보기" in text   # 뷰어가 열린 상태
```
본문이 `인쇄  첨부보기`로 바뀌면 인증은 성공했다. 이때 iframe에 승인번호·공급자·품목·합계가 나온다.

**이 판정은 ‘인증 성공’일 뿐 ‘정답’ 판정이 아니다.** 본문 문자열이 존재하기만 하면 통과하므로, 다른 건의 문서가 복제되어 있어도 OK로 나온다(실제로 승인번호까지 동일한 타 건의 PDF가 ‘성공’으로 집계된 사례가 있다). 정답 여부는 6절의 교차검증에서 판정한다.

### 5. PDF 캡처
```python
await cdp("Emulation.setDeviceMetricsOverride",
          {"width":1240,"height":1754,"deviceScaleFactor":1,"mobile":False})
r = await cdp("Page.printToPDF", {"printBackground": True,
      "paperWidth":8.27, "paperHeight":11.69,   # A4
      "marginTop":0.3,"marginBottom":0.3,"marginLeft":0.3,"marginRight":0.3})
open(out, "wb").write(base64.b64decode(r["result"]["data"]))
```

## 반드시 지킬 검증 두 가지

1. **중복 메일 배제**: 추출 전 원본 HTML들의 `idCriPcContents` 값을 SHA-256으로 해싱해 서로 같은지 확인한다. 같으면 같은 메일이며, 서로 다른 거래명세서에 재사용하면 다른 건의 PDF가 복제된다.
2. **내용 대조**: 추출 PDF의 텍스트에서 공급자·품목·금액을 뽑아 대상 거래명세서와 대조한다. 승인번호(예 `20261001-10261001-83988297`)가 문서 식별자다.

## 교차검증 루프 (추출기가 반드시 지켜야 한다)

인증 판정과 정답 판정을 분리한다. 추출기는 **거래명세서 기준정보를 입력으로 받아** 아래를 대조하고, 하나라도 어긋나면 정상 파일명으로 저장하지 않는다.

- **공급자**: 부분 일치 허용 (`주식회사 OO` ↔ `(주)OO`)
- **합계**: 세금계산서 합계금액 vs 거래명세서 공급가액 (±1원 또는 천원 단위 반올림)
- **품목**: 거래명세서 품목명이 세금계산서 품목에 존재 (공백 제거 후 부분 문자열)
- **승인번호**: 파싱 성공

실패 시에는 `{stem}_전자세금계산서.미검증.pdf`처럼 **성공 산출물과 구분되는 이름**으로 저장하거나 아예 저장하지 않는다.

**실행 결과 전체의 승인번호를 모아 중복을 검사한다.** 같은 승인번호가 2건 이상 나오면 그것은 한 메일이 여러 거래명세서에 매핑됐다는 뜻이므로, 해당 건을 전부 실패로 후퇴시키고 파일명도 강등한다. 개별 건의 대조가 통과해도 이 검사 없이는 복제를 못 잡는다.

기준정보를 정적 dict로만 하드코딩하면 거래명세서가 추가·변경될 때 검증이 조용히 무효가 되므로, **대상 거래명세서 PDF(또는 그 구조화 JSON)에서 기대값을 런타임에 읽어 조립**한다.

## 치명적 실패 모드

- headless/Edge `--print-to-pdf`만 돌리면 "보안메일 비밀번호 인증창"만 인쇄된다(금액 0자).
- 인증 없이 `printToPDF`를 부르면 같은 결과. **반드시 PIN 인증 완료 후** 캡처한다.