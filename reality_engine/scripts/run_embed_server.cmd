@echo off
REM ---------------------------------------------------------------------------
REM Vulkan-only embedding server (bge-small-en-v1.5-q8_0, :8099).
REM Single-run contract: hub owns restart (detached+persist). No respawn loop
REM here, otherwise hub and cmd double-spawn on :8099.
REM
REM Defaults resolve relative to this script; env overrides win:
REM   EM_BIN   - llama-server.exe path
REM   EM_MODEL - bge-small-en-v1.5-q8_0.gguf path
REM   EM_HOST / EM_PORT - bind address and port
REM ---------------------------------------------------------------------------
if not defined EM_HOST set EM_HOST=127.0.0.1
if not defined EM_PORT set EM_PORT=8099
if not defined EM_MODEL set EM_MODEL=%~dp0..\data\models\gguf\bge-small-en-v1.5-q8_0.gguf
REM EM_BIN default is this box's install; override via env on any other box.
if not defined EM_BIN set EM_BIN=C:\Users\warri\prism-llama-bonsai2\llama-server.exe
"%EM_BIN%" --model "%EM_MODEL%" --host %EM_HOST% --port %EM_PORT% ^
  --threads 8 --ctx-size 2048 --embedding --pooling mean -ngl 99
