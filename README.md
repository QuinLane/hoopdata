# hoopdata

## Nightly update

`scripts/register-nightly.ps1` registers a Windows Task Scheduler job, "hoopdata nightly ingest". It runs plain `hoopdata ingest` daily at 6am, which keeps the data root's saved selection current, so run `hoopdata ingest --season ...` or `--all-seasons` once first. If the PC was off or asleep at 6am, the job runs as soon as possible afterwards. The task's Last Run Result is non-zero when any item failed, and each run writes a log under the data root.

Set up (needs [uv](https://docs.astral.sh/uv/) on your PATH). Run it again to update the task, for example after moving the repo:

```powershell
.\scripts\register-nightly.ps1 -DataRoot D:\nba-data
# or, with NBA_DATA_ROOT set:
.\scripts\register-nightly.ps1
# see what it would register, without registering:
.\scripts\register-nightly.ps1 -DataRoot D:\nba-data -WhatIf
```

The task runs as you, only while you are logged on.

Remove:

```powershell
Unregister-ScheduledTask -TaskName "hoopdata nightly ingest" -Confirm:$false
```
