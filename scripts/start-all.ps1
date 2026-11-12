# 开机/登录自启包装（供计划任务调用）
# 挂载方式：schtasks /Create /TN "IPSimWorkbench-AutoStart" /SC ONLOGON /TR "...start-all.ps1" /F
# start-local-windows.ps1 会拉起：Ollama / AnythingLLM / MySQL / MinIO / backend / frontend
# 已在监听的端口会跳过，不会重复启动。
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "[start-all] $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') 启动工作台..."
& (Join-Path $Root "scripts\start-local-windows.ps1")
Write-Host "[start-all] 完成"
