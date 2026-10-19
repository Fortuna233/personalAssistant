param([Parameter(Mandatory=$true)][string]$Server)
Write-Host "阅读网页 8765："
Test-NetConnection -ComputerName $Server -Port 8765
Write-Host "同步服务 22000："
Test-NetConnection -ComputerName $Server -Port 22000
Write-Host "如果失败，请检查主机防火墙、校园网设备隔离及主机地址。不要开启公网端口映射。"
