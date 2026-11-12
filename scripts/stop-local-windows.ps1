# 停止工作台四件套（MySQL/MinIO/后端/前端）——只杀本项目相关进程
# 用法: .\scripts\stop-local-windows.ps1
#       .\scripts\stop-local-windows.ps1 -IncludeKnowledge   # 同时停 Ollama / AnythingLLM
param(
  [switch]$IncludeKnowledge
)
$ErrorActionPreference = "Continue"

function Stop-ByPort($Port, $Label, $AllowedNames) {
  $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $conn) { Write-Host "[stop] $Label ($Port) 未运行"; return }
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
  if (-not $proc) { Write-Host "[stop] $Label ($Port) 进程不存在"; return }
  $name = $proc.Name.ToLower()
  $cmd = ($proc.CommandLine + "").ToLower()
  $match = $false
  foreach ($n in $AllowedNames) {
    if ($name -eq $n) { $match = $true; break }
  }
  if (-not $match) {
    if ($Label -eq "Backend" -and $cmd -match "uvicorn main:app") { $match = $true }
    if ($Label -eq "Frontend" -and $name -eq "node.exe" -and $cmd -match "vite") { $match = $true }
  }
  if (-not $match) { Write-Host "[stop] $Label ($Port) 被非本项目进程占用: $name，跳过"; return }
  Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
  Write-Host "[stop] $Label ($Port) 已停止 (PID $($proc.ProcessId))"
}

Stop-ByPort 13307 "MySQL" @("mysqld.exe")
Stop-ByPort 9002   "MinIO" @("minio.exe")
Stop-ByPort 8000   "Backend" @("python.exe", "pythonw.exe")
Stop-ByPort 5173   "Frontend" @("node.exe")
if ($IncludeKnowledge) {
  Stop-ByPort 11434 "Ollama" @("ollama.exe")
  Stop-ByPort 3001 "AnythingLLM" @("anythingllm.exe")
} else {
  Write-Host "[stop] 未停 Ollama/AnythingLLM（桌面应用，加 -IncludeKnowledge 才会停）"
}
Write-Host "[stop] 完成"
