@echo off
REM research_pipeline.bat - Windows 배치 래퍼
REM 매일 새벽 4시 cronjob용 진입점
REM Hermes 루트 .env에서 SLACK_BOT_TOKEN을 로드한 후 파이프라인 실행

cd /d "%~dp0"

REM Hermes 루트 .env에서 SLACK_BOT_TOKEN 추출
set HERMES_HOME=%USERPROFILE%\AppData\Local\hermes
findstr /B "SLACK_BOT_TOKEN=" "%HERMES_HOME%\.env" > %TEMP%\slack_env.tmp 2>nul
if %ERRORLEVEL% EQU 0 (
    for /f "tokens=2 delims==" %%a in ('type %TEMP%\slack_env.tmp') do (
        set "SLACK_BOT_TOKEN=%%a"
    )
    del %TEMP%\slack_env.tmp
)

REM Python 실행
"C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" -u "C:\Users\user\AppData\Local\hermes\skills\research\research_new\scripts\research_pipeline.py" %*

echo %ERRORLEVEL%
