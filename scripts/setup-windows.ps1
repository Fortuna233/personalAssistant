param(
    [string]$Library = "D:\StudyLibrary",
    [string]$BindAddress = "127.0.0.1"
)
$ErrorActionPreference = "Stop"
$Project = Split-Path $PSScriptRoot -Parent
Set-Location $Project
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "请先安装 Python 3.11 或更新版，并启用 Python Launcher。" }
py -3 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败" }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "安装依赖失败" }
foreach ($Folder in @("Notes", "Books", "Experiments")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Library $Folder) | Out-Null
}
New-Item -ItemType Directory -Force -Path "runtime" | Out-Null
if (-not (Test-Path "config/local.json")) {
    $Bytes = New-Object byte[] 32
    $Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $Rng.GetBytes($Bytes)
    $Rng.Dispose()
    $Config = @{
        library = $Library
        database = "runtime/assistant.db"
        host = $BindAddress
        port = 8765
        token = [Convert]::ToBase64String($Bytes)
        scan_seconds = 60
    }
    $Json = $Config | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $Project "config/local.json"), $Json, (New-Object Text.UTF8Encoding($false)))
}
Write-Host "安装完成。访问密钥保存在 config/local.json，请勿分享或提交 Git。"
Write-Host "启动：.\.venv\Scripts\python.exe -m assistant --config config/local.json"
Write-Host "默认仅本机访问；校园网监听可重新安装时指定 -BindAddress 0.0.0.0，已有配置需手动修改。"
