$WshShell = New-Object -comObject WScript.Shell
while ($true) {
    # Send F15 key every 60 seconds (F15 is usually harmless/ignored by apps)
    $WshShell.SendKeys("{F15}")
    Start-Sleep -Seconds 60
}
