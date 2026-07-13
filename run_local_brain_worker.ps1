param(
    [ValidateSet("all", "index", "embed", "status")]
    [string]$Mode = "all",

    [string]$Root = $env:BRAIN_LOCAL_LIBRARY_DIR,
    [string]$MaxBytes = "250MB",
    [int]$MaxPdfPages = 2000,
    [int]$MaxExtractedChars = 5000000,
    [int]$ChangedFilesLimit = 25,
    [int]$EmbedMaxChunks = 250,
    [int]$EmbedBatchSize = 1,
    [double]$EmbedSleep = 3,
    [double]$WatchMinutes = 0,
    [switch]$Force,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Worker = Join-Path $RepoRoot "backend\local_brain_worker.py"

$workerArgs = @(
    $Worker,
    "--mode", $Mode,
    "--max-bytes", $MaxBytes,
    "--max-pdf-pages", "$MaxPdfPages",
    "--max-extracted-chars", "$MaxExtractedChars",
    "--changed-files-limit", "$ChangedFilesLimit",
    "--embed-max-chunks", "$EmbedMaxChunks",
    "--embed-batch-size", "$EmbedBatchSize",
    "--embed-sleep", "$EmbedSleep"
)

if ($Root) {
    $workerArgs += @("--root", $Root)
}

if ($WatchMinutes -gt 0) {
    $workerArgs += @("--watch-minutes", "$WatchMinutes")
}

if ($Force) {
    $workerArgs += "--force"
}

if ($Json) {
    $workerArgs += "--json"
}

python @workerArgs
