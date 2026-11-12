# Check local workbench services (four-piece + Ollama + AnythingLLM + knowledge health)
# Usage: .\scripts\status.ps1
# 端口探测必须用 TCP 连接 127.0.0.1，不要用 Get-NetTCPConnection（无管理员时常空结果误报 DOWN）。
$o = @()
function Test-Listening($Port) {
  $client = $null
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect("127.0.0.1", [int]$Port, $null, $null)
    $ok = $iar.AsyncWaitHandle.WaitOne(400, $false)
    if (-not $ok) { return $false }
    $client.EndConnect($iar) | Out-Null
    return $true
  } catch {
    return $false
  } finally {
    if ($client) { try { $client.Close() } catch {} }
  }
}
function Check-Port($Port, $Label) {
  if (Test-Listening $Port) { $script:o += ("  [OK]   " + $Label + " (" + $Port + ")") }
  else { $script:o += ("  [DOWN] " + $Label + " (" + $Port + ")") }
}
$o += "== Windows local services =="
Check-Port 13307 "MySQL"
Check-Port 9002 "MinIO API"
Check-Port 8000 "Backend"
Check-Port 5173 "Frontend"
Check-Port 11434 "Ollama"
Check-Port 3001 "AnythingLLM"
$o += "== Backend health =="
try {
  $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/health" -UseBasicParsing -TimeoutSec 20
  $o += "  " + $r.Content
} catch { $o += "  health unavailable: " + $_.Exception.Message }
$o += "== Knowledge health =="
try {
  # 账号口令从根 .env 读取（禁止把明文口令写进仓库）；缺配置则跳过知识库检查
  $Root = Split-Path -Parent $PSScriptRoot
  $EnvFile = Join-Path $Root ".env"
  $AdminUser = "admin"; $AdminPass = ""
  if (Test-Path $EnvFile) {
    $u = Select-String -Path $EnvFile -Pattern "^ADMIN_USERNAME=" | Select-Object -First 1
    $p = Select-String -Path $EnvFile -Pattern "^ADMIN_PASSWORD=" | Select-Object -First 1
    if ($u) { $AdminUser = $u.Line.Substring("ADMIN_USERNAME=".Length).Trim() }
    if ($p) { $AdminPass = $p.Line.Substring("ADMIN_PASSWORD=".Length).Trim() }
  }
  if (-not $AdminPass) { throw "根 .env 未配置 ADMIN_PASSWORD，跳过知识库检查" }
  $loginBody = (@{ username = $AdminUser; password = $AdminPass } | ConvertTo-Json -Compress)
  $login = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/auth/login" -Method POST -Body $loginBody -ContentType "application/json" -UseBasicParsing -TimeoutSec 15
  $token = ($login.Content | ConvertFrom-Json).access_token
  $kh = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/ai/knowledge/health" -Headers @{ Authorization = "Bearer $token" } -UseBasicParsing -TimeoutSec 20
  $parsed = $kh.Content | ConvertFrom-Json
  $o += ("  available=" + $parsed.available + " document_count=" + $parsed.document_count + " provider=" + $parsed.provider + " workspace=" + $parsed.workspace_slug)
} catch { $o += "  knowledge health unavailable: " + $_.Exception.Message }
$o -join "`n"
