#!/usr/bin/env python3
"""
Local LLM 요약 모듈.

- 텍스트(초록) 요약 → Local LLM (GLM-5.2, llm-chat.example.local:8888)
- 이미지(Graphical Abstract / Figure) 요약 → Vision LLM (Qwen2.5-VL-72B, llm-vision.example.local:8888)
- 응답 불안정성 대응: .get() 폴백 체이닝 + 재시도
- GLM-5.2는 reasoning_content 필드에 답변 출력 → content 우선, reasoning_content fallback
"""

import os
import re
import logging
import time
import ipaddress
import socket
import urllib.parse
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

# Hermes 전역 .env 우선 로드 (라이브 시크릿)
HERMES_ENV = os.path.expanduser(r"~\AppData\Local\hermes\.env")
if os.path.exists(HERMES_ENV):
    load_dotenv(HERMES_ENV)

# 로컬 스킬 .env 로드 (토픽, 편수 설정 등)
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_ENV = os.path.join(SKILL_ROOT, ".env")
if os.path.exists(LOCAL_ENV):
    load_dotenv(LOCAL_ENV)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 설정
# ------------------------------------------------------------------

LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://llm-chat.example.local:8888")  # GLM-5.2
VISION_LLM_URL = os.getenv("VISION_LLM_URL", "http://llm-vision.example.local:8888")  # Qwen2.5-VL-72B
DEFAULT_MODEL = os.getenv("LLM_MODEL", "")  # 빈 문자열 = Ollama 자동 모델 선택


def _env_int(name: str, default: int) -> int:
    """환경변수를 안전하게 int로 읽음 (잘못된 값이면 기본값)."""
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        logger.warning(f"환경변수 {name}이(가) 정수가 아님 — 기본값 {default} 사용")
        return default


# LLM 요청 타임아웃 (초). GLM-5.2 CPU 기반 2~3분/요청이므로 기본 4분(240초).
# 서버 지연 시 빠르게 초록으로 넘어가기 위해 타임아웃 240초, 재시도 1회(재시도 없음) 적용.
LLM_TIMEOUT_SECS = _env_int("LLM_TIMEOUT_SECS", 240)  # 기본 240초 (4분)
LLM_MAX_RETRIES = _env_int("LLM_MAX_RETRIES", 1)      # 1회 실패 시 재시도 없이 즉시 폴백

# 텍스트 요약 시스템 프롬프트 — 출력은 '목적'/'결과' 두 줄만 허용.
# 지시문·안내문(예: "The user wants a summary...")이 응답에 새는 것을 방지하기 위해
# 형식을 강제하고, 응답 후처리 클리너(_clean_llm_text)로도 한 번 더 걸러냄.
#
# 두 가지 모드:
# - abstract 모드: 초록만 있을 때. 논리 전개에 맞춰 정리하되 불완전한 부분은
#   추론으로 보완 가능 — 추론 내용은 문장 끝에 (추론) 표기.
# - fulltext 모드: 논문 전문(PDF)이 있을 때. 본문 서술 흐름을 따르고 등장하는
#   Figure들을 흐름 순서로 언급. 결과 길이 제한 없음.
_ABSTRACT_RULES = (
    "결과에는 길이 제한이 없다 — 주요 결과와 시사점을 충분히 상술한다.\n"
    "초록의 논리 전개가 불완전한 부분은 맥락에 맞게 추론하여 보완할 수 있으며, "
    "초록에 직접적 근거가 없어 추론한 내용은 해당 부분 끝에 (추론)라고 명시한다.\n"
)
_FULLTEXT_RULES = (
    "본문(전문)의 내용 흐름을 따라 요약하고, 등장하는 Figure들은 흐름 순서대로 언급하며 "
    "해당 Figure가 보여주는 내용을 함께 서술한다 (예: 'Figure 2에서 X를 확인').\n"
    "결과에는 길이 제한이 없다 — 주요 결과와 시사점을 충분히 상술한다.\n"
    "텍스트에서 근거를 찾아 추론한 해석은 해당 부분 끝에 (추론)라고 명시한다.\n"
)
_COMMON_TAIL = (
    "절대 규칙: 지시문/안내문/영어 설명/형식 언급을 출력하지 않는다. 위 두 줄 외의 모든 출력은 금지."
)

TEXT_SYSTEM_PROMPT = (
    "You are a research assistant. Analyze the paper ABSTRACT and output EXACTLY two lines in Korean.\n"
    "Format (output ONLY these two lines — no preamble, no instructions, no extra bullets):\n"
    "목적: <연구 목적 1~2문장>\n"
    "결과: <주요 결과 및 시사점>\n"
    + _ABSTRACT_RULES + _COMMON_TAIL
)

FULLTEXT_SYSTEM_PROMPT = (
    "You are a research assistant. Analyze the PAPER FULLTEXT / EXCERPTS below and output EXACTLY two lines in Korean.\n"
    "Format (output ONLY these two lines — no preamble, no instructions, no extra bullets):\n"
    "목적: <연구 목적 1~2문장>\n"
    "결과: <주요 결과 및 시사점>\n"
    + _FULLTEXT_RULES + _COMMON_TAIL
)

# LLM 응답에서 제거할 메타/안내문 라인 패턴 (프롬프트 에코 방지)
_META_LINE_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"^\s*(the\s+)?user\s+wants?\b",
    r"^\s*summary\s+(is|needs?|should)\b",
    r"^\s*\d*\.?\s*(concise\s+)?bullet\s+points?\b",
    r"^\s*in\s+korean[\s.,!]*$",
    r"^\s*here('s| is)\s+(a|the)\s+summary\b",
    r"^\s*(sure|certainly|of course)[!,.]?\s*$",
    r"^\s*(as an? (ai|research assistant))\b",
    r"^\s*(다음은|아래는|아래와 같이|제공된 초록|요약을) .*(합니다|입니다|드립니다)\s*$",
    r"^\s*(형식|출력 형식|포맷)[:：]",
    r"^(the format is|format:)",
    r"^(abstract analysis|drafting|refining|check(ing)? (constraints|the)|final (check|answer)|let me)\b",
    r"^-\s*(exactly|no preamble|absolutely no)\b",
))

# '목적:'/'결과:' 라벨 행 인식용
_PAIR_LABEL_RE = re.compile(r"^\s*\*{0,2}\s*(목적|결과)\s*\*{0,2}\s*[:：]\s*\*{0,2}")


def _clean_llm_text(text: str) -> str:
    """
    LLM 응답 후처리:
    - 코드펜스 제거, 메타/안내문 라인 제거(프롬프트 에코 차단), 공백 정규화
    - '목적:'/'결과:' 라벨 앞뒤 마크다운 강조(** 등) 제거

    GLM-5.2는 사고과정(초안→다듬기→검증)을 content에 통째로 출력하고 최종 답안이
    마지막에 오는 경향이 있으므로, 라벨 쌍이 존재하면 **마지막 쌍만** 남긴다.
    """
    if not text:
        return ""
    cleaned_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```"):
            continue
        if any(p.search(line) for p in _META_LINE_PATTERNS):
            continue
        # **목적:** 등 마크다운 강조 제거 (콜론 뒤 닫는 ** 포함)
        line = re.sub(
            r"^\*{0,2}\s*(목적|결과|Purpose|Result|Results|Aim|Findings)\s*\*{0,2}\s*[:：]\s*\*{0,2}",
            r"\1: ",
            line,
        )
        cleaned_lines.append(line)

    joined = "\n".join(cleaned_lines).strip()

    last_purpose = last_result = None
    for line in joined.splitlines():
        m = _PAIR_LABEL_RE.match(line)
        if not m:
            continue
        if m.group(1) == "목적":
            last_purpose = line.strip()
        else:
            last_result = line.strip()

    if last_purpose or last_result:
        return "\n".join(l for l in (last_purpose, last_result) if l)
    return joined


# ------------------------------------------------------------------
# 데이터 모델
# ------------------------------------------------------------------

@dataclass
class SummaryResult:
    """LLM 요약 결과. status: 'ok' | 'llm_failed' | 'no_content' | 'skipped'"""
    summary: str  # 핵심 요약 (목적/결과 두 줄 또는 폴백 초록)
    status: str = "ok"  # 서킷 브레이커가 실제 LLM 성공/실패를 정확히 판정하기 위한 상태값


# ------------------------------------------------------------------
# 모델 자동 조회
# ------------------------------------------------------------------

# URL별 모델명 캐시. 조회 실패(빈 값)는 캐시하지 않아 다음 호출 시 재시도됨.
_model_cache: Dict[str, str] = {}


def _get_model_name(llm_url: str = None) -> str:
    """Local LLM의 /v1/models에서 첫 번째 모델 이름 자동 조회."""
    if llm_url is None:
        llm_url = LOCAL_LLM_URL
    try:
        r = requests.get(f"{llm_url.rstrip('/')}/v1/models", timeout=10)
        r.raise_for_status()
        models = r.json().get("models", [])
        if models:
            name = models[0].get("model", "") or models[0].get("name", "")
            if name:
                return name
    except Exception as e:
        logger.warning(f"모델 자동 조회 실패: {e}")
    return ""


def get_model(llm_url: str = None) -> str:
    """
    모델 이름 반환. .env/기본값 우선, 자동 조회 fallback.

    - llm_url 생략 시 LOCAL_LLM_URL 기준 (DEFAULT_MODEL 우선 적용)
    - VISION_LLM_URL 등 다른 서버는 해당 /v1/models에서 별도 조회
    - 일시적 조회 실패(빈 값)는 캐시하지 않음 → 다음 호출에서 재시도
    """
    url = (llm_url or LOCAL_LLM_URL).rstrip("/")
    if url in _model_cache:
        return _model_cache[url]

    name = ""
    if url == LOCAL_LLM_URL.rstrip("/") and DEFAULT_MODEL:
        name = DEFAULT_MODEL
    else:
        name = _get_model_name(url)

    if name:
        _model_cache[url] = name
    return name


# ------------------------------------------------------------------
# 헬퍼
# ------------------------------------------------------------------

def _build_openai_payload(
    messages: List[dict],
    model: str = "",
    max_tokens: int = 512,
    temperature: float = 0.3,
) -> dict:
    """OpenAI 호환 Chat API 요청 바디."""
    payload = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    # 모델 이름이 있으면 payload에 포함 (없으면 Ollama 자동 선택)
    if model:
        payload["model"] = model
    return payload


def _extract_content(resp_json: dict) -> str:
    """
    OpenAI 호한 응답에서 content 추출.
    GLM-5.2 (Local LLM)는 reasoning_content 필드에 답변이 있을 수 있음.
    Qwen2.5-VL (Vision LLM)는 표준 choices[0].message.content 사용.
    """
    # 표준 OpenAI: choices[0].message.content
    content = (
        (resp_json.get("choices") or [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if content:
        return content.strip()

    # GLM-5.2 fallback: reasoning_content (thinking/reasoning 출력)
    content = (
        (resp_json.get("choices") or [{}])[0]
        .get("message", {})
        .get("reasoning_content", "")
    )
    if content:
        return content.strip()

    # fallback: response 필드
    content = resp_json.get("response", "")
    if content:
        return content.strip()

    # fallback: text 필드
    content = resp_json.get("text", "")
    if content:
        return content.strip()

    # fallback: message.content 직접
    content = resp_json.get("message", {}).get("content", "")
    if content:
        return content.strip()

    return ""


# 허용된 신뢰할 수 있는 학술 논문 PDF 호스트 화이트리스트
ALLOWED_ACADEMIC_DOMAINS = (
    "biorxiv.org",
    "medrxiv.org",
    "arxiv.org",
    "semanticscholar.org",
    "sciencedirect.com",
    "elsevier.com",
    "springer.com",
    "springeropen.com",
    "nature.com",
    "cell.com",
    "wiley.com",
    "nih.gov",
    "ncbi.nlm.nih.gov",
    "plos.org",
    "frontiersin.org",
    "mdpi.com",
    "pnas.org",
    "science.org",
    "sciencemag.org",
    "oup.com",
    "tandfonline.com",
    "cambridge.org",
    "biomedcentral.com",
    "iop.org",
    "annualreviews.org",
    "embopress.org",
    "thelancet.com",
    "ahajournals.org",
    "ashpublications.org",
    "sagepub.com",
)


def _is_safe_url(url: str, allowed_domains: Optional[Tuple[str, ...]] = ALLOWED_ACADEMIC_DOMAINS) -> bool:
    """
    SSRF 및 비인가 호스트 방지:
    - https 스키마 강제
    - 신뢰할 수 있는 학술 도메인 화이트리스트 검증
    - DNS 해석 후 사설/루프백/링크로컬/메타데이터/예약 IP 접근 차단
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            logger.warning(f"SSRF 차단: https 미사용 스키마 ({parsed.scheme}): {url}")
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        hostname_lower = hostname.lower()

        # 1. 학술 도메인 화이트리스트 검증
        if allowed_domains is not None:
            if not any(hostname_lower == d or hostname_lower.endswith("." + d) for d in allowed_domains):
                logger.warning(f"SSRF 차단: 허용되지 않은 비학술 도메인 ({hostname}): {url}")
                return False

        # 2. DNS 해석 후 사설/루프백/링크로컬/예약 IP 차단 (DNS Rebinding 방지)
        addr_info = socket.getaddrinfo(hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                logger.warning(f"SSRF 차단: 사설/로컬/예약 IP 접근 거부 ({hostname} -> {ip_str})")
                return False
        return True
    except Exception as e:
        logger.warning(f"URL 유효성 검증 실패 ({url[:80]}): {e}")
        return False


def _extract_text_and_captions_from_pdf_url(
    pdf_url: str,
    max_head_pages: int = 3,
    max_tail_pages: int = 3,
    max_bytes: int = 15 * 1024 * 1024,
) -> Tuple[str, List[str], bool, int]:
    """
    PDF URL로부터 본문 발췌(서론 Head + 결론/고찰 Tail) 및 전체 Figure 캡션 추출.
    반환: (body_text, captions, is_partial, total_pages)
    - SSRF 방지: https 강제, 학술 도메인 화이트리스트, 공인 IP만 허용
    - 메모리 보호: 15MB 스트리밍 상한 강제
    - 타임아웃: 10초
    - 결론 누락 방지: 전체 페이지 대상 Figure 캡션 수집 및 본문 고찰/결론 섹션 발췌
    """
    if not _is_safe_url(pdf_url):
        return "", [], False, 0

    tmp_path = ""
    try:
        import fitz  # pymupdf
        import tempfile

        r = requests.get(pdf_url, timeout=10, stream=True, allow_redirects=True)
        r.raise_for_status()

        # 리디렉션된 최종 대상 URL도 SSRF 검증
        if r.url != pdf_url and not _is_safe_url(r.url):
            logger.warning(f"SSRF 차단: 리디렉션된 대상 URL 안전성 검증 실패 ({r.url})")
            return "", [], False, 0

        content_length = int(r.headers.get("Content-Length") or 0)
        if content_length > max_bytes:
            logger.warning(f"PDF 크기 헤더 초과 ({content_length} bytes > {max_bytes} bytes), 건너뜀: {pdf_url}")
            return "", [], False, 0

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            downloaded = 0
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        logger.warning(f"PDF 스트리밍 상한({max_bytes} bytes) 초과로 중단: {pdf_url}")
                        return "", [], False, 0
                    f.write(chunk)
            tmp_path = f.name

        doc = fitz.open(tmp_path)
        captions: List[str] = []
        body_parts: List[str] = []
        total_pages = len(doc)
        is_partial = False

        try:
            # 1. 전체 페이지에서 Figure 캡션 수집 (최대 12개)
            for page in doc:
                page_text = page.get_text()
                for line in page_text.splitlines():
                    line = line.strip()
                    if re.match(r"^(Figure|Fig\.?)\s*\d+", line, re.IGNORECASE) and len(line) > 15:
                        captions.append(line[:300])
                        if len(captions) >= 12:
                            break
                if len(captions) >= 12:
                    break

            # 2. 본문 텍스트 발췌
            if total_pages <= (max_head_pages + max_tail_pages):
                for page in doc:
                    body_parts.append(page.get_text())
                is_partial = False
            else:
                is_partial = True
                # Head: 서론/배경 (0 .. max_head_pages-1)
                for i in range(min(max_head_pages, total_pages)):
                    body_parts.append(doc[i].get_text())

                # Tail: Discussion / Conclusion 위치 탐색
                discussion_page_idx = -1
                for i in range(max_head_pages, total_pages):
                    p_txt = doc[i].get_text()
                    if re.search(r"\b(Discussion|Conclusions?|Concluding\s+Remarks)\b", p_txt, re.IGNORECASE):
                        discussion_page_idx = i
                        break

                tail_start = discussion_page_idx if discussion_page_idx != -1 else max(max_head_pages, total_pages - max_tail_pages)
                tail_end = min(total_pages, tail_start + max_tail_pages)

                body_parts.append("\n\n[... 본문 중간 상세 방법론 생략 ...]\n\n")
                for i in range(tail_start, tail_end):
                    body_parts.append(doc[i].get_text())

            raw_body = "\n".join(body_parts)

            # 3. 마지막 참고문헌(References / Bibliography) 잘라내어 컨텍스트 절약
            ref_match = re.search(r"\n\s*(References|Literature Cited|Bibliography)\s*\n", raw_body, re.IGNORECASE)
            if ref_match:
                raw_body = raw_body[:ref_match.start()].strip()

            return raw_body.strip(), captions, is_partial, total_pages
        finally:
            doc.close()
    except Exception as e:
        logger.warning(f"PDF 텍스트 추출 실패 ({pdf_url[:80]}): {e}")
        return "", [], False, 0
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _extract_text_from_pdf_url(pdf_url: str, max_page: int = 8, max_bytes: int = 15 * 1024 * 1024) -> str:
    """기존 호환용 래퍼: PDF 본문 발췌 텍스트 반환."""
    text, _, _, _ = _extract_text_and_captions_from_pdf_url(pdf_url, max_bytes=max_bytes)
    return text


# ------------------------------------------------------------------
# Local LLM 텍스트 요약
# ------------------------------------------------------------------

def summarize_abstract(
    text: str,
    model: str = "",
    max_tokens: int = 1024,
    temperature: float = 0.3,
    max_retries: int = None,
    mode: str = "abstract",
) -> str:
    """
    초록 또는 전문 텍스트를 Local LLM에 전달해 '목적/결과' 두 줄 요약 생성.
    재시도 로직 포함.

    - mode="abstract": 초록 기반 요약 (불완전 부분 (추론) 보완 허용)
    - mode="fulltext": 전문 기반 요약 (Figure 흐름 따름, 결과 길이 제한 없음)
    - model=""이면 get_model()로 자동 조회
    """
    if max_retries is None:
        max_retries = LLM_MAX_RETRIES

    if not text or not text.strip():
        return "초록 정보가 없습니다."

    # 너무 길면 자르기 (토큰 제한)
    if len(text) > 8000:
        text = text[:8000] + "... (생략)"

    system_prompt = FULLTEXT_SYSTEM_PROMPT if mode == "fulltext" else TEXT_SYSTEM_PROMPT
    prefix = "PAPER FULLTEXT:\n" if mode == "fulltext" else "ABSTRACT:\n"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{prefix}{text}"},
    ]

    model = model or get_model()
    payload = _build_openai_payload(messages, model, max_tokens, temperature)
    # stop 토큰 추가로 과도한 출력 방지
    payload["stop"] = ["\n\n\n"]

    api_url = f"{LOCAL_LLM_URL.rstrip('/')}/v1/chat/completions"

    for attempt in range(max_retries):
        try:
            r = requests.post(api_url, json=payload, timeout=LLM_TIMEOUT_SECS)
            r.raise_for_status()
            resp_json = r.json()
            content = _clean_llm_text(_extract_content(resp_json))
            if content:
                return content
            logger.warning(f"Local LLM 응답에서 content 추출 실패 (attempt {attempt+1})")
        except requests.exceptions.ConnectionError:
            logger.error(f"Local LLM 연결 실패 (attempt {attempt+1}): {LOCAL_LLM_URL}")
        except requests.exceptions.ReadTimeout:
            logger.error(f"Local LLM 응답 타임아웃 (attempt {attempt+1}): request took >{LLM_TIMEOUT_SECS}s")
        except Exception as e:
            logger.error(f"Local LLM 요약 실패 (attempt {attempt+1}): {e}")

        if attempt < max_retries - 1:
            time.sleep(5 * (attempt + 1))

    return f"[요약 실패] Local LLM({LOCAL_LLM_URL})에 연결할 수 없습니다."


# ------------------------------------------------------------------
# 종합 요약 (fulltext 우선, abstract 폴백)
# ------------------------------------------------------------------

def _extract_figure_captions(text: str, max_captions: int = 12) -> List[str]:
    """전문 텍스트에서 Figure 캡션 행을 추출 (LLM에 구조 힌트로 제공)."""
    captions = []
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^(Figure|Fig\.?)\s*\d+", line, re.IGNORECASE) and len(line) > 15:
            captions.append(line[:300])
            if len(captions) >= max_captions:
                break
    return captions


def summarize_paper(paper) -> SummaryResult:
    """
    논문 객체를 요약. 두 가지 모드:

    - fulltext 모드: PDF 전문 접근 가능 시 — 본문 흐름 + Figure 캡션 힌트를
      함께 전달해 Figure별 내용 흐름 요약 유도
    - abstract 모드: 초록만 있을 때 — 논리 전개 정리, 불완전 부분은 (추론) 표기 허용

    Graphical Abstract / Vision LLM 경로는 제거됨.
    """
    # 1. fulltext 확보 시도
    pdf_url = None
    if paper.source == "biorxiv":
        # bioRxiv details API 응답에는 pdf_url 필드가 없으므로 DOI로 직접 구성
        doi = paper.paper_id or paper.raw.get("doi", "")
        if doi and str(doi).startswith("10."):
            pdf_url = f"https://www.biorxiv.org/content/{doi}.full.pdf"
    elif paper.source == "semantic_scholar":
        pdf_url = paper.raw.get("pdf_url") or None

    abstract = paper.abstract
    if not abstract and paper.source == "elsevier":
        abstract = paper.raw.get("dc:description", "") or paper.raw.get("dc:abstract", "") or ""

    if pdf_url and str(pdf_url).startswith("http"):
        # HTTP인 경우 HTTPS로 업그레이드
        if str(pdf_url).startswith("http://"):
            pdf_url = "https://" + str(pdf_url)[7:]

        body_text, captions, is_partial, total_pages = _extract_text_and_captions_from_pdf_url(pdf_url)
        if body_text and len(body_text) > 500:
            context_parts = []
            if abstract:
                context_parts.append(f"AUTHOR ABSTRACT:\n{abstract.strip()}")
            if captions:
                context_parts.append("FIGURE CAPTIONS (전체 논문 주요 Figure):\n" + "\n".join(captions))
            page_info = f"전체 {total_pages}쪽 중 서론 및 고찰/결론 발췌" if is_partial else f"전체 {total_pages}쪽 본문"
            context_parts.append(f"PAPER BODY EXCERPTS ({page_info}):\n{body_text}")

            context = "\n\n".join(context_parts)
            summary = summarize_abstract(context, mode="fulltext")
            if summary and not summary.startswith("[요약 실패]"):
                return SummaryResult(summary=summary, status="ok")
            # fulltext 요약 실패/타임아웃 시, 서버 지연 상태이므로 2차 LLM 호출을 하지 않고 즉시 원문 초록으로 폴백
            if abstract:
                logger.info(f"Fulltext 요약 실패로 원문 초록으로 즉시 폴백 ({paper.paper_id})")
                return SummaryResult(summary=f"초록 (전문 요약 실패): {abstract.strip()}", status="llm_failed")
            return SummaryResult(summary="초록 정보를 가져올 수 없습니다.", status="llm_failed")

    # 2. abstract 요약 시도
    if abstract:
        summary = summarize_abstract(abstract, mode="abstract")
        if summary and not summary.startswith("[요약 실패]"):
            return SummaryResult(summary=summary, status="ok")
        # LLM 요약 실패/타임아웃 시 원문 초록으로 즉시 폴백
        logger.info(f"초록 요약 실패/타임아웃으로 원문 초록으로 즉시 폴백 ({paper.paper_id})")
        return SummaryResult(summary=f"초록 (LLM 지연 대체): {abstract.strip()}", status="llm_failed")

    return SummaryResult(summary="초록 정보를 가져올 수 없습니다.", status="no_content")


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from paper_search import search_all

    topic = sys.argv[1] if len(sys.argv) > 1 else os.getenv("RESEARCH_TOPIC", "Cancer Immunotherapy")
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    papers = search_all(topic, max_results=3, lookback_days=days)
    for p in papers:
        print(f"\n=== [{p.source}] {p.title[:80]} ===")
        result = summarize_paper(p)
        print(result.summary)
