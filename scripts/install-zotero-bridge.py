"""Generate reviewable per-user startup files; never alter login settings automatically."""

import argparse
import plistlib
import subprocess
import sys
from pathlib import Path


def powershell_literal(value):
    return "'" + value.replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", default="runtime/bridge-startup")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    config = Path(args.config).resolve()
    if not config.is_file():
        parser.error("请先创建桥接配置文件")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    arguments = [str(project / "scripts/zotero_bridge.py"), "--config", str(config), "--watch"]
    label = "cn.shenqingti.zotero-bridge"
    plist = {
        "Label": label,
        "ProgramArguments": [sys.executable, *arguments],
        "WorkingDirectory": str(project),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 60,
        "StandardOutPath": str(output / "bridge.log"),
        "StandardErrorPath": str(output / "bridge-error.log"),
    }
    mac = output / (label + ".plist")
    mac.write_bytes(plistlib.dumps(plist))
    win = output / "register-bridge.ps1"
    win.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        + "$Action = New-ScheduledTaskAction -Execute "
        + powershell_literal(sys.executable)
        + " -Argument "
        + powershell_literal(subprocess.list2cmdline(arguments))
        + " -WorkingDirectory "
        + powershell_literal(str(project))
        + "\n"
        + "$Trigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)\n"
        + "$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 20 -RestartInterval (New-TimeSpan -Minutes 1)\n"
        + "Register-ScheduledTask -TaskName 'ShenQingTiZoteroBridge' -Action $Action -Trigger $Trigger -Settings $Settings\n",
        encoding="utf-8-sig",
    )
    print("已生成启动文件（尚未安装）：", output)
    print(
        "Mac：将 plist 复制到 ~/Library/LaunchAgents/ 后运行 launchctl bootstrap gui/$(id -u) <plist绝对路径>"
    )
    print("Windows：在本机生成后，用 PowerShell 执行", win)
    print("只安装对应本机系统的文件；Zotero 桌面程序也需登录后启动。")


if __name__ == "__main__":
    main()
