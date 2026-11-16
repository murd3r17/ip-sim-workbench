param(
  [Parameter(Mandatory = $true)][string]$EditionDir,
  [ValidateRange(1024, 65535)][int]$Port = 18773,
  [switch]$ReuseDependencies,
  [switch]$Upgrade,
  [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Edition = (Resolve-Path -LiteralPath $EditionDir).Path
$Corpus = Join-Path $Edition 'corpus'
foreach ($item in @('manifest.json', 'freeze.json', 'corpus', 'pages', 'legacy-identity.json')) {
  if (-not (Test-Path -LiteralPath (Join-Path $Edition $item))) { throw "教材目录缺少 $item" }
}
$frozen = Get-Content -LiteralPath (Join-Path $Edition 'freeze.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$actual = (Get-FileHash -LiteralPath (Join-Path $Edition 'manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant()
if ($frozen.status -ne 'FROZEN' -or $frozen.reading_manifest_sha256 -ne $actual) {
  throw '请提供已经冻结的一整套教材目录。'
}
$env:KNOWLEDGE_EDITION_DIR = $Edition
$env:KNOWLEDGE_CORPUS_DIR = $Corpus
$env:PYTHONUTF8 = '1'
$env:KNOWLEDGE_PROVIDER = 'local'
$env:DB_BACKEND = 'sqlite'
$env:DEVICE_MODE = 'sim'
$env:DEPLOY_SIMULATE_ONLY = 'true'
$env:MONITOR_SCHEDULER_ENABLED = 'false'
$Runtime = Join-Path $Root '.runtime\reviewed-workbench'
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
$Db = (Join-Path $Runtime 'workbench.sqlite3').Replace('\', '/')
$env:DB_URL = "sqlite+aiosqlite:///$Db"
$env:KNOWLEDGE_LOCAL_STORAGE = (Join-Path $Runtime 'knowledge')
$env:LOG_DIR = (Join-Path $Runtime 'logs')
$env:LLM_BASE_URL = 'http://127.0.0.1:1'
$env:LLM_API_KEY = ''
$env:LLM_FALLBACK_API_KEY = ''

if ($Upgrade -or $NoStart -or -not (Test-Path -LiteralPath $Db) -or -not (Test-Path -LiteralPath (Join-Path $Root 'backend\.venv\Scripts\python.exe'))) {
  & (Join-Path $PSScriptRoot 'bootstrap-local.ps1') -Mode minimal -NoStart -MinimalDbPath $Db `
    -BackupDir (Join-Path $Runtime 'backups') -SkipDependencyInstall:$ReuseDependencies -BackendPort $Port
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if ($NoStart) { return }

$Py = Join-Path $Root 'backend\.venv\Scripts\python.exe'
Push-Location (Join-Path $Root 'backend')
try {
  Write-Host "工作台地址 http://127.0.0.1:$Port 。按 Ctrl+C 停止。"
  & $Py -m uvicorn main:app --host 127.0.0.1 --port $Port
  exit $LASTEXITCODE
} finally {
  Pop-Location
}
