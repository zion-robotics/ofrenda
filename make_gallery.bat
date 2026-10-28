@echo off
cd /d "%~dp0"
python make_gallery.py %*
if exist gallery\index.html start "" gallery\index.html
pause
