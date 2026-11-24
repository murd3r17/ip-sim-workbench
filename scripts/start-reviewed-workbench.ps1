param(
  [Parameter(Mandatory = $true)][string]$EditionDir,
  [string]$OriginalDir,
  [ValidateRange(1024, 65535)][int]$Port = 18773,
  [switch]$ReuseDependencies,
  [switch]$Upgrade,
  [switch]$NoStart,
  [string]$PreviousEditionDir
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
function Resolve-FrozenReadingEdition([string]$Directory) {
  $path = (Resolve-Path -LiteralPath $Directory).Path
  foreach ($item in @('manifest.json', 'freeze.json', 'corpus', 'pages', 'legacy-identity.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $path $item))) { throw "教材目录 $path 缺少 $item" }
  }
  $frozen = Get-Content -LiteralPath (Join-Path $path 'freeze.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  $manifestHash = (Get-FileHash -LiteralPath (Join-Path $path 'manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($frozen.status -ne 'FROZEN' -or $frozen.reading_manifest_sha256 -ne $manifestHash) {
    throw "请提供已经冻结的一整套教材目录。当前路径 $path"
  }
  return $path
}
$Edition = Resolve-FrozenReadingEdition $EditionDir
$env:KNOWLEDGE_EDITION_DIR = $Edition
$env:KNOWLEDGE_CORPUS_DIR = Join-Path $Edition 'corpus'
if ($PreviousEditionDir) {
  $previous = Resolve-FrozenReadingEdition $PreviousEditionDir
  if ($previous -ieq $Edition) { throw '历史教材目录应指向前一版冻结教材。' }
  $env:KNOWLEDGE_PREVIOUS_EDITION_DIR = $previous
}
if ($OriginalDir) {
  $env:KNOWLEDGE_ORIGINAL_DIR = (Resolve-Path -LiteralPath $OriginalDir).Path
} else {
  $env:KNOWLEDGE_ORIGINAL_DIR = ''
}
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
$env:LLM_PROVIDER = 'openai_compatible'
$env:LLM_BASE_URL = 'http://127.0.0.1:1'
$env:LLM_API_KEY = ''
$env:LLM_FALLBACK_BASE_URL = ''
$env:LLM_FALLBACK_MODEL = ''
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
