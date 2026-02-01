$WshShell = New-Object -comObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "Portfolio Dashboard.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
# Targeting cmd.exe allows pinning to Taskbar
$Shortcut.TargetPath = "C:\Windows\System32\cmd.exe"
$Shortcut.Arguments = "/c ""C:\Users\Tomek\Projects\portfolio-dashboard-2026\start_dashboard.bat"""
$Shortcut.WindowStyle = 7
# Try to find Chrome icon, fallback to cmd if not found
if (Test-Path "C:\Program Files\Google\Chrome\Application\chrome.exe") {
    $Shortcut.IconLocation = "C:\Program Files\Google\Chrome\Application\chrome.exe,0"
}
$Shortcut.Save()
Write-Host "Shortcut created at $ShortcutPath"
