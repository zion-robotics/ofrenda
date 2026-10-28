@echo off
cd /d "%~dp0"
python ofrenda.py %* --html offering.html
if exist offering.html start "" offering.html
pause
