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
Info "安装后端依赖（$([System.IO.Path]::GetFileName($spec))）…"
& $VenvPy -m pip install -r $spec --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install 失败，请检查网络或配置 PIP_INDEX_URL 镜像" }
Info "后端依赖安装完成"

# ── 3) 生成 .env（不覆盖已有）────────────────────────────────────────
function New-Secret([int]$bytes = 48) {
  return (& $VenvPy -c "import secrets;print(secrets.token_urlsafe($bytes))").Trim()
}
function New-FernetKey {
  return (& $VenvPy -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())").Trim()
}

if ($Mode -eq 'full') {
  & (Join-Path $PSScriptRoot 'configure-full.ps1') -Root $Root -Python $VenvPy
} elseif (Test-Path $EnvFile) {
  Info "已存在根 .env，保持不变（如需重置请先备份并删除）"
} else {
  if (-not (Test-Path $EnvExample)) { throw "缺少 .env.example，无法生成 .env" }
  $adminPassword = New-Secret 12
  $content = Get-Content $EnvExample -Raw -Encoding UTF8
  $content = $content -replace '(?m)^DB_PASSWORD=.*$', 'DB_PASSWORD='
  $content = $content -replace '(?m)^JWT_SECRET_KEY=.*$', ("JWT_SECRET_KEY=" + (New-Secret 48))
  $content = $content -replace '(?m)^FERNET_KEY=.*$', ("FERNET_KEY=" + (New-FernetKey))
  $content = $content -replace '(?m)^ADMIN_PASSWORD=.*$', ("ADMIN_PASSWORD=" + $adminPassword)
  if ($Mode -eq 'minimal') {
    $content = $content -replace '(?m)^# DB_BACKEND=sqlite$', 'DB_BACKEND=sqlite'
    $content = $content -replace '(?m)^DEVICE_MODE=.*$', 'DEVICE_MODE=sim'
    $content = $content -replace '(?m)^KNOWLEDGE_PROVIDER=.*$', 'KNOWLEDGE_PROVIDER=local'
    $content = $content -replace '(?m)^LLM_API_KEY=.*$', 'LLM_API_KEY='
    $content = $content -replace '(?m)^KNOWLEDGE_API_KEY=.*$', 'KNOWLEDGE_API_KEY='
    $content = $content -replace '(?m)^LLM_BASE_URL=.*$', 'LLM_BASE_URL=http://127.0.0.1:1'
  }
  [System.IO.File]::WriteAllText($EnvFile, $content, (New-Object System.Text.UTF8Encoding($false)))
  Info "已生成根 .env（模式=$Mode）"
  Write-Host ""
  Write-Host "  初始管理员信息已写入本机根 .env，请在本机安全查看；不会回显到日志。" -ForegroundColor Green
  Write-Host ""
  if ($Mode -eq 'full') {
    Warn "full 模式还需在 .env 填写 DB_PASSWORD / DEVICE_DEFAULT_* / LLM_API_KEY / KNOWLEDGE_API_KEY"
  } else {
    Warn "minimal 模式不需要数据库与设备凭据；如需真机或真实知识库，改用 -Mode full 并补 .env"
  }
}

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
# ── 5) 初始化数据库与演示数据 ─────────────────────────────────────────
Info "初始化数据库（$Mode 模式）…"
if ($Mode -eq 'minimal') {
  # 最小模式必须**强制**走 SQLite：否则一旦目录里已有根 .env（例如使用者本机，
  # 或从已有环境拷贝过来的目录），下面的初始化与播种会连上真实 MySQL 并写入演示数据。
  # 进程环境变量优先于 .env，子进程（python/uvicorn）会继承。
  $env:DB_BACKEND = 'sqlite'
  $env:DB_URL = ''
  $env:DEVICE_MODE = 'sim'
  $env:KNOWLEDGE_PROVIDER = 'local'
  Info "已强制最小模式环境变量：DB_BACKEND=sqlite / DEVICE_MODE=sim / KNOWLEDGE_PROVIDER=local"
}
Push-Location $Backend
try {
  Initialize-WorkbenchDatabase $Mode $VenvPy $Backend $Root $BackupDir $BackupFile

  if ($Mode -eq 'minimal') {
    Info "播种离线演示数据（幂等，已存在则跳过）…"
    & $VenvPy (Join-Path $Backend "scripts\seed_sim_devices.py")
    if ($LASTEXITCODE -ne 0) { throw "模拟设备播种失败" }
    & $VenvPy (Join-Path $Backend "scripts\seed_training_labs.py")
    if ($LASTEXITCODE -ne 0) { throw "实训样例播种失败" }
  }
} finally { Pop-Location }

# ── 6) 启动 ───────────────────────────────────────────────────────────
if ($NoStart) {
  Info "已按 -NoStart 跳过启动。手动启动："
  if ($Mode -eq 'full') {
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\start-full.ps1 -BackendPort $BackendPort"
  } else {
    Write-Host "  cd backend; .venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000"
  }
  exit 0
}

if ($Mode -eq 'full') {
  Info "启动 full 后端；外部依赖已经通过认证预检"
  & (Join-Path $PSScriptRoot 'start-full.ps1') -Root $Root -BackendPort $BackendPort
} else {
  Info "启动后端（前端由后端托管）…"
  New-Item -ItemType Directory -Force -Path (Join-Path $Root '.runtime\logs') | Out-Null
  $env:PYTHONPATH = $Backend
  Start-Process -FilePath $VenvPy `
    -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000") `
    -WorkingDirectory $Backend -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Root ".runtime\logs\backend.out") `
    -RedirectStandardError (Join-Path $Root ".runtime\logs\backend.err")
  $deadline = (Get-Date).AddSeconds(60)
  $up = $false
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/health" -UseBasicParsing -TimeoutSec 3
      if ($resp.StatusCode -eq 200) { $up = $true; break }
    } catch { Start-Sleep -Milliseconds 800 }
  }
  if ($up) {
    Write-Host ""
    Write-Host "  ★ 打开 http://127.0.0.1:8000  （登录见根 .env 的 ADMIN_USERNAME / ADMIN_PASSWORD）" -ForegroundColor Green
    Write-Host ""
  } else {
    throw "后端 60s 内未就绪，请查看 .runtime\logs\backend.err"
  }
}
