$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("c:\Users\Tomek\Projects\portfolio-dashboard-2026\Mobile Access.lnk")
$Shortcut.TargetPath = "cmd.exe"
$Shortcut.Arguments = "/c ""c:\Users\Tomek\Projects\portfolio-dashboard-2026\start_mobile_access.bat"""
$Shortcut.WorkingDirectory = "c:\Users\Tomek\Projects\portfolio-dashboard-2026"
$Shortcut.IconLocation = "c:\Users\Tomek\Projects\portfolio-dashboard-2026\donkey.ico"
$Shortcut.Save()
Write-Host "Shortcut updated with new icon at $($Shortcut.FullName)"
