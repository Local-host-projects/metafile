@echo off
rem Metafile server -- dual-stack on the default port 8000.
rem Serves http://localhost:8000 and http://127.0.0.1:8000 (IPv4 + IPv6 + LAN).
cd /d "%~dp0backend"
echo Starting Metafile on http://localhost:8000 ...
python run.py
pause
