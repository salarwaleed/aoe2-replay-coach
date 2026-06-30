@echo off
REM ============================================================
REM Nightly synthesis job (TELEMETRY_PLAN.md sec 2, stage 2).
REM
REM Runs Pipeline 2 (raw ChromaDB chunks -> DynamoDB timelines) then
REM Pipeline 3 (DynamoDB timelines -> Ollama synthesis -> MinIO/S3 profiles),
REM in sequence, intended to run unattended overnight via Windows Task
REM Scheduler (~3 AM). See docs\NIGHTLY_SYNTHESIS_SETUP.md for how to
REM register it.
REM
REM Runs OUTSIDE the bot process by design: it must complete even if the
REM Discord bot itself is down, and it uses a much larger/slower local LLM
REM (qwen2.5:7b) than is appropriate to run inside the bot's event loop.
REM
REM Requires: chromadb (:8000), dynamodb-local (:8001), minio (:9000), and
REM ollama (:11434) all already running (see infra\docker-compose.yml and
REM `ollama serve`) before this script fires -- it does not start them.
REM ============================================================

setlocal

REM Resolve the worktree root as the directory this .bat file lives in, so
REM the job works regardless of the cwd Task Scheduler launches it from.
set "PROJECT_ROOT=%~dp0"
REM Strip the trailing backslash %~dp0 always leaves.
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

REM Shared pipeline virtualenv interpreter (see pipeline\README.md -- always
REM install pipeline deps into this dedicated venv, never globally). This is
REM the same venv used for manual "python -m pipeline.pipelineN_..." runs.
set "PYTHON_EXE=D:\my-portfolio\discord bot\.venv\Scripts\python.exe"

set "LOG_DIR=%PROJECT_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM One timestamped log per run. %DATE%/%TIME% are locale-dependent but fine
REM here since they're only used to build a sortable-enough unique filename,
REM not parsed back out.
set "TS=%DATE%_%TIME%"
set "TS=%TS::=-%"
set "TS=%TS: =0%"
set "TS=%TS:/=-%"
set "TS=%TS:.=-%"
set "LOG_FILE=%LOG_DIR%\nightly_synthesis_%TS%.log"

echo ============================================================ > "%LOG_FILE%"
echo Nightly synthesis run started %DATE% %TIME% >> "%LOG_FILE%"
echo Project root : %PROJECT_ROOT% >> "%LOG_FILE%"
echo Python       : %PYTHON_EXE% >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"

cd /d "%PROJECT_ROOT%"

echo. >> "%LOG_FILE%"
echo --- Pipeline 2: telemetry (chunks -^> DynamoDB) --- >> "%LOG_FILE%"
"%PYTHON_EXE%" -m pipeline.pipeline2_telemetry >> "%LOG_FILE%" 2>&1
set "P2_EXIT=%ERRORLEVEL%"
echo Pipeline 2 exit code: %P2_EXIT% >> "%LOG_FILE%"

if not "%P2_EXIT%"=="0" (
    echo. >> "%LOG_FILE%"
    echo Pipeline 2 FAILED ^(exit %P2_EXIT%^) - skipping Pipeline 3. >> "%LOG_FILE%"
    echo Nightly synthesis run FAILED at %DATE% %TIME% >> "%LOG_FILE%"
    exit /b %P2_EXIT%
)

echo. >> "%LOG_FILE%"
echo --- Pipeline 3: profile synthesis (DynamoDB -^> Ollama -^> MinIO/S3) --- >> "%LOG_FILE%"
"%PYTHON_EXE%" -m pipeline.pipeline3_profiles --all >> "%LOG_FILE%" 2>&1
set "P3_EXIT=%ERRORLEVEL%"
echo Pipeline 3 exit code: %P3_EXIT% >> "%LOG_FILE%"

echo. >> "%LOG_FILE%"
if "%P3_EXIT%"=="0" (
    echo Nightly synthesis run COMPLETED OK at %DATE% %TIME% >> "%LOG_FILE%"
) else (
    echo Nightly synthesis run FAILED at %DATE% %TIME% >> "%LOG_FILE%"
)

exit /b %P3_EXIT%
