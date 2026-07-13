param(
    [string]$TaskName = "Dashboard Analytics Local Brain Autosync",
    [int]$IntervalMinutes = 15,
    [int]$ChangedFilesLimit = 10,
    [int]$EmbedMaxChunks = 500,
    [int]$EmbedBatchSize = 1,
    [double]$EmbedSleep = 3,
    [string]$MaxBytes = "50MB",
    [int]$MaxPdfPages = 300,
    [int]$MaxExtractedChars = 750000,
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $RepoRoot "run_local_brain_autosync.ps1"
$LoopRunner = Join-Path $RepoRoot "run_local_brain_autosync_loop.ps1"

if (!(Test-Path -LiteralPath $Runner)) {
    throw "Autosync runner not found: $Runner"
}
if (!(Test-Path -LiteralPath $LoopRunner)) {
    throw "Autosync loop runner not found: $LoopRunner"
}

$quotedRunner = '"' + $Runner + '"'
$argument = "-NoProfile -ExecutionPolicy Bypass -File $quotedRunner " +
    "-ChangedFilesLimit $ChangedFilesLimit " +
    "-EmbedMaxChunks $EmbedMaxChunks " +
    "-EmbedBatchSize $EmbedBatchSize " +
    "-EmbedSleep $EmbedSleep " +
    "-MaxBytes $MaxBytes " +
    "-MaxPdfPages $MaxPdfPages " +
    "-MaxExtractedChars $MaxExtractedChars"

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $RepoRoot
$minuteTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger @($minuteTrigger, $logonTrigger) `
        -Settings $settings `
        -Description "Indexes the local synced Google Drive brain folder into Supabase and embeds new chunks." `
        -Force | Out-Null

    if ($RunNow) {
        Start-ScheduledTask -TaskName $TaskName
    }

    Write-Output "Installed scheduled task: $TaskName"
    Write-Output "Interval: every $IntervalMinutes minute(s), plus at Windows logon."
    Write-Output "Logs: $RepoRoot\outputs\local_brain_autosync.log"
} catch {
    $runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $runName = "DashboardAnalyticsLocalBrainAutosync"
    $quotedLoopRunner = '"' + $LoopRunner + '"'
    $runCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $quotedLoopRunner " +
        "-IntervalMinutes $IntervalMinutes " +
        "-ChangedFilesLimit $ChangedFilesLimit " +
        "-EmbedMaxChunks $EmbedMaxChunks " +
        "-EmbedBatchSize $EmbedBatchSize " +
        "-EmbedSleep $EmbedSleep " +
        "-MaxBytes $MaxBytes " +
        "-MaxPdfPages $MaxPdfPages " +
        "-MaxExtractedChars $MaxExtractedChars"

    New-Item -Path $runKey -Force | Out-Null
    Set-ItemProperty -Path $runKey -Name $runName -Value $runCommand

    if ($RunNow) {
        Start-Process powershell.exe `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $quotedLoopRunner -IntervalMinutes $IntervalMinutes -ChangedFilesLimit $ChangedFilesLimit -EmbedMaxChunks $EmbedMaxChunks -EmbedBatchSize $EmbedBatchSize -EmbedSleep $EmbedSleep -MaxBytes $MaxBytes -MaxPdfPages $MaxPdfPages -MaxExtractedChars $MaxExtractedChars" `
            -WindowStyle Hidden
    }

    Write-Output "Task Scheduler install failed, so installed per-user startup autosync instead."
    Write-Output "Startup key: HKCU\Software\Microsoft\Windows\CurrentVersion\Run\$runName"
    Write-Output "Interval: every $IntervalMinutes minute(s) while Windows is logged in."
    Write-Output "Logs: $RepoRoot\outputs\local_brain_autosync.log"
}
