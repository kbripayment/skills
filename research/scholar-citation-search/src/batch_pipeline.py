#!/usr/bin/env python3
"""
배치 파이프라인 — 원논문 DOI를 입력받아 citing 논문들을 개별 .md로 Obsidian 저장 (v1.3.0).

핵심 설계:
  - citation_pipeline.py의 run_pipeline을 재사용하지 않고 개별 함수를 직접 호출
    (단일/배치 파이프라인 시그니처 오염 방지)
  - Gap a:  scite/OpenAlex 호출 사이에 1.0초 Rate Limit throttle
  - Gap g:  batch_progress.json로 중단/재개 복구 지원 (--resume)
  - SHA256 사전 스캔 O(1) 중복 검사 (build_sha256_set 재사용)

사용법:
    # 전체 배치 (최대 20건 citing 논문)
    python src/batch_pipeline.py --doi "10.18653/v1/N19-1423" \
        --rq "How does self-attention compare to LSTM?" \
        --vault "D:/Obsidian Vault" --max-citing 20

    # 중단 후 재개 (completed_dois 스킵)
    python src/batch_pipeline.py --doi "10.18653/v1/N19-1423" \
        --rq "attention" --vault "D:/Obsidian Vault" --resume
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import time as _time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

# ── 경로 ──────────────────────────────────────────────────────────────

SKILL_ROOT = Path(__file__).parent.parent.resolve()
SRC_DIR = SKILL_ROOT / "src"
DOWNLOAD_DIR = Path.home() / "AppData" / "Local" / "Temp" / "academic-mcp-downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── citation_pipeline 함수 직접 임포트 ──────────────────────────────
# NOTE: batch_pipeline은 run_pipeline 재사용 대신 개별 함수를 직접 호출하여
#       단일/배치 간 시그니처 오염을 방지한다.
sys.path.insert(0, str(SRC_DIR))

from citation_pipeline import (
    CanonicalPaper,
    SciteVerification,
    FilteredPassage,
    enrich_paper,
    acquire_body,
    extract_and_filter,
    _verify_scite_async,
    load_env_key,
    build_sha256_set,
    check_existing_sha256_cached,
    invalidate_sha256_cache,
    save_to_obsidian,
    fetch_openalex_by_doi,
    collect_scholar_cited_by as _collect_openalex,
)


# ── 진행 상태 (Gap g) ────────────────────────────────────────────────

@dataclass
class BatchProgress:
    """batch_progress.json 상태 관리."""
    source_doi: str
    source_title: str
    started_at: str
    completed_dois: list[str] = field(default_factory=list)
    failed_dois: list[str] = field(default_factory=list)
    # failed_details: {doi -> {"error": str, "title": str}}

    @classmethod
    def load(cls, path: Path) -> "BatchProgress":
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return cls(**data)
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    def save(self, path: Path) -> None:
        """JSON 저장 + OS 버퍼 플러시 (중단 복구 보장)."""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic on POSIX; Windows에서도 충분히 안전

    def mark_completed(self, doi: str) -> None:
        if doi not in self.completed_dois:
            self.completed_dois.append(doi)

    def mark_failed(self, doi: str) -> None:
        if doi not in self.failed_dois:
            self.failed_dois.append(doi)


def _progress_path(source_doi: str) -> Path:
    """DOI 해시 기반 progress 파일 경로."""
    h = hashlib.sha1(source_doi.encode()).hexdigest()[:12]
    return DOWNLOAD_DIR / f"batch_progress_{h}.json"


# ── Rate Limit throttle (Gap a) ────────────────────────────────────

THROTTLE_INTERVAL = 1.0  # 초


def _throttle(label: str = "throttle") -> None:
    """scite/OpenAlex API 호출 사이에 1.0초 대기 (Rate Limit 방지)."""
    print(f"  [THROTTLE] [{label}] {THROTTLE_INTERVAL}s rate limit 대기...")
    _time.sleep(THROTTLE_INTERVAL)


def _check_vault_capacity(vault_path: str | Path, estimated_pdfs: int = 20, avg_mb: float = 4.4) -> None:
    """vault 용량 경고: 여유 공간이 예상 필요량의 1.5배 미만이면 경고."""
    import shutil
    free_gb = shutil.disk_usage(vault_path).free / (1024 ** 3)
    needed_gb = (estimated_pdfs * avg_mb) / 1024
    if free_gb < needed_gb * 1.5:
        print(f"[WARN] 용량 경고: 여유 {free_gb:.1f}GB, 필요 ~{needed_gb:.1f}GB (PDF {estimated_pdfs}건 기준)")


# ── 단일 citing 논문 처리 ──────────────────────────────────────────

async def process_citing_paper(
    citing: dict,
    source_doi: str,
    source_title: str,
    research_question: str,
    vault_path: str,
    sha256_set: set[str],
    progress: BatchProgress,
    progress_path: Path,
    filter_threshold: float,
    max_passages: int,
    mailto: str,
) -> bool:
    """
    단일 citing 논문을 Enrich → Acquire → Filter → Verify → Obsidian 저장 파이프라인.

    Returns: True(성공) / False(실패)
    """
    doi = citing.get("doi") or ""
    title = citing.get("title") or citing.get("display_name", "") or "Unknown"

    # ── Gap g: 이미 완료된 DOI 스킵 ─────────────────────────────
    if doi and doi in progress.completed_dois:
        print(f"  [SKIP] [{doi}] 이미 완료 — 스킵 (resume)")
        return True

    print(f"\n  [PAPER] [{doi or 'no-DOI'}] {title[:60]}")

    # ── ① CanonicalPaper 생성 ────────────────────────────────────
    paper = CanonicalPaper(
        doi=doi or None,
        title=title,
        authors=citing.get("authors", []),
        year=citing.get("year"),
        open_access_url=citing.get("open_access_url"),
        source="openalex",
    )

    # ── ② OpenAlex 메타 보강 ────────────────────────────────────
    _throttle("OpenAlex")
    paper = await enrich_paper(paper)
    print(f"    [①-③] 보강: {paper.title[:50]}, year={paper.year}")

    # ── ③ 3-tier 본문 확보 ──────────────────────────────────────
    paper = await acquire_body(paper)
    print(f"    [④] 본문: tier={paper.acquisition_tier}, method={paper.acquisition_method}")

    # ── ④ LLM 필터링 ───────────────────────────────────────────
    passages: list[FilteredPassage] = []
    if paper.sha256 and research_question:
        passages = await extract_and_filter(
            paper, research_question, filter_threshold, max_passages
        )
        print(f"    [⑤] 필터 통과: {len(passages)}건 passage")
    else:
        print(f"    [⑤] PDF/RQ 없음 — 패스")

    # ── ⑤ scite 검증 ───────────────────────────────────────────
    verification = SciteVerification(doi=paper.doi or "", title=paper.title)
    if paper.doi:
        _throttle("scite")
        token = load_env_key("SCITE_ACCESS_TOKEN")
        if token:
            verification = await _verify_scite_async(paper.doi, paper.title, token)
        else:
            verification.error = "SCITE_ACCESS_TOKEN 없음"
            verification.verification_status = "scite_unreachable"
        print(f"    [⑥] scite: label={verification.label}, status={verification.verification_status}")
    else:
        verification.verification_status = "unverifiable_no_doi"
        verification.error = "DOI 없음 — scite 검증 불가"
        print(f"    [⑥] DOI 없음 — scite 검증 스킵")

    # ── ⑥ Obsidian 저장 (백링크 포함) ───────────────────────────
    saved_path = None
    try:
        # SHA256 사전 스캔 기반 O(1) 중복 검사
        if paper.sha256 and paper.sha256 in sha256_set:
            print(f"    [WARN] SHA256 중복 — 저장 스킵: {paper.sha256[:16]}...")
        else:
            saved = save_to_obsidian(
                paper, verification, list(passages),
                vault_path,
                source_doi=source_doi,   # citing 논문에 원논문 DOI 백링크
                source_title=source_title, # citing 논문에 원논문 제목 백링크
            )
            if saved:
                saved_path = str(saved)
                # SHA256 집합에 새 해시 추가 (메모리 내 동기화)
                if paper.sha256:
                    sha256_set.add(paper.sha256)
    except (FileNotFoundError, PermissionError) as e:
        print(f"    [ERROR] Obsidian 저장 실패: {e}")
        progress.mark_failed(doi)
        progress.save(progress_path)
        return False

# ── 완료 처리 ───────────────────────────────────────────────
    progress.mark_completed(doi)
    progress.save(progress_path)
    print(f"    [DONE] 완료: {saved_path or '(skip/duplicate)'}")
    return True


# ── 메인 배치 실행 ─────────────────────────────────────────────────

async def run_batch(
    source_doi: str,
    research_question: str,
    vault_path: str,
    max_citing: int = 20,
    filter_threshold: float = 0.40,
    max_passages: int = 10,
    mailto: str = "",
    resume: bool = False,
) -> BatchProgress:
    """
    원논문 DOI의 citing 논문들을 배치 처리한다.

    Returns: BatchProgress 결과
    """
    print(f"\n{'='*60}")
    print(f"[BATCH] 배치 파이프라인 시작 — 원본 DOI: {source_doi}")
    print(f"   max_citing={max_citing}, throttle={THROTTLE_INTERVAL}s, resume={resume}")
    print(f"{'='*60}\n")

    vault = Path(vault_path)
    if not vault.exists():
        raise FileNotFoundError(f"Obsidian vault 없음: {vault}")

    _check_vault_capacity(vault, estimated_pdfs=max_citing)

    # ── progress 파일 로드 (Gap g: --resume) ────────────────────
    progress_path = _progress_path(source_doi)
    progress = BatchProgress.load(progress_path)

    if progress and resume:
        print(f"[Resume] 기존 진행 상태 발견:")
        print(f"  완료: {len(progress.completed_dois)}건")
        print(f"  실패: {len(progress.failed_dois)}건")
        print(f"  시작: {progress.started_at}")
    else:
        # 새 시작 또는 resume 없이 재실행 (기존 progress 덮어쓰기)
        print(f"[NEW] progress 파일: {progress_path}")
        progress = BatchProgress(
            source_doi=source_doi,
            source_title="",
            started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

    # ── SHA256 사전 스캔 O(1) (Gap b 재사용) ────────────────────
    print(f"[Vault] SHA256 사전 스캔 시작...")
    sha256_set = build_sha256_set(vault_path)
    print(f"[Vault] {len(sha256_set)}건 고유 해시 적재 완료\n")

    # ── 원본 논문 메타 조회 (백링크용) ───────────────────────────
    _throttle("OpenAlex (원본 DOI)")
    from citation_pipeline import fetch_openalex_by_doi
    source_data = await fetch_openalex_by_doi(source_doi, mailto)
    source_title = (
        source_data.get("display_name", "")
        if source_data
        else ""
    )
    progress.source_title = source_title
    print(f"[SRC] {source_title[:60]}\n")

    # ── citing 논문 수집 ─────────────────────────────────────────
    print(f"[COLLECT] citing 논문 조회 중 (max={max_citing})...")
    citing_list = await _collect_openalex(source_title, max_results=max_citing)
    if not citing_list:
        print("[WARN] citing 논문 0건 — 종료")
        return progress

    total = len(citing_list)
    print(f"[COLLECT] {total}건 조회 완료\n")

    # ── 배치 루프 ────────────────────────────────────────────────
    succeeded = 0
    failed = 0
    skipped = 0

    for idx, citing in enumerate(citing_list, 1):
        doi = citing.get("doi") or citing.get("title", "no-title")[:30]
        print(f"[{idx}/{total}] 처리 중: {doi}")

        if doi in progress.completed_dois:
            skipped += 1
            print(f"  [SKIP] 이미 완료 — 스킵")
            continue

        ok = await process_citing_paper(
            citing=citing,
            source_doi=source_doi,
            source_title=source_title,
            research_question=research_question,
            vault_path=vault_path,
            sha256_set=sha256_set,
            progress=progress,
            progress_path=progress_path,
            filter_threshold=filter_threshold,
            max_passages=max_passages,
            mailto=mailto,
        )
        if ok:
            succeeded += 1
        else:
            failed += 1

    # ── 결과 요약 ────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"[DONE] 배치 완료 — succeeded={succeeded}, failed={failed}, skipped={skipped}")
    print(f"   progress: {progress_path}")
    print(f"{'='*60}\n")

    progress.save(progress_path)
    return progress


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="원논문 DOI 기반 citing 논문 배치 Obsidian 저장 (v1.3.0)"
    )
    parser.add_argument("--doi", required=True, help="원본 논문 DOI")
    parser.add_argument("--rq", default="", help="유사 판별 기준 연구 질문")
    parser.add_argument("--vault", required=True, help="Obsidian vault 경로")
    parser.add_argument(
        "--max-citing", type=int, default=20,
        help="처리할 citing 논문 최대 수 (기본 20)"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.40,
        help="LLM 필터 threshold (기본 0.40)"
    )
    parser.add_argument(
        "--max-passages", type=int, default=10,
        help="최대 passage 수 (기본 10)"
    )
    parser.add_argument("--mailto", default="", help="OpenAlex polite pool 이메일")
    parser.add_argument(
        "--resume", action="store_true",
        help="이전 progress.json에서 이어서 실행 (완료된 DOI 스킵)"
    )
    args = parser.parse_args()

    result = asyncio.run(run_batch(
        source_doi=args.doi,
        research_question=args.rq,
        vault_path=args.vault,
        max_citing=args.max_citing,
        filter_threshold=args.threshold,
        max_passages=args.max_passages,
        mailto=args.mailto,
        resume=args.resume,
    ))

    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
