# 一键上传并编译（在 Windows PowerShell 里运行）
# 用法： cd D:\课设\deploy ; .\upload.ps1
#       或 .\upload.ps1 -RobotIp 10.224.117.14

param(
    [string]$RobotIp = "10.224.117.14",
    [string]$User    = "root"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot   # D:\课设
Set-Location $root

Write-Host "==> 定位机器人工作空间" -ForegroundColor Cyan
$detect = 'P=$(find $HOME /home /opt -maxdepth 4 -type d -name bobac2_base 2>/dev/null | head -1); if [ -n "$P" ]; then dirname $(dirname $P); else echo $HOME/bobac2_ws; fi'
$ws = (ssh "${User}@${RobotIp}" "bash -lc '$detect'").Trim()
if (-not $ws) { throw "无法定位 ~/bobac2_ws，请手动检查" }
Write-Host "    工作空间 = $ws" -ForegroundColor Green

Write-Host "==> 上传两个 ROS 包" -ForegroundColor Cyan
scp -O -r .\bobac2_face .\practicum_manager "${User}@${RobotIp}:$ws/src/"

Write-Host "==> 上传控制脚本" -ForegroundColor Cyan
scp -O .\deploy\practicum.sh     "${User}@${RobotIp}:~/practicum.sh"
scp -O .\deploy\robot_install.sh "${User}@${RobotIp}:~/robot_install.sh"

Write-Host "==> 远程编译（会再要一次密码）" -ForegroundColor Cyan
ssh "${User}@${RobotIp}" "chmod +x ~/practicum.sh && bash ~/robot_install.sh"

Write-Host "==> 完成。现在双击 D:\课设\console\启动控制台.bat" -ForegroundColor Green
