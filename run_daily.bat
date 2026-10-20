@echo off
rem Daily JobAgent run. Edit PYTHON to the full path from:  where python
set PYTHON=python
cd /d "%~dp0"
if not exist logs mkdir logs
%PYTHON% run_daily.py >> logs\run_daily.log 2>&1
