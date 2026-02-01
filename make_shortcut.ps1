$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("c:\Users\Tomek\Projects\portfolio-dashboard-2026\Mobile Access.lnk")
$Shortcut.TargetPath = "cmd.exe"
$Shortcut.Arguments = "/c ""c:\Users\Tomek\Projects\portfolio-dashboard-2026\start_mobile_access.bat"""
$Shortcut.WorkingDirectory = "c:\Users\Tomek\Projects\portfolio-dashboard-2026"
$Shortcut.IconLocation = "C:\Windows\System32\shell32.dll,220"
$Shortcut.Save()
Write-Host "Shortcut created successfully at $($Shortcut.FullName)"
