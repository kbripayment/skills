# Gmail 초안 첨부 — 용량 한도와 안전한 재검색/검증

`gmail.users().drafts().create(userId="me", body={"message": {}}, media_body=MediaIoBaseUpload(...))`는
메시지 본문 전체(첨부 포함)를 단일 업로드로 보낸다. 한도는 36,700,160 바이트이며, 넘으면
`googleapiclient.errors.MediaUploadSizeError: Media larger than: 36700160`으로 죽는다. 첨부 크기를
미리 알면 Vision/OCR 파이프라인을 돌릴 필요가 없다 — 파일 크기만 확인하고 처리한다.

## 1. 첨부 크기로 먼저 판단하기
`os.path.getsize()`로 폴더 루트의 각 PDF 크기를 나열한다. 검수사진 PDF가 수십 MB인 것이 흔하다.
합계가 한도 근처면 다음 중 하나를 적용한다.

## 2. 검수사진 PDF 재압축 (원본 보존, 첨부용 사본만 압축)
PyMuPDF `doc.extract_image(xref)`로 원본 이미지 바이트를 꺼내 PIL로 JPEG(q=84, optimize) 재인코딩 후
`page.replace_image(xref, stream=jpeg_bytes)`로 되돌린다. 저장 시 `doc.save(out, garbage=4, deflate=True,
deflate_images=True)`. 페이지 수와 `page.rect`가 유지되는지 반드시 재열기해 검증한다.

- 원본 `Y:\` 파일은 절대 덮어쓰지 않는다. 압축본은 임시 폴더에 두고, 첨부 시 **압축본 경로 + 원본 파일명**을
  넘겨야 메일에 붙는 이름이 원본과 같게 보인다.
- 실측 축소폭은 이미지마다 다르다(4128×3096 JPEG는 대략 20~25% 감소). 한도를 여전히 넘으면 DPI를 낮추거나
  JPEG 품질을 더 낮춰 재압축한다. 그래도 안 되면 첨부 대신 Drive 링크를 본문에 넣고 사용자에게 확인받는다.

## 3. 중복 초안 검사 — `q` 검색을 믿지 말 것
`drafts.list(q='subject:"..."')`는 RFC 2047 인코딩된 한글 제목에서 매칭을 놓쳐 빈 결과를 준다(실측).
`drafts.list()`을 `pageToken`으로 끝까지 돌려 각 초안의 헤더를 직접 읽고, 제목을 디코딩해 비교한다.

## 4. drafts.get() 인자 함정
`gmail.users().drafts().get(..., metadataHeaders=[...])`는 `TypeError: Got an unexpected keyword argument
metadataHeaders`. `format="full"`(또는 `"metadata"`)만 가능하다. 헤더 필터가 필요하면 `format="full"`로 받은 뒤
`payload["headers"]`에서 직접 `{name.lower(): value}` 딕셔너리를 만든다.

## 5. read-back 검증
초안 생성 직후 `drafts.get(format="full")`로 수신자·제목·첨부 파일명 목록을 다시 읽어 기대값과 비교한다.
불일치하면 스크립트를 실패로 끝낸다 — 성공을 보고하지 않는다.

## 6. 산출물 스코프 규칙
이메일 작성 자동화에서 발송은 하지 않는다. 초안만 만들고, 시트 기안일/지급상태 갱신은 초안 생성
성공에 확인된 경우에만 수행한다. 확인 못 한 건(예: OCR이 빈 결과인 세금계산서)은 보고서에서 제외하고
어떤 건이 왜 빠졌는지 한 줄로 밝힌다.
