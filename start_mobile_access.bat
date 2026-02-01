@echo off
echo Starting Mobile Access Tunnel...
echo This will generate a QR code for your phone.
echo.
cd /d "%~dp0"
python share_dashboard.py
pause
