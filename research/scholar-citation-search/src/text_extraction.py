#!/usr/bin/env python3
"""
논문 텍스트 추출 + 유사 전개 LLM 필터링 — SKILL.md v1.2.0 Step ⑤

입력:  PDF 경로 or raw text (paper_acquisition.py 출력)
출력:  filtered_passages[] (score 포함, research_question 기준 유사도 필터링)

필요 의존성 (가상환경 또는 pip):
    pip install pymupdf pdfplumber

LLM 필터는 HTTP POST로 외부 LLM API를 호출합니다.
호출 구조만 잡아두고, 실제 API 키는 ~/.hermes/.env 의 LLM_API_KEY 에서 읽습니다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

# ── PDF 추출 ─────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """
    PDF 파일에서 텍스트 추출. PyMuPDF 우선, pdfplumber 폴백.

    Args:
        pdf_path: PDF 파일 경로

    Returns:
        추출된 텍스트 (공백 정제됨)
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 파일 없음: {pdf_path}")

    text = ""

    # PyMuPDF (fitz) 시도
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(pdf_path))
        chunks = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text("text")
            if page_text.strip():
                chunks.append(page_text)
        doc.close()
        text = "\n".join(chunks)
    except ImportError:
        pass  # pdfplumber 폴백

    # pdfplumber 폴백
    if not text.strip():
        try:
            import pdfplumber

            with pdfplumber.open(str(pdf_path)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        text += page_text + "\n"
        except ImportError:
            raise RuntimeError(
                "PyMuPDF도 pdfplumber도 설치되어 있지 않습니다.\n"
                "pip install pymupdf pdfplumber 을 실행하세요."
            )

    return _normalize_whitespace(text)


def extract_text_from_text_file(text_path: str | Path) -> str:
    """이미 추출된 텍스트 파일(.txt)을 읽어 반환."""
    return _normalize_whitespace(Path(text_path).read_text(encoding="utf-8", errors="replace"))


# ── 섹션 분절 ────────────────────────────────────────────────────────

SECTION_HEADERS = {
    "abstract": r"(?i)^\s*(abstract|요약)\s*$",
    "introduction": r"(?i)^\s*(1\.?\s*)?(introduction|서론|서\s*론)\s*$",
    "related": r"(?i)^\s*(2\.?\s*)?(related\s*(work|studies|papers)|관련\s*(연구|연구동향))\s*$",
    "background": r"(?i)^\s*(background|연구\s*배경)\s*$",
    "method": r"(?i)^\s*(3\.?\s*)?(method|methods?|방법론?|experimental?\s*(setup|setting)?)\s*$",
    "experiment": r"(?i)^\s*(4\.?\s*)?(experiment|experimental?\s*result|실험|결과)\s*$",
    "result": r"(?i)^\s*(4\.?\s*)?(result|results?\s*and\s*discussion|result\s*and\s*discussion|결과\s*및\s*토론)\s*$",
    "discussion": r"(?i)^\s*(5\.?\s*)?(discussion|토론|Discussion)\s*$",
    "conclusion": r"(?i)^\s*(6\.?\s*)?(conclusion|conclusions?|요약\s*결론|결론)\s*$",
    "reference": r"(?i)^\s*(reference|references|참\s*고\s*문\s*헌)\s*$",
}


def split_sections(text: str) -> dict[str, str]:
    """
    논문 텍스트를 섹션별로 분절.

    Returns:
        {"abstract": "...", "introduction": "...", ...}
        매칭되지 않은 텹스트는 "unmatched" 키에 수집.
    """
    lines = text.split("\n")
    sections: dict[str, list[str]] = {k: [] for k in list(SECTION_HEADERS.keys()) + ["unmatched"]}
    current_section = "unmatched"

    for line in lines:
        matched = False
        for sec_name, pattern in SECTION_HEADERS.items():
            if re.match(pattern, line.strip()):
                current_section = sec_name
                matched = True
                break
        sections[current_section].append(line)

    result = {}
    for sec_name, lines_list in sections.items():
        joined = _normalize_whitespace("\n".join(lines_list))
        if joined.strip():
            result[sec_name] = joined

    return result


def get_priority_sections(sections: dict[str, str]) -> list[tuple[str, str]]:
    """
    필터링 시 우선순위가 높은 섹션 반환 (abst/intro/method/results/discussion/conclusion).
    """
    priority = ["abstract", "introduction", "method", "result", "discussion", "conclusion"]
    result = []
    for key in priority:
        if key in sections:
            result.append((key, sections[key]))
    return result


# ── LLM 유사도 필터 ─────────────────────────────────────────────────

DEFAULT_LLM_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_LLM_MODEL = "auto/best-reasoning"


def _resolve_api_url(api_url: str | None = None) -> str:
    """LLM API URL 결정: 인자 > ~/.hermes/.env LLM_API_URL > 기본값(OpenAI)."""
    return api_url or _load_env("LLM_API_URL") or DEFAULT_LLM_URL


def _is_reasoning_model(model: str) -> bool:
    """reasoning 계열 모델 여부 (temperature 미지원 대비)."""
    m = (model or "").lower()
    return ("reasoning" in m or "thinking" in m
            or m.startswith(("o1", "o3", "o4")))


def _chat_post(api_url: str, api_key: str, payload: dict, timeout: float) -> str:
    """Chat Completions POST 후 원시 body 텍스트 반환."""
    import urllib.request

    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_chat_content(body: str) -> str:
    """
    Chat Completions 응답 파싱 (단일 JSON + SSE 스트리밍 양립).
    - 단일 JSON: choices[0].message.content
    - SSE: `data:` 라인 누적 → delta.content 결합 → `[DONE]` 종료.
    실패 시 ValueError.
    """
    text = (body or "").strip()
    if not text:
        raise ValueError("빈 응답 body")
    if not text.startswith("data:"):
        data = json.loads(text)
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {}) or {}
            if isinstance(delta.get("content"), str):
                parts.append(delta["content"])
            msg = choice.get("message", {}) or {}
            if isinstance(msg.get("content"), str):
                parts.append(msg["content"])
    return "".join(parts)


def similarity_filter(
    text: str,
    research_question: str,
    *,
    api_url: str | None = None,
    api_key: str | None = None,
    model: str = DEFAULT_LLM_MODEL,
    section_name: str = "unknown",
    timeout: float = 30.0,
) -> float | None:
    """
    논문 단락(text)이 연구 질문(research_question)과 얼마나 관련 있는지
    LLM에 판단을 요청하여 0.0~1.0 점수를 반환.

    Args:
        text: 평가할 텍스트 (500단어 이하로 자름)
        research_question: 원본 연구 질문
        api_url: LLM API URL (None이면 env LLM_API_URL → DEFAULT_LLM_URL 순으로 해석)
        api_key: API 키 (None이면 ~/.hermes/.env 의 LLM_API_KEY)
        model: 사용할 모델
        section_name: 섹션 이름 (로그용)
        timeout: HTTP 타임아웃(초)

    Returns:
        0.0~1.0 사이 유사도 점수. LLM 호출 실패 시 None.
    """
    # API 키 결정
    api_key = api_key or _load_env("LLM_API_KEY")
    if not api_key:
        # LLM_API_KEY 없으면 키워드 기반 폴백 점수 반환
        return _keyword_similarity_fallback(text, research_question)

    api_url = _resolve_api_url(api_url)

    # 텍스트 길이 제한 (토큰 절약)
    truncated = _truncate_text(text, max_words=400)

    system_prompt = (
        "You are a research relevance scorer. "
        "Given a research question and a passage from an academic paper, "
        "rate how relevant the passage is to answering the research question. "
        "Respond ONLY with a single float between 0.0 (completely irrelevant) and 1.0 (directly relevant). "
        "Consider: does the passage discuss concepts, methods, datasets, or findings "
        "that help address the research question?"
    )

    user_prompt = f"""Research Question: {research_question}

Passage (section: {section_name}):
{truncated}

Relevance score (0.0 to 1.0):"""

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 1000,  # reasoning 모델 추론 여유 (상한일 뿐 실제 과금 아님)
        "stream": False,
    }
    if not _is_reasoning_model(model):
        payload["temperature"] = 0.0

    try:
        body = _chat_post(api_url, api_key, payload, timeout)
        content = _parse_chat_content(body)
        # 숫자 추출 (추론 과정 숫자가 섞일 수 있어 마지막 float 우선)
        matches = re.findall(r"0?\.\d+|1\.0+", content.strip())
        if matches:
            score = float(matches[-1])
            return max(0.0, min(1.0, score))
        return None
    except Exception as e:
        print(f"[相似度 필터 오류] {e}", file=sys.stderr)
        # 폴백: 키워드 기반 점수
        return _keyword_similarity_fallback(text, research_question)


def _keyword_similarity_fallback(text: str, research_question: str) -> float:
    """
    LLM_API_KEY가 없거나 API 호출 실패 시, 키워드 오버랩 기반 유사도 폴백.
    0.0~0.5 사이 점수만 반환 (LLM 대비 보수적).
    """
    text_lower = text.lower()
    rq_lower = research_question.lower()

    # 단어 토큰화
    rq_words = set(re.findall(r"\b\w{3,}\b", rq_lower))
    text_words = set(re.findall(r"\b\w{3,}\b", text_lower))

    if not rq_words:
        return 0.0

    overlap = rq_words & text_words
    score = len(overlap) / len(rq_words)
    return min(score * 0.5, 0.5)  # 최대 0.5로 제한


# ── RQ 3-class 분류 + 방법론 유사도 + TF-IDF (plans_citation.md Step ⑤) ──

_RQ_CLASSES = ("same", "related", "unrelated")
_METHOD_SIMS = ("high", "medium", "low")
_CONFIDENCES = ("high", "medium", "low")


def _token_set(text: str) -> set[str]:
    """3자 이상 단어 토큰 집합 (Jaccard/TF-IDF 폴백 공용)."""
    return set(re.findall(r"\b\w{3,}\b", (text or "").lower()))


def method_jaccard(chunk: str, research_question: str) -> float:
    """
    방법론 키워드 Jaccard 유사도. 스펙 임계값 ≥0.3 (high/medium 통과).
    매핑: ≥0.5 → high, ≥0.3 → medium, 그 외 → low.
    """
    a, b = _token_set(chunk), _token_set(research_question)
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 3)


def compute_tfidf_similarity(text1: str, text2: str) -> float:
    """
    TF-IDF cosine 보조 지표 (스펙 ≥0.35).
    sklearn이 있으면 TF-IDF 사용, 없으면 토큰 Jaccard로 폴백.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        vec = TfidfVectorizer(stop_words="english", max_features=1000)
        tfidf = vec.fit_transform([text1 or "", text2 or ""])
        return round(float((tfidf[0] @ tfidf[1].T).toarray()[0, 0]), 3)
    except Exception:
        a, b = _token_set(text1), _token_set(text2)
        if not a or not b:
            return 0.0
        return round(len(a & b) / len(a | b), 3)


def _classify_heuristic(candidate_text: str, original_rq: str) -> dict[str, Any]:
    """
    LLM_API_KEY가 없을 때의 결정적 휴리스틱 분류.
    related 판정은 confidence=low로 두어 human_review 큐로 유도 (스펙 보수 원칙).
    """
    rq_words = _token_set(original_rq)
    c_words = _token_set(candidate_text)
    overlap_ratio = (len(rq_words & c_words) / len(rq_words)) if rq_words else 0.0
    j = method_jaccard(candidate_text, original_rq)
    method = "high" if j >= 0.5 else ("medium" if j >= 0.3 else "low")
    if overlap_ratio >= 0.5 and method in ("high", "medium"):
        rq_class, confidence = "same", "medium"
    elif overlap_ratio >= 0.25:
        rq_class, confidence = "related", "low"
    else:
        rq_class, confidence = "unrelated", "medium"
    return {
        "rq_class": rq_class,
        "method_similarity": method,
        "confidence": confidence,
        "reason": f"heuristic: overlap={overlap_ratio:.2f}, jaccard={j:.2f} (LLM_API_KEY 없음)",
    }


def _classify_via_llm(
    candidate_text: str,
    original_rq: str,
    *,
    api_key: str,
    model: str = DEFAULT_LLM_MODEL,
    api_url: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """스펙 Q1-Q3 프롬프트로 LLM에 JSON 분류 요청. 파싱 실패 시 예외."""
    import urllib.request

    url = _resolve_api_url(api_url)
    prompt = (
        f'원본 RQ: "{original_rq}"\n'
        f'후보 abstract+intro: "{_truncate_text(candidate_text, max_words=800)}"\n'
        'Q1: 동일한 연구 질문인가? (same/related/unrelated)\n'
        'Q2: 방법론 유사도? (high/medium/low)\n'
        'Q3: 비슷한 전개로 볼 수 있는가? (yes/no + 1줄 근거)\n'
        'JSON으로만 응답: {"rq_class": "...", "method_similarity": "...", '
        '"verdict": "...", "reason": "...", "confidence": "high|medium|low"}'
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,  # reasoning 모델 추론 여유
        "stream": False,
    }
    if not _is_reasoning_model(model):
        payload["temperature"] = 0.0
    body = _chat_post(url, api_key, payload, timeout)
    content = _parse_chat_content(body)
    m = re.search(r"\{.*\}", content.strip(), re.DOTALL)
    if not m:
        raise ValueError(f"LLM 분류 JSON 파싱 실패: {content[:100]}")
    parsed = json.loads(m.group(0))
    rq_class = str(parsed.get("rq_class", "")).strip().lower()
    method = str(parsed.get("method_similarity", "")).strip().lower()
    confidence = str(parsed.get("confidence", "")).strip().lower()
    if rq_class not in _RQ_CLASSES or method not in _METHOD_SIMS or confidence not in _CONFIDENCES:
        raise ValueError(f"LLM 분류 enum 범위 이탈: {parsed}")
    return {
        "rq_class": rq_class,
        "method_similarity": method,
        "confidence": confidence,
        "reason": str(parsed.get("reason", ""))[:300],
    }


def classify_rq_similarity(
    candidate_text: str,
    original_rq: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_LLM_MODEL,
    api_url: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """
    RQ 3-class 분류 진입점.
    Returns: {rq_class, method_similarity, confidence, reason}.
    LLM 키가 없거나 호출 실패 시 휴리스틱으로 폴백 (결정적, 오프라인 동작).
    """
    key = api_key or _load_env("LLM_API_KEY")
    if key:
        try:
            return _classify_via_llm(
                candidate_text, original_rq,
                api_key=key, model=model, api_url=api_url, timeout=timeout,
            )
        except Exception as e:
            print(f"[RQ 분류 LLM 실패 → 휴리스틱]: {e}", file=sys.stderr)
    return _classify_heuristic(candidate_text, original_rq)


def decide_verdict(
    rq_class: str,
    method_similarity: str,
    score: float,
    tfidf_score: float | None,
    threshold: float = 0.40,
    confidence: str = "medium",
) -> str:
    """
    최종 판정: kept | filtered_out | needs_human_review.
    - unrelated → filtered_out (confidence 무관)
    - confidence low → needs_human_review (자동 탈락 금지, 스펙 재현성 규칙)
    - method low → filtered_out
    - same + (score≥thr 또는 tfidf≥0.35) → kept
    - related + score≥thr → kept, 그 외 → needs_human_review
      (related 상위 50% 근사: threshold 통과분을 상위로 간주)
    """
    rq = rq_class if rq_class in _RQ_CLASSES else "related"
    if rq == "unrelated":
        return "filtered_out"
    if confidence == "low":
        return "needs_human_review"
    if method_similarity not in ("high", "medium"):
        return "filtered_out"
    tfidf = tfidf_score or 0.0
    if rq == "same" and (score >= threshold or tfidf >= 0.35):
        return "kept"
    if rq == "related" and score >= threshold:
        return "kept"
    return "needs_human_review"


# ── 유사 전개 필터링 (메인) ─────────────────────────────────────────

def filter_by_rq(
    text_or_path: str | Path,
    research_question: str,
    *,
    threshold: float = 0.40,
    max_passages: int = 10,
    api_url: str | None = None,
    api_key: str | None = None,
    model: str = DEFAULT_LLM_MODEL,
    include_review: bool = False,
) -> list[dict[str, Any]]:
    """
    논문 텍스트를 연구 질문 기준으로 필터링.

    Args:
        text_or_path: PDF 경로 또는 원본 텍스트 문자열 (.pdf 확장자면 PDF로 처리)
        research_question: 유사 판별 기준이 될 연구 질문
        threshold: 이 점수 이상인 passage만 통과 (기본 0.40)
        max_passages: 최대 반환 passage 수 (kept/review 각 리스트에 적용)
        api_url / api_key / model: LLM API 설정
        include_review: True면 needs_human_review 항목도 verdict와 함께 반환
            (False면 kept만 반환 — 기존 호출과 하위호환)

    Returns:
        [{"section", "text", "score", "sha256", "source_file",
          "rq_class", "method_similarity", "tfidf_score",
          "confidence", "filter_reason", "verdict"}, ...]
        kept 내림차순 정렬 (+ include_review 시 review 항목 뒤따름).
    """
    # 1) 텍스트 확보
    path = Path(text_or_path)
    if path.suffix.lower() == ".pdf":
        raw_text = extract_text_from_pdf(path)
        source_file = str(path)
    elif path.exists() and path.suffix.lower() == ".txt":
        raw_text = extract_text_from_text_file(path)
        source_file = str(path)
    else:
        raw_text = _normalize_whitespace(str(text_or_path))
        source_file = "inline"

    if not raw_text.strip():
        raise ValueError("추출된 텍스트가 비어 있습니다.")

    # 2) 섹션 분절
    sections = split_sections(raw_text)
    priority_sections = get_priority_sections(sections)

    # 3) 단락 분할 (500단어 단위)
    def chunk_text(text: str, max_words: int = 500) -> list[tuple[str, str]]:
        """(section_name, chunk_text) 리스트 반환"""
        paragraphs = re.split(r"\n\n+", text)
        chunks: list[tuple[str, str]] = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            words = para.split()
            if len(words) <= max_words:
                chunks.append(para)
            else:
                # 긴 단락을 다시 분할
                for i in range(0, len(words), max_words):
                    chunk = " ".join(words[i : i + max_words])
                    chunks.append(chunk)
        return chunks

    # 4) 각 청크에 대해 LLM 유사도 점수 + RQ 3-class 분류 산출
    scored: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []

    for sec_name, sec_text in priority_sections:
        chunks = chunk_text(sec_text)
        for chunk in chunks:
            score = similarity_filter(
                chunk,
                research_question,
                api_url=api_url,
                api_key=api_key,
                model=model,
                section_name=sec_name,
            )
            if score is None:
                continue
            cls = classify_rq_similarity(
                chunk, research_question,
                api_key=api_key, model=model, api_url=api_url,
            )
            tfidf = compute_tfidf_similarity(chunk, research_question)
            verdict = decide_verdict(
                cls["rq_class"], cls["method_similarity"],
                score, tfidf, threshold, cls["confidence"],
            )
            if verdict == "filtered_out":
                continue
            chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
            item = {
                "section": sec_name,
                "text": chunk,
                "score": round(score, 3),
                "sha256": chunk_hash,
                "source_file": source_file,
                "rq_class": cls["rq_class"],
                "method_similarity": cls["method_similarity"],
                "tfidf_score": round(tfidf, 3),
                "confidence": cls["confidence"],
                "filter_reason": cls["reason"],
                "verdict": verdict,
            }
            if verdict == "kept":
                scored.append(item)
            elif verdict == "needs_human_review" and include_review:
                review.append(item)

    # 5) 점수 내림차순 정렬 + 상위 max_passages 개만 반환
    scored.sort(key=lambda x: x["score"], reverse=True)
    result = scored[:max_passages]
    if include_review:
        review.sort(key=lambda x: x["score"], reverse=True)
        result = result + review[:max_passages]
    return result


# ── 유틸리티 ─────────────────────────────────────────────────────────

def _normalize_whitespace(text: str) -> str:
    """여러 공백을 단일 공백으로, 줄바꿈은 단일 공백으로."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _truncate_text(text: str, max_words: int = 400) -> str:
    """단어 수 기준 텍스트 자르기."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def _load_env(key: str) -> Optional[str]:
    """~/.hermes/.env 에서 키 조회 (UTF-16 LE BOM 대응)."""
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return None

    for enc in ("utf-8", "utf-16-le", "utf-16-be"):
        try:
            text = env_path.read_text(encoding=enc)
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    if k.strip() == key:
                        return v.strip().strip("\"'")
        except (UnicodeDecodeError, OSError):
            continue
    return None


# ── 테스트 ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="논문 텍스트 추출 + 유사 전개 필터링")
    parser.add_argument("--input", "-i", required=True, help="PDF 파일 경로 또는 .txt 파일")
    parser.add_argument("--rq", required=True, help="유사 판별 기준 연구 질문")
    parser.add_argument("--threshold", "-t", type=float, default=0.40, help="유사도 threshold (기본 0.40)")
    parser.add_argument("--max", "-m", type=int, default=10, help="최대 passage 수 (기본 10)")
    parser.add_argument("--model", default=DEFAULT_LLM_MODEL, help="LLM 모델")
    args = parser.parse_args()

    print(f"📄 텍스트 추출 중: {args.input}")
    print(f"🔍 연구 질문: {args.rq}")
    print(f"📊 threshold: {args.threshold}, max_passages: {args.max}")
    print()

    try:
        passages = filter_by_rq(
            args.input,
            args.rq,
            threshold=args.threshold,
            max_passages=args.max,
            model=args.model,
        )

        if not passages:
            print("⚠️  threshold 이상의 유사 passage 없음. threshold를 낮춰 보세요.")
            sys.exit(0)

        print(f"✅ {len(passages)}개 passage 필터링됨:\n")
        for i, p in enumerate(passages, 1):
            preview = p["text"][:200].replace("\n", " ")
            print(f"--- Passage {i} [{p['section']}] score={p['score']} ---")
            print(preview + ("..." if len(p["text"]) > 200 else ""))
            print(f"    sha256={p['sha256'][:16]}...")
            print()

    except Exception as e:
        print(f"❌ 오류: {e}", file=sys.stderr)
        sys.exit(1)
