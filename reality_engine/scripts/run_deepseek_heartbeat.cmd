@echo off
rem DeepSeek heartbeat, hourly (Task Scheduler: RealityEngine-DeepSeekHeartbeat). Wakes DeepSeek only, never Claude.
rem Restarts dead transcript readers (no LLM), then off-peak (15:30-06:30 IST) runs one DeepSeek check; see
rem reality_engine\scripts\deepseek_heartbeat.py. Log: reality_engine\data\logs\deepseek_heartbeat.log
cd /d "%~dp0\..\.."
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.deepseek_heartbeat >> reality_engine\data\logs\deepseek_heartbeat.log 2>&1
