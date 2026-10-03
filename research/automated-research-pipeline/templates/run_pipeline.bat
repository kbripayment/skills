@echo off
REM Windows batch wrapper for research pipeline cronjobs.
REM Loads SLACK_BOT_TOKEN from Hermes root .env, then runs the Python pipeline.
REM
REM Usage: Place at C:\Users\user\AppData\Local\hermes\scripts\run_research_pipeline.bat
REM Cronjob script path: use this batch file as the cron --script argument.

cd /d "%~dp0"

REM Extract SLACK_BOT_TOKEN from Hermes root .env
for /f "tokens=*" %%i in ('findstr "SLACK_BOT_TOKEN" "C:\Users\user\AppData\Local\hermes\.env" 2^>nul') do set %%i

REM Run pipeline (Python venv path may vary per environment)
"C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" scripts/research_pipeline.py

REM Exit with Python's exit code
exit /b %ERRORLEVEL%
