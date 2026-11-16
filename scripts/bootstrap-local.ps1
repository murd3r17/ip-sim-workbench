# bootstrap-local.ps1 — 一键准备本地运行环境（可移植性档位 1）
#
# 目标：干净机器克隆仓库后，跑本脚本即可用。
#   -Mode minimal（默认）：SQLite + DEVICE_MODE=sim + 本地知识库 + 预置前端 dist
#                          → 只依赖 Python，不需要 MySQL / Node / Ollama / AnythingLLM
#   -Mode full：接收方自己的 MySQL + SSH + DeepSeek + AnythingLLM，认证预检后显式初始化
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap-local.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap-local.ps1 -Mode full
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap-local.ps1 -NoStart
param(
  [ValidateSet('minimal', 'full')]
  [string]$Mode = 'minimal',
  [switch]$NoStart,
  [switch]$RebuildFrontend,
  [string]$MinimalDbPath,
  [switch]$SkipDependencyInstall,
  [string]$BackupDir,
  [string]$BackupFile,
  [ValidateRange(1, 65535)][int]$BackendPort = 8000
)

$ErrorActionPreference = "Stop"
# 原生命令（python/npm）输出按 UTF-8 解码，避免中文日志乱码
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = "1"
$Root = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $Root "backend"))) {
  throw "找不到 backend 目录（$Root）。请从仓库根目录运行本脚本。"
}
$Backend = Join-Path $Root "backend"
$Venv = Join-Path $Backend ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
$EnvFile = Join-Path $Root ".env"
$EnvExample = Join-Path $Root ".env.example"
if ($MinimalDbPath -and $Mode -ne 'minimal') { throw 'MinimalDbPath 仅用于本地模拟工作台。' }

if ($Mode -eq 'minimal' -and -not $NoStart) {
  $portCheck = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $BackendPort)
  try {
    $portCheck.ExclusiveAddressUse = $true
    $portCheck.Start()
  } catch [System.Net.Sockets.SocketException] {
    throw "无法监听本机端口 $BackendPort。请确认端口可用，或用 -BackendPort 指定其他端口。"
  } finally {
    $portCheck.Stop()
  }
}

function Info($msg) { Write-Host "[bootstrap] $msg" }
function Warn($msg) { Write-Host "[bootstrap] WARN: $msg" -ForegroundColor Yellow }

function Initialize-WorkbenchDatabase($Mode, $Python, $Backend, $Root, $BackupDir, $BackupFile) {
  if ($Mode -eq 'full') {
    $PreflightArguments = @((Join-Path $Backend 'scripts\full_preflight.py'), '--root', $Root, '--phase', 'prepare')
    if ($BackupFile) { $PreflightArguments += @('--backup-file', $BackupFile) }
    & $Python @PreflightArguments
    if ($LASTEXITCODE -ne 0) { throw 'full 认证预检失败；未执行数据库初始化或迁移。' }
  }
  $BootstrapArguments = @((Join-Path $Backend 'scripts\bootstrap_local.py'))
  if ($Mode -eq 'minimal' -and -not $BackupDir) { $BackupDir = Join-Path $Root '.runtime\backups' }
  if ($BackupDir) { $BootstrapArguments += @('--backup-dir', $BackupDir) }
  if ($BackupFile) { $BootstrapArguments += @('--backup-file', $BackupFile) }
  & $Python @BootstrapArguments
  if ($LASTEXITCODE -ne 0) { throw '数据库初始化失败（检查有效数据库配置及备份要求）。' }
}

# ── 1) 找 Python ─────────────────────────────────────────────────────
function Resolve-Python {
  foreach ($candidate in @('py -3.12', 'py -3', 'python')) {
    $parts = $candidate.Split(' ')
    $exe = $parts[0]
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
      try {
        $args = @(); if ($parts.Length -gt 1) { $args = $parts[1..($parts.Length - 1)] }
        $ver = & $exe @args -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($ver -and [version]$ver -ge [version]'3.11') {
          return @{ Exe = $exe; Args = $args; Version = $ver }
        }
      } catch { }
    }
  }
  return $null
}

if ($Mode -eq 'minimal') {
  $PythonCommand = if (Test-Path $VenvPy) { @{ Exe = $VenvPy; Args = @() } } else { Resolve-Python }
  if (-not $PythonCommand) { throw '未找到 Python 3.11+。请安装 Python 3.12 后重试。' }
  $entry = Join-Path $PSScriptRoot 'bootstrap_local.py'
  $prepare = @($entry, '--no-start', '--port', "$BackendPort")
  if ($MinimalDbPath) { $prepare += @('--db-path', $MinimalDbPath) }
  if ($BackupDir) { $prepare += @('--backup-dir', $BackupDir) }
  if ($SkipDependencyInstall) { $prepare += '--skip-dependency-install' }
  if ($RebuildFrontend) { $prepare += '--rebuild-frontend' }
  & $PythonCommand.Exe @($PythonCommand.Args) @prepare
  if ($LASTEXITCODE -ne 0) { throw '最小模式初始化失败。请查看上方提示。' }
  if ($NoStart) {
    Info '已完成初始化。重新运行同一脚本并移除 -NoStart 即可启动。'
    exit 0
  }
  $appUrl = "http://127.0.0.1:$BackendPort"
  if ($MinimalDbPath) { $env:DB_SQLITE_PATH = [System.IO.Path]::GetFullPath($MinimalDbPath) }
  $logs = Join-Path $Root '.runtime\logs'
  New-Item -ItemType Directory -Force -Path $logs | Out-Null
  $runId = [Guid]::NewGuid().ToString('N')
  $stderrPath = Join-Path $logs "minimal-$runId.err"
  $startOptions = @{
    FilePath = $VenvPy
    PassThru = $true
    WorkingDirectory = $Root
    WindowStyle = 'Hidden'
    ArgumentList = @('scripts/bootstrap_local.py', '--start-only', '--port', "$BackendPort")
    RedirectStandardOutput = Join-Path $logs "minimal-$runId.out"
    RedirectStandardError = $stderrPath
  }
  $backendProcess = Start-Process @startOptions
  $deadline = (Get-Date).AddSeconds(60)
  while ((Get-Date) -lt $deadline -and -not $backendProcess.HasExited) {
    try {
      $resp = Invoke-WebRequest -Uri "$appUrl/api/v1/health" -UseBasicParsing -TimeoutSec 3
      if ($resp.StatusCode -eq 200) {
        Info "打开 $appUrl。管理员账号见本机 .env。"
        exit 0
      }
    } catch { Start-Sleep -Milliseconds 700 }
  }
  if (-not $backendProcess.HasExited) { $backendProcess.Kill($true) }
  throw "工作台未就绪，请查看 $stderrPath"
}

if (-not (Test-Path $VenvPy)) {
  $python = Resolve-Python
  if (-not $python) {
    throw "未找到 Python 3.11+。请先安装（https://www.python.org/downloads/），或运行: winget install Python.Python.3.12"
  }
  Info "使用 Python $($python.Version) 创建虚拟环境 -> backend\.venv"
  & $python.Exe @($python.Args) -m venv $Venv
  if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败" }
} else {
  Info "复用已有虚拟环境 backend\.venv"
}

# ── 2) 安装后端依赖 ───────────────────────────────────────────────────
$lock = Join-Path $Backend "requirements.lock"
$spec = $lock
if (-not (Test-Path -LiteralPath $spec)) { throw "缺少 requirements.lock，不能进行可复核交付" }
if ($SkipDependencyInstall) {
  & $VenvPy -m pip check
  if ($LASTEXITCODE -ne 0) { throw '现有依赖环境不完整，请常规初始化。' }
  & $VenvPy -c "import fastapi, uvicorn, sqlalchemy, alembic, aiosqlite"
  if ($LASTEXITCODE -ne 0) { throw '现有环境缺少基本运行依赖，请常规初始化。' }
} else {
  Info "安装后端依赖（$([System.IO.Path]::GetFileName($spec))）…"
  & $VenvPy -m pip install -r $spec --quiet
  if ($LASTEXITCODE -ne 0) { throw "pip install 失败，请检查网络或配置 PIP_INDEX_URL 镜像" }
  Info "后端依赖安装完成"
}

& (Join-Path $PSScriptRoot 'configure-full.ps1') -Root $Root -Python $VenvPy

# ── 4) 前端 dist ──────────────────────────────────────────────────────
$Dist = Join-Path $Root "sim-frontend\dist"
if ($RebuildFrontend -or -not (Test-Path (Join-Path $Dist "index.html"))) {
  if (Get-Command npm.cmd -ErrorAction SilentlyContinue) {
    Info "构建前端 dist（npm ci + npm run build）…"
    Push-Location (Join-Path $Root "sim-frontend")
    try {
      if (-not (Test-Path 'package-lock.json')) { throw "缺少 package-lock.json" }
      & npm.cmd ci --silent
      if ($LASTEXITCODE -ne 0) { throw "npm ci 失败" }
      & npm.cmd run build
      if ($LASTEXITCODE -ne 0) { throw "前端构建失败，环境准备未完成" }
    } finally { Pop-Location }
  } elseif (Test-Path (Join-Path $Dist "index.html")) {
    Info "使用仓库自带的 sim-frontend/dist"
  } else {
    throw "未找到 npm 且没有预置 dist，环境准备未完成；请安装 Node 20+"
  }
} else {
  Info "前端 dist 已存在，跳过构建（需要重建加 -RebuildFrontend）"
}

if (-not (Test-Path (Join-Path $Dist 'index.html'))) { throw "缺少前端 dist/index.html" }
Info '初始化 full 数据库…'
Push-Location $Backend
try {
  Initialize-WorkbenchDatabase $Mode $VenvPy $Backend $Root $BackupDir $BackupFile
} finally { Pop-Location }

if ($NoStart) {
  Info "已完成初始化。启动：powershell -File scripts\start-full.ps1 -BackendPort $BackendPort"
  exit 0
}
& (Join-Path $PSScriptRoot 'start-full.ps1') -Root $Root -BackendPort $BackendPort
