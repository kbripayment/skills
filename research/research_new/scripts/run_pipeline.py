#!/usr/bin/env python3
"""
run_pipeline 래퍼 (Windows/MSYS 겸용).

주의: 이 파일을 다른 위치로 복사해도 자기 자신을 재실행하지 않도록
파이프라인 경로는 절대 경로로 고정되어 있다. (과거 hermes/scripts 사본이
자기 자신을 무한 spawn해 크론 3시간 타임아웃이 발생한 적 있음)
"""

import sys
import os
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Hermes venv Python 우선 사용 (Windows 네이티브 경로)
VENV_PYTHON = "C:\\Users\\user\\AppData\\Local\\hermes\\hermes-agent\\venv\\Scripts\\python.exe"
if not os.path.exists(VENV_PYTHON):
    # 폴백: 시스템 python
    VENV_PYTHON = sys.executable

# 실제 오케스트레이터는 절대 경로로 지정 (래퍼 복사본 위치와 무관)
PIPELINE = "C:\\Users\\user\\AppData\\Local\\hermes\\skills\\research\\research_new\\scripts\\research_pipeline.py"

# .env 로딩을 위해 스킬 루트로 작업 디렉토리 이동
SKILL_ROOT = os.path.dirname(os.path.dirname(PIPELINE))
os.chdir(SKILL_ROOT)

if __name__ == "__main__":
    # CLI 인자(topic, days)도 하위 프로세스에 그대로 전달
    sys.exit(subprocess.call([VENV_PYTHON, "-u", PIPELINE] + sys.argv[1:]))
