param(
    [int]$IntervalMinutes = 15,
    [int]$ChangedFilesLimit = 10,
    [int]$EmbedMaxChunks = 500,
    [int]$EmbedBatchSize = 1,
    [double]$EmbedSleep = 3,
    [string]$MaxBytes = "50MB",
    [int]$MaxPdfPages = 300,
    [int]$MaxExtractedChars = 750000
)

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $RepoRoot "run_local_brain_autosync.ps1"
$OutputDir = Join-Path $RepoRoot "outputs"
$LoopLog = Join-Path $OutputDir "local_brain_autosync_loop.log"

if (!(Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

function Write-LoopLog {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LoopLog -Value "[$stamp] $Message" -Encoding UTF8
}

$sleepSeconds = [Math]::Max(60, $IntervalMinutes * 60)
Write-LoopLog "Started local brain autosync loop. Interval: $IntervalMinutes minute(s)."

while ($true) {
    try {
        & $Runner `
            -ChangedFilesLimit $ChangedFilesLimit `
            -EmbedMaxChunks $EmbedMaxChunks `
            -EmbedBatchSize $EmbedBatchSize `
            -EmbedSleep $EmbedSleep `
            -MaxBytes $MaxBytes `
            -MaxPdfPages $MaxPdfPages `
            -MaxExtractedChars $MaxExtractedChars
    } catch {
        Write-LoopLog "Autosync run failed: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds $sleepSeconds
}
