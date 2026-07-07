param(
    [string]$TaskName = "Dashboard Analytics Local Brain Autosync",
    [string]$RunName = "DashboardAnalyticsLocalBrainAutosync"
)

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed scheduled task: $TaskName"
} else {
    Write-Output "Scheduled task not found: $TaskName"
}

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$runValue = Get-ItemProperty -Path $runKey -Name $RunName -ErrorAction SilentlyContinue
if ($runValue) {
    Remove-ItemProperty -Path $runKey -Name $RunName
    Write-Output "Removed startup autosync: $RunName"
} else {
    Write-Output "Startup autosync not found: $RunName"
}
