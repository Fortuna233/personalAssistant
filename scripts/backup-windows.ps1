param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = "Stop"
$Project = Split-Path $PSScriptRoot -Parent
& "$Project\.venv\Scripts\python.exe" "$PSScriptRoot\backup.py" --config "$Project\config\local.json" --destination $Destination
if ($LASTEXITCODE -ne 0) { throw "备份失败" }
