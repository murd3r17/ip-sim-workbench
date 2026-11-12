# Local Windows runtime helpers (no Docker / no eNSP)
# Data & logs: .runtime\

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $Root "backend"))) {
  throw "找不到 backend 目录（$Root）。请从仓库根目录运行本脚本。"
}
$Runtime = Join-Path $Root ".runtime"
$Log = Join-Path $Runtime "logs"
$Mysqld = Join-Path $Runtime "mysql-server\bin\mysqld.exe"
$Ini = Join-Path $Runtime "my.ini"
$Py = Join-Path $Root "backend\.venv\Scripts\python.exe"
$Npm = (Get-Command npm.cmd).Source

New-Item -ItemType Directory -Force -Path $Log | Out-Null

function Get-EnvValue($Key) {
  $envFile = Join-Path $Root ".env"
  if (Test-Path $envFile) {
    $line = Select-String -Path $envFile -Pattern "^$Key=" | Select-Object -First 1
    if ($line) { return $line.Line.Substring($Key.Length + 1).Trim() }
  }
  return $null
}

function Test-Listening($Port) {
  # TcpClient 探测 127.0.0.1 是否接受连接。Get-NetTCPConnection 在部分会话里会空结果，
  # 导致已在听的 Ollama 被误判 DOWN，再 Start-Process 抢端口/空等 90s。
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

function Wait-Port($Port, $TimeoutSeconds, $Label) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-Listening $Port) { return $true }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Start-Ollama {
  if (Test-Listening 11434) { Write-Host "Ollama already on 11434"; return }
  $Ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
  if (-not (Test-Path $Ollama)) {
    Write-Host "WARN: ollama.exe not found at $Ollama (knowledge embedding skipped)"
    return
  }
  # 不重定向到固定 ollama.err：二次 Start 会截断文件，把成功日志盖成 bind 失败
  Start-Process -FilePath $Ollama -ArgumentList @("serve") -WindowStyle Hidden
  if (-not (Wait-Port 11434 30 "Ollama")) {
    Write-Host "WARN: Ollama failed to listen on 11434"
    return
  }
  Write-Host "Ollama started http://127.0.0.1:11434"
}

function Start-AnythingLLM {
  if (Test-Listening 3001) { Write-Host "AnythingLLM already on 3001"; return }
  $Exe = Join-Path $env:LOCALAPPDATA "Programs\AnythingLLM\AnythingLLM.exe"
  if (-not (Test-Path $Exe)) {
    Write-Host "WARN: AnythingLLM.exe not found at $Exe (knowledge search skipped)"
    return
  }
  Start-Process -FilePath $Exe -WindowStyle Hidden
  if (Wait-Port 3001 60 "AnythingLLM") {
    Write-Host "AnythingLLM started http://127.0.0.1:3001"
    return
  }
  # Electron 桌面应用在非交互/服务式会话里直接 Start-Process 会立刻退出（实测 exit 9、
  # 无任何日志）。改由 explorer 在**交互式 shell 会话**里拉起即可正常启动（实测 3001 起听）。
  Write-Host "AnythingLLM 未起来，改用 explorer 以交互会话拉起…"
  Start-Process explorer.exe -ArgumentList "`"$Exe`""
  if (-not (Wait-Port 3001 90 "AnythingLLM")) {
    Write-Host "WARN: AnythingLLM failed to listen on 3001（请从开始菜单手动启动 AnythingLLM）"
    return
  }
  Write-Host "AnythingLLM started http://127.0.0.1:3001"
}

function Write-PortSummary {
  Write-Host ""
  Write-Host "Ports:"
  foreach ($item in @(
    @{ Port = 11434; Label = "Ollama" },
    @{ Port = 3001; Label = "AnythingLLM" },
    @{ Port = 13307; Label = "MySQL" },
    @{ Port = 9002; Label = "MinIO" },
    @{ Port = 8000; Label = "Backend" },
    @{ Port = 5173; Label = "Frontend" }
  )) {
    $state = if (Test-Listening $item.Port) { "LISTEN" } else { "DOWN" }
    Write-Host ("  {0,-12} {1} {2}" -f $item.Label, $item.Port, $state)
  }
}

function Start-MinIO {
  if (Test-Listening 9002) { Write-Host "MinIO already on 9002"; return }
  $Minio = Join-Path $Runtime "minio\minio.exe"
  if (-not (Test-Path $Minio)) { throw "minio.exe not found: $Minio" }
  $Data = Join-Path $Runtime "minio-data"
  $env:MINIO_ROOT_USER = Get-EnvValue "MINIO_ACCESS_KEY"
  $env:MINIO_ROOT_PASSWORD = Get-EnvValue "MINIO_SECRET_KEY"
  # 不再回落内置 <SET-YOUR-OWN-CREDENTIAL>：凭据不一致会让后端连不上，且默认口令不应出现在仓库逻辑里
  if (-not $env:MINIO_ROOT_USER -or -not $env:MINIO_ROOT_PASSWORD) {
    Write-Host "WARN: 根 .env 未配置 MINIO_ACCESS_KEY / MINIO_SECRET_KEY，跳过 MinIO（对象存储为可选组件）"
    return
  }
  Start-Process -FilePath $Minio -ArgumentList @("server", $Data, "--address", ":9002", "--console-address", ":9003") `
    -RedirectStandardOutput (Join-Path $Log "minio.out") `
    -RedirectStandardError (Join-Path $Log "minio.err") `
    -WindowStyle Hidden
  if (-not (Wait-Port 9002 40 "MinIO")) { throw "MinIO failed to listen on 9002 (check .runtime/logs/minio.err)" }
  Write-Host "MinIO started http://127.0.0.1:9002 (console :9003)"
}

function Ensure-MySQL {
  # Local workbench MySQL uses 13307 to avoid RAGFlow Docker MySQL on 13306.
  $port = 13307
  if (Test-Listening $port) {
    Write-Host "MySQL already on $port"
    return
  }
  if (-not (Test-Path $Mysqld)) { throw "mysqld not found: $Mysqld" }
  if (-not (Test-Path $Ini)) { throw "missing $Ini" }
  Start-Process -FilePath $Mysqld -ArgumentList @("--defaults-file=$Ini") -WindowStyle Hidden
  if (-not (Wait-Port $port 30 "MySQL")) { throw "MySQL failed to listen on $port (check .runtime/mysql-data/*.err)" }
  Write-Host "MySQL started on $port"
}

function Start-Backend {
  if (Test-Listening 8000) { Write-Host "Backend already on 8000"; return }
  $env:PYTHONPATH = Join-Path $Root "backend"
  Start-Process -FilePath $Py -ArgumentList @("-m","uvicorn","main:app","--host","127.0.0.1","--port","8000") `
    -WorkingDirectory (Join-Path $Root "backend") `
    -RedirectStandardOutput (Join-Path $Log "backend.out") `
    -RedirectStandardError (Join-Path $Log "backend.err") `
    -WindowStyle Hidden
  if (-not (Wait-Port 8000 40 "Backend")) {
    throw "Backend failed to listen on 8000 (check .runtime/logs/backend.err)"
  }
  Write-Host "Backend started http://127.0.0.1:8000"
}

function Start-Frontend {
  if (Test-Listening 5173) { Write-Host "Frontend already on 5173"; return }
  # PS 5.1 直接 Start-Process .cmd（npm.cmd）并重定向输出会让子进程继承父句柄，
  # 导致启动脚本挂起不退出；用 cmd.exe /c start（独立最小化窗口）完全分离：
  #   start "" /min cmd /c "npm run dev ..."
  # start 的第一参数是窗口标题，空引号必须用 '""' 形式传给 cmd
  $inner = 'npm run dev -- --host 127.0.0.1 --port 5173'
  $args = '/c start "" /min cmd /c ' + ('"' + $inner + '"')
  Start-Process -FilePath "cmd.exe" `
    -ArgumentList @($args) `
    -WorkingDirectory (Join-Path $Root "sim-frontend") `
    -WindowStyle Hidden
  if (-not (Wait-Port 5173 40 "Frontend")) {
    Write-Host "WARN: Frontend failed to listen on 5173 within 40s"
    return
  }
  Write-Host "Frontend started http://127.0.0.1:5173"
}

Start-Ollama
Start-AnythingLLM
Ensure-MySQL
Start-MinIO
Start-Backend
Start-Frontend
Write-Host ""
Write-Host "Open:  http://127.0.0.1:5173"
Write-Host "API:   http://127.0.0.1:8000/docs"
Write-Host "Login: 见根 .env 的 ADMIN_USERNAME / ADMIN_PASSWORD（首次 bootstrap 会生成并打印一次）"
Write-PortSummary

# 显式退出：确保脚本进程不残留（子服务均为分离进程，不受影响）
exit 0

