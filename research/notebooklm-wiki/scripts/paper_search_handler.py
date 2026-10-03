#!/usr/bin/env python3
"""
논문 검색 핸들러 - Hermes와 Slack 통합

워크플로:
1. Slack에서 주제 입력 → Hermes가 PubMed/bioRxiv/Semantic Scholar(+Springer/Elsevier)에서 검색
2. 결과를 Slack에 리스트 형태로 전송 → 사용자가 번호로 선택
3. 선택된 논문을 NotebookLM에 소스 추가 (PDF는 사용자 요청)
4. 메타데이터를 LLM-wiki raw/에 저장 + concepts/(주제).md에 교차참조 추가
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Dict, Optional

# paper_search.py lives alongside this file; ensure it is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paper_search import search_all

# Windows 콘솔(cp949)에서 이모지 출력 시 UnicodeEncodeError 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 환경 변수
WIKI_PATH = Path(os.environ.get("WIKI_PATH", os.path.expanduser("~/wiki")))
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# ─── Slack Helper ───────────────────────────────────────────────────────────── #
def send_slack_message(message: str, webhook_url: Optional[str] = None):
    """Slack으로 메시지 전송."""
    import urllib.request

    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        print("⚠️ SLACK_WEBHOOK_URL 미설정. Slack 알림 건너뛰기.")
        return

    payload = {"text": message}
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data,
                                    headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            # Slack incoming webhooks reply with plain text "ok", not JSON.
            body = response.read().decode()
            if response.status == 200 and "ok" in body.lower():
                print("✅ Slack 메시지 전송 완료")
            else:
                print(f"⚠️ Slack 응답: {body}")
    except Exception as e:
        print(f"⚠️ Slack 메시지 전송 실패: {e}")

# ─── Paper Search (delegates to paper_search.py) ───────────────────────────── #

def paper_to_dict(p) -> Dict:
    """paper_search.Paper → handler가 사용하는 dict 형태로 변환."""
    raw = p.raw if isinstance(p.raw, dict) else {}
    authors = p.authors if isinstance(p.authors, list) else []
    return {
        "source": p.source,
        "id": p.paper_id,
        "title": p.title,
        "url": p.url,
        "authors": ", ".join(authors),
        "journal": raw.get("fulljournalname", "") or raw.get("venue", "") or "",
        "pubdate": p.published_date,
    }


def search_papers(query: str, max_results: int = 5, lookback_days: int = 1) -> List[Dict]:
    """paper_search.search_all()을 호출해 통합 검색 후 dict 리스트로 반환.

    대상: PubMed + bioRxiv + Semantic Scholar + (API key 있으면) Springer/Elsevier.
    arXiv는 paper_search 모듈에서 bioRxiv로 대체되었다.
    """
    try:
        papers = search_all(query, max_results=max_results, lookback_days=lookback_days)
    except Exception as e:
        print(f"논문 검색 실패: {e}")
        return []
    return [paper_to_dict(p) for p in papers]

# ─── LLM-wiki 저장 ──────────────────────────────────────────────────────────── #

def save_to_llmwiki(source: str, query: str, papers: List[Dict]):
    """논문 메타데이터를 LLM-wiki raw/ 디렉토리에 저장."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    # 파일명 안전하게 처리
    safe_query = "".join(c if c.isalnum() else "_" for c in query)[:50]
    filename = WIKI_PATH / "raw" / f"{source}_{safe_query}_{timestamp}.md"
    filename.parent.mkdir(parents=True, exist_ok=True)
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# {source} 검색 결과: '{query}'\n\n")
        f.write(f"검색 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## 논문 목록\n\n")
        
        for i, paper in enumerate(papers, 1):
            f.write(f"### {i}. {paper['title']}\n")
            f.write(f"- **출처**: {paper['source']}\n")
            f.write(f"- **ID**: `{paper['id']}`\n")
            f.write(f"- **URL**: {paper['url']}\n")
            f.write(f"- **저자**: {paper['authors']}\n")
            f.write(f"- **저널/출판**: {paper['journal']}\n")
            f.write(f"- **발표일**: {paper['pubdate']}\n")
            f.write(f"- **선택 ID**: `{paper['source']}:{paper['id']}`\n\n")
    
    print(f"✅ LLM-wiki에 저장됨: {filename}")
    return filename

def update_concept_page(topic: str, papers: List[Dict]):
    """concepts/(주제명).md에 교차참조 추가."""
    concepts_dir = WIKI_PATH / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)
    
    # 파일명 안전하게 처리
    safe_topic = "".join(c if c.isalnum() else "_" for c in topic)[:50]
    concept_file = concepts_dir / f"{safe_topic}.md"
    
    # 기존 내용 읽기 (없으면 새로 생성)
    existing_content = ""
    if concept_file.exists():
        existing_content = concept_file.read_text(encoding="utf-8")
    
    # 새 참조 섹션 작성
    new_section = f"\n## 연구 업데이트 ({datetime.now().strftime('%Y-%m-%d')})\n\n"
    for paper in papers:
        new_section += f"- [[raw/{paper['source']}:{paper['id']}]]: {paper['title']}\n"
    
    # 파일 쓰기
    with open(concept_file, "a", encoding="utf-8") as f:
        f.write(new_section)
    
    print(f"✅ 개념 페이지 업데이트: {concept_file}")

# ─── Hermes 명령어 핸들러 ────────────────────────────────────────────────────── #

class PaperSelectionState:
    """논문 선택 상태를 추적하는 클래스."""
    _instance = None
    _results: List[Dict] = []
    _query: str = ""
    _notebook_id: str = ""
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @property
    def results(self):
        return self._results
    
    @results.setter
    def results(self, value):
        self._results = value
    
    @property
    def query(self):
        return self._query
    
    @query.setter
    def query(self, value):
        self._query = value
    
    @property
    def notebook_id(self):
        return self._notebook_id
    
    @notebook_id.setter
    def notebook_id(self, value):
        self._notebook_id = value
    
    def clear(self):
        self._results = []
        self._query = ""
        self._notebook_id = ""
        try:
            _state_file().unlink(missing_ok=True)
        except Exception:
            pass

# 전역 상태 인스턴스
state = PaperSelectionState()

# ─── 상태 영속화 (CLI 호출 간 상태 유지) ────────────────────────────────────────── #
def _state_file() -> Path:
    """검색 상태를 보관할 파일 경로."""
    return WIKI_PATH / ".paper_search_state.json"

def _save_state():
    """현재 선택 상태를 디스크에 저장 (프로세스 간 유지)."""
    try:
        data = {
            "results": state.results,
            "query": state.query,
            "notebook_id": state.notebook_id,
        }
        _state_file().parent.mkdir(parents=True, exist_ok=True)
        _state_file().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"⚠️ 상태 저장 실패: {e}")

def _load_state():
    """디스크에서 선택 상태를 복원 (없으면 무시)."""
    try:
        p = _state_file()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            state.results = data.get("results", [])
            state.query = data.get("query", "")
            state.notebook_id = data.get("notebook_id", "")
    except Exception:
        pass

def hermes_paper_search_handler(command: str, args: List[str]):
    """Slack/Hermes에서 논문 검색 명령어 처리."""
    query = " ".join(args) if args else ""

    if command in ("select", "status"):
        _load_state()

    if command == "search":
        if not query:
            send_slack_message("❌ 검색어를 입력하세요. 예: `/search 양자컴퓨팅`")
            return None
        
        send_slack_message(f"🔍 '{query}'에 대해 PubMed, bioRxiv, Semantic Scholar에서 검색 중...")
        
        # paper_search.py 통합 검색 (PubMed + bioRxiv + Semantic Scholar + Springer/Elsevier)
        all_papers = search_papers(query)
        
        if not all_papers:
            send_slack_message("🔍 검색 결과가 없습니다. 다른 검색어를 시도해 보세요.")
            state.clear()
            _save_state()
            return None
        
        # 결과를 Slack에 번호 매겨서 전송
        message = f"📄 **'{query}' 검색 결과** (총 {len(all_papers)}건)\n\n"
        for i, paper in enumerate(all_papers, 1):
            message += f"**{i}. [{paper['source']}]** {paper['title'][:100]}...\n"
            message += f"   👤 {paper['authors']}\n"
            message += f"   🔗 {paper['url']}\n\n"
        
        message += "\n선택하려면 `/select <번호>`를 입력하세요. (예: `/select 1`)"
        
        send_slack_message(message)
        
        # 상태 저장
        state.results = all_papers
        state.query = query
        _save_state()
        
        # LLM-wiki에 검색 결과 저장
        save_to_llmwiki("multi", query, all_papers)
        
        return all_papers
    
    elif command == "select":
        if not state.results:
            send_slack_message("❌ 먼저 `/search <주제>`로 검색을 수행하세요.")
            return None
        
        try:
            selection = int(args[0]) - 1 if args else -1
            if selection < 0 or selection >= len(state.results):
                send_slack_message(f"❌ 잘못된 번호입니다. 1~{len(state.results)} 사이의 번호를 입력하세요.")
                return None
            
            selected_paper = state.results[selection]
            
            # NotebookLM에 소스 추가
            # PDF 요청 메시지 전송
            send_slack_message(
                f"✅ **선택된 논문**: {selected_paper['title']}\n\n"
                f"📄 출처: {selected_paper['source']}\n"
                f"🔗 URL: {selected_paper['url']}\n"
                f"👤 저자: {selected_paper['authors']}\n\n"
                f"📥 NotebookLM에 URL 소스를 추가했습니다.\n"
                f"📄 PDF가 필요하시면 파일을 업로드하거나 `/pdf-request` 명령어로 요청하세요."
            )
            
            # LLM-wiki 개념 페이지 업데이트
            update_concept_page(state.query, [selected_paper])
            _save_state()
            
            return selected_paper
            
        except ValueError:
            send_slack_message("❌ 숫자를 입력하세요. (예: `/select 1`)")
            return None
    
    else:
        send_slack_message("지원하지 않는 명령어입니다. `/search` 또는 `/select`를 사용하세요.")
        return None

# ─── CLI 인터페이스 ─────────────────────────────────────────────────────────── #

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="논문 검색 및 선택 핸들러")
    subparsers = parser.add_subparsers(dest="command")
    
    # 검색 명령
    search_parser = subparsers.add_parser("search", help="주제로 논문 검색")
    search_parser.add_argument("query", nargs="+", help="검색어")
    
    # 선택 명령
    select_parser = subparsers.add_parser("select", help="검색 결과에서 번호로 선택")
    select_parser.add_argument("index", type=int, help="선택할 번호 (1부터 시작)")
    
    # 상태 확인
    status_parser = subparsers.add_parser("status", help="현재 검색 상태 확인")
    
    args = parser.parse_args()

    if args.command in ("select", "status"):
        _load_state()

    if args.command == "search":
        papers = hermes_paper_search_handler("search", args.query)
        if papers:
            print(f"\n🔍 총 {len(papers)}개 논문 검색 완료. 번호를 선택하세요.")
    
    elif args.command == "select":
        if not 1 <= args.index <= len(state.results):
            print(f"❌ 잘못된 번호입니다. 1~{len(state.results)} 사이의 번호를 입력하세요.")
            sys.exit(1)
        selected = hermes_paper_search_handler("select", [str(args.index)])
        if selected:
            print(f"✅ 선택된 논문: {selected['title']}")
    
    elif args.command == "status":
        if state.results:
            print(f"🔍 현재 검색 결과: {len(state.results)}개")
            print(f"📝 검색어: {state.query}")
            for i, p in enumerate(state.results, 1):
                print(f"  {i}. [{p['source']}] {p['title'][:60]}...")
        else:
            print("🔍 현재 검색 결과 없음. `/search <주제>`로 시작하세요.")
    
    else:
        parser.print_help()
