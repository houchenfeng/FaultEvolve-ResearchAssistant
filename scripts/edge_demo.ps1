# 本地-云端混合演示一键启动：后端（含 /api/edge 与平板网页）+ 工作台前端。
#
#   powershell -ExecutionPolicy Bypass -File scripts\edge_demo.ps1
#
# 平板与笔记本需在同一局域网；首次运行请以管理员身份放行 8011 端口：
#   New-NetFirewallRule -DisplayName FaultEvolveEdge -Direction Inbound -Protocol TCP -LocalPort 8011 -Action Allow
param(
    [int]$ApiPort = 8011,
    [int]$WebPort = 5180
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

$backend = "`$env:PYTHONUTF8='1'; Set-Location '$repo'; & '$python' scripts/showcase_serve.py --host 0.0.0.0 --port $ApiPort"
Start-Process powershell -ArgumentList '-NoExit', '-Command', $backend -WindowStyle Minimized

$web = "`$env:VITE_API_PROXY_TARGET='http://127.0.0.1:$ApiPort'; `$env:VITE_DEV_PORT='$WebPort'; Set-Location '$repo\web'; pnpm dev --host 0.0.0.0"
Start-Process powershell -ArgumentList '-NoExit', '-Command', $web -WindowStyle Minimized

$ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.|198\.1[89]\.)' -and $_.PrefixOrigin -ne 'WellKnown' } |
    Select-Object -ExpandProperty IPAddress

Write-Host ''
Write-Host '路演演示（EvoBot）：' -NoNewline; Write-Host " http://127.0.0.1:$WebPort/" -ForegroundColor Cyan
Write-Host '混合云模式：      ' -NoNewline; Write-Host " http://127.0.0.1:$WebPort/?stage=hybrid" -ForegroundColor Cyan
foreach ($ip in $ips) {
    Write-Host '平板 APK 填写地址：' -NoNewline; Write-Host " ${ip}:$ApiPort" -ForegroundColor Green
    Write-Host '平板浏览器版：    ' -NoNewline; Write-Host " http://${ip}:$ApiPort/edge-tablet/" -ForegroundColor Green
}
