@echo off
echo.
echo === Your Local IP Addresses ===
echo.
ipconfig | findstr /i "ipv4"
echo.
echo Use one of the IP addresses above to access the dashboard from your phone.
echo Example URL: http://192.168.1.X:5173
echo.
pause
