# stale `__pycache__`로 인한 `graphical_abstract` TypeError

**증상:** `SummaryResult.__init__() got an unexpected keyword argument 'graphical_abstract'` 또는 `PaperWithSummary.__init__() got an unexpected keyword argument 'graphical_abstract'`

**원인:** `local_llm_summarize.py`와 `slack_research_notifier.py`의 dataclass(`SummaryResult`, `PaperWithSummary`)에서 Vision LLM 관련 필드(`graphical_abstract`)가 코드상 제거되었지만, **컴파일된 `.pyc` 캐시가 구버전 정의를 기억하고 있어** 오래된 시그니처로 실행됨.

- 소스 코드에는 `graphical_abstract` 인자가 nowhere에 없음 (grep으로 확인됨)
- 동일한 소스 코드로 실행했는데도 어떤 때는 성공, 어떤 때는 실패 → pycache 불일치
- `inspect.getsource()`로 확인한 live 소스에는 해당 필드/인자 없음

**해결:**
```bash
# scripts/__pycache__ 전체 삭제 후 재실행
rm -rf C:/Users/user/AppData/Local/hermes/skills/research/research_new/scripts/__pycache__
```

**예방:**
- `research_pipeline.py` 실행 전에 `scripts/__pycache__/`가 존재하는지 확인하고 정리
- 코드 변경 후 재실행 시 pycache 정리 습관화
- 핵심 데이터 클래스(dataclass) 시그니처 변경 시 `__pycache__` 정리가 필수

**발생 이력:**
- 2026-08-26 16:22:28 첫 실행 → 1/12 요약 단계에서 TypeError
- 2026-08-26 11:37 동일 조건 성공 (pycache clean 상태였음)
- 2026-08-26 pycache 정리 후 재실행 → 정상 진행 확인

**참조:** `local_llm_summarize.py:156` (SummaryResult 정의), `slack_research_notifier.py:59` (PaperWithSummary 정의)
