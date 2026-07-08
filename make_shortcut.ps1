$WshShell = New-Object -comObject WScript.Shell
$ProjectRoot = $PSScriptRoot
$ShortcutPath = Join-Path $ProjectRoot "Mobile Access.lnk"
$LauncherPath = Join-Path $ProjectRoot "start_mobile_access.bat"

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "cmd.exe"
$Shortcut.Arguments = "/c ""$LauncherPath"""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.IconLocation = "C:\Windows\System32\shell32.dll,220"
$Shortcut.Save()
Write-Host "Shortcut created successfully at $($Shortcut.FullName)"
