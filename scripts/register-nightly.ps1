<#
.SYNOPSIS
Registers (or updates) the nightly hoopdata Task Scheduler job.

.DESCRIPTION
The task runs plain `hoopdata ingest` daily at 6am, which keeps the data root's saved
selection current. If the PC was off or asleep at 6am, it runs as soon as possible
afterwards. The task runs uv directly, so
the CLI's exit code becomes the task's Last Run Result (non-zero when items failed).

.PARAMETER DataRoot
Where data is written. Defaults to $env:NBA_DATA_ROOT.

.EXAMPLE
.\scripts\register-nightly.ps1 -DataRoot D:\nba-data

.EXAMPLE
.\scripts\register-nightly.ps1 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$DataRoot = $env:NBA_DATA_ROOT
)

$ErrorActionPreference = "Stop"
$TaskName = "hoopdata nightly ingest"

if (-not $DataRoot) {
    throw "Pass -DataRoot or set NBA_DATA_ROOT."
}
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Uv = (Get-Command uv).Source

$action = New-ScheduledTaskAction `
    -Execute $Uv `
    -Argument "run --project `"$RepoRoot`" hoopdata ingest --data-root `"$DataRoot`"" `
    -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At 6am
# Local time without a UTC offset, so the task stays at 6am across daylight saving changes.
$trigger.StartBoundary = (Get-Date 6am).ToString("s")
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable

if ($PSCmdlet.ShouldProcess($TaskName, "Register daily 6am task running: $Uv $($action.Arguments)")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "Registered '$TaskName': daily at 6am, data root $DataRoot"
}
