param(
    [int]$ChangedFilesLimit = 10,
    [int]$EmbedMaxChunks = 500,
    [int]$EmbedBatchSize = 50,
    [double]$EmbedSleep = 3,
    [string]$MaxBytes = "50MB",
    [int]$MaxPdfPages = 300,
    [int]$MaxExtractedChars = 750000,
    [int]$StaleLockHours = 6
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputDir = Join-Path $RepoRoot "outputs"
$LogPath = Join-Path $OutputDir "local_brain_autosync.log"
$LockPath = Join-Path $OutputDir "local_brain_autosync.lock"

if (!(Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

function Write-AutosyncLog {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LogPath -Value "[$stamp] $Message" -Encoding UTF8
}

if (Test-Path -LiteralPath $LockPath) {
    $lockAge = (Get-Date) - (Get-Item -LiteralPath $LockPath).LastWriteTime
    $lockPid = (Get-Content -LiteralPath $LockPath -ErrorAction SilentlyContinue | Select-Object -First 1)
    $lockProcess = $null
    if ($lockPid -match '^\d+$') {
        $lockProcess = Get-Process -Id ([int]$lockPid) -ErrorAction SilentlyContinue
    }

    if ($lockProcess -and $lockAge.TotalHours -lt $StaleLockHours) {
        Write-AutosyncLog "Skipped: previous worker still running as PID $lockPid."
        exit 0
    }

    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}

$PID | Set-Content -LiteralPath $LockPath -Encoding ASCII

try {
    Write-AutosyncLog "Starting local brain autosync."
    & (Join-Path $RepoRoot "run_local_brain_worker.ps1") `
        -Mode all `
        -ChangedFilesLimit $ChangedFilesLimit `
        -EmbedMaxChunks $EmbedMaxChunks `
        -EmbedBatchSize $EmbedBatchSize `
        -EmbedSleep $EmbedSleep `
        -MaxBytes $MaxBytes `
        -MaxPdfPages $MaxPdfPages `
        -MaxExtractedChars $MaxExtractedChars `
        -Json *>> $LogPath
    Write-AutosyncLog "Finished local brain autosync."
} catch {
    Write-AutosyncLog "Failed: $($_.Exception.Message)"
    exit 1
} finally {
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}
