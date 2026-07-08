$WshShell = New-Object -comObject WScript.Shell
$ProjectRoot = $PSScriptRoot
$ShortcutPath = Join-Path $ProjectRoot "Mobile Access.lnk"
$LauncherPath = Join-Path $ProjectRoot "start_mobile_access.bat"
$IconPath = Join-Path $ProjectRoot "donkey.ico"

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "cmd.exe"
$Shortcut.Arguments = "/c ""$LauncherPath"""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.IconLocation = $IconPath
$Shortcut.Save()
Write-Host "Shortcut updated with new icon at $($Shortcut.FullName)"
