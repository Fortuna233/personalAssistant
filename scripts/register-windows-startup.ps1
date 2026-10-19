param([Parameter(Mandatory=$true)][string]$SyncthingExe)
$ErrorActionPreference = "Stop"
$Project = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $Project ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "请先运行 setup-windows.ps1" }
$SyncthingExe = (Resolve-Path $SyncthingExe).Path
$User = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType S4U -RunLevel Limited
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 20 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$AppAction = New-ScheduledTaskAction -Execute $Python -Argument "-m assistant --config `"$Project\config\local.json`"" -WorkingDirectory $Project
$SyncAction = New-ScheduledTaskAction -Execute $SyncthingExe -Argument "serve --no-browser --no-restart" -WorkingDirectory (Split-Path $SyncthingExe -Parent)
Register-ScheduledTask -TaskName "StudyHarbor" -Action $AppAction -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
Register-ScheduledTask -TaskName "StudySyncthing" -Action $SyncAction -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
powercfg /change standby-timeout-ac 0
Start-ScheduledTask -TaskName "StudyHarbor"
Start-ScheduledTask -TaskName "StudySyncthing"
Write-Host "已配置开机任务及接通电源不休眠。S4U 任务仅使用本地目录；请重启并在未登录状态验证。"
