param(
  [string]$Root = (Split-Path $PSScriptRoot -Parent),
  [string]$Python,
  [switch]$CheckOnly,
  [switch]$RestartDraft
)
$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath($Root)
$Target = Join-Path $Root '.env'
if ((Test-Path -LiteralPath $Target) -and -not $CheckOnly) {
  Write-Host '[full] 已有 .env，保持所有配置与凭据不变。'
  Write-Host '[full] 只检查缺项：重新运行本脚本并加 -CheckOnly（仅本地格式检查，不请求模型或服务）。'
  return
}
if (-not $Python) { $Python = Join-Path $Root 'backend\.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python)) { throw '请先运行 bootstrap-local.ps1 -Mode full 安装 Python 依赖。' }
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
$Preflight = Join-Path $PSScriptRoot '..\backend\scripts\full_preflight.py'
if ($CheckOnly) {
  & $Python $Preflight --root $Root --validate-only
  if ($LASTEXITCODE -ne 0) { throw '配置尚未完整；按上方键名在本机修正配置，然后重跑 -CheckOnly。未探测服务或修改文件。' }
  return
}

# Only this allowlist can reach the resumable draft. Credentials stay in memory
# until the complete configuration passes the same validator as full preflight.
$DraftKeys = @('DB_HOST','DB_PORT','DB_NAME','DB_USER','ADMIN_USERNAME','DEVICE_DEFAULT_USERNAME',
  'LLM_BASE_URL','LLM_MODEL','LLM_VISION_MODEL','KNOWLEDGE_BASE_URL','KNOWLEDGE_WORKSPACE_SLUG',
  'MINIO_ENDPOINT','MINIO_BUCKET','MINIO_SECURE')
$DraftDirectory = Join-Path $Root '.runtime\setup'
$DraftPath = Join-Path $DraftDirectory 'full-draft.json'
foreach ($directory in @($Root, (Join-Path $Root '.runtime'), $DraftDirectory)) {
  if ((Test-Path -LiteralPath $directory) -and ((Get-Item -LiteralPath $directory).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw '配置草稿目录不能经过符号链接或目录联接；请选择普通项目目录。'
  }
}
$Draft = @{}
if ((Test-Path -LiteralPath $DraftPath) -and ((Get-Item -LiteralPath $DraftPath).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
  throw '配置草稿文件不能是符号链接。'
}
if ((Test-Path -LiteralPath $DraftPath) -and -not $RestartDraft) {
  try {
    if ((Get-Item -LiteralPath $DraftPath).Length -gt 65536) { throw 'draft size' }
    $saved = Get-Content -LiteralPath $DraftPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($saved.schema -ne 1) { throw 'draft schema' }
    foreach ($key in $DraftKeys) {
      $entry = $saved.values.PSObject.Properties[$key]
      if ($entry -and $entry.Value -is [string] -and $entry.Value.Length -le 512 -and $entry.Value -notmatch '[\x00-\x1f]') {
        if ($key -like '*BASE_URL') {
          $uri = $null
          if (-not [Uri]::TryCreate($entry.Value, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -notin @('http','https') -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) { continue }
        }
        $Draft[$key] = $entry.Value
      }
    }
    Write-Host '[full] 已恢复非秘密填写进度。可逐项修改；密码和密钥需要重新输入。加 -RestartDraft 可从默认值重新填写。'
  } catch { Write-Host '[full] 上次非秘密草稿无法读取，本次从默认值重新填写；已有 .env 不受影响。' }
}
function Save-SetupDraft {
  $safe = [ordered]@{}
  foreach ($key in $DraftKeys) { if ($Draft.ContainsKey($key)) { $safe[$key] = $Draft[$key] } }
  [IO.Directory]::CreateDirectory($DraftDirectory) | Out-Null
  $temporary = Join-Path $DraftDirectory ('draft-' + [Guid]::NewGuid().ToString('N') + '.tmp')
  [IO.File]::WriteAllText($temporary, (@{schema=1;values=$safe} | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
  if (Test-Path -LiteralPath $DraftPath) { [IO.File]::Replace($temporary, $DraftPath, [System.Management.Automation.Language.NullString]::Value) }
  else { [IO.File]::Move($temporary, $DraftPath) }
}

function Read-Setting([string]$Key, [string]$Name, [string]$Default = '') {
  if ($Draft.ContainsKey($Key)) { $Default = $Draft[$Key] }
  $value = Read-Host "$Name [$Default]"
  if ([string]::IsNullOrWhiteSpace($value)) { $value = $Default }
  if ([string]::IsNullOrWhiteSpace($value)) { throw "$Name 不能为空" }
  $value = $value.Trim()
  if ($Key -like '*BASE_URL') {
    $uri = $null
    if (-not [Uri]::TryCreate($value, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -notin @('http','https') -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
      throw "$Key 需要不含用户信息、查询参数或片段的 HTTP(S) 服务地址；未保存该值。"
    }
  }
  $Draft[$Key] = $value
  Save-SetupDraft
  return $value
}
function Read-OptionalSetting([string]$Key, [string]$Name) {
  $previous = if ($Draft.ContainsKey($Key)) { $Draft[$Key] } else { '' }
  $value = (Read-Host "$Name（留空沿用 [$previous]，输入 - 清空）").Trim()
  if (-not $value) { $value = $previous }
  if ($value -eq '-') { $value = '' }
  $Draft[$Key] = $value
  Save-SetupDraft
  return $value
}
function Read-PrivateSetting([string]$Name) {
  $secure = Read-Host "$Name（隐藏输入，不回显）" -AsSecureString
  $pointer = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    $value = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ([string]::IsNullOrWhiteSpace($value)) { throw "$Name 不能为空" }
    return $value
  } finally {
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $secure.Dispose()
  }
}
function Quote-DotEnv([string]$Value) {
  if ($Value.Contains('`${') -or $Value.Contains('${') -or $Value.IndexOfAny([char[]]"`r`n`0") -ge 0) {
    throw '配置值不能含换行、空字符或 dotenv 变量插值；未写入配置。'
  }
  return '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"'
}

Write-Host '[full] 使用接收方自己的外部/已安装服务；本步骤不会安装或修改这些服务。'
Write-Host '[full] MySQL 数据库和用户须已创建。恢复旧库时必须安全沿用原库对应的 Fernet 密钥；请直接准备已有配置，不运行首次向导。'
Write-Host '[full] 分为数据库、管理员/设备、模型、知识和可选存储五组。中断后重跑恢复非秘密进度；密码/密钥不会写入草稿。'
$values = [ordered]@{
  DB_BACKEND = 'mysql'; DB_URL = ''; DEVICE_MODE = 'ssh'; KNOWLEDGE_PROVIDER = 'anythingllm'
  LLM_PROVIDER = 'openai_compatible'; MONITOR_SCHEDULER_ENABLED = 'false'; DEPLOY_SIMULATE_ONLY = 'true'; APP_VERSION = 'v7.0'
}
$values.DB_HOST = Read-Setting 'DB_HOST' 'MySQL 主机' '127.0.0.1'
$values.DB_PORT = Read-Setting 'DB_PORT' 'MySQL 端口' '3306'
$values.DB_NAME = Read-Setting 'DB_NAME' 'MySQL 数据库名（已存在空库或已核验副本）' 'sim_workspace'
$values.DB_USER = Read-Setting 'DB_USER' 'MySQL 用户' 'sim_admin'
$values.DB_PASSWORD = Read-PrivateSetting 'MySQL 密码'
$values.ADMIN_USERNAME = Read-Setting 'ADMIN_USERNAME' '工作台管理员用户名' 'admin'
$values.ADMIN_PASSWORD = Read-PrivateSetting '工作台管理员密码'
$values.DEVICE_DEFAULT_USERNAME = Read-Setting 'DEVICE_DEFAULT_USERNAME' '设备默认 SSH 用户'
$values.DEVICE_DEFAULT_PASSWORD = Read-PrivateSetting '设备默认 SSH 密码'
$values.LLM_BASE_URL = Read-Setting 'LLM_BASE_URL' 'DeepSeek 兼容 API 地址' 'https://api.deepseek.com/v1'
$values.LLM_MODEL = Read-Setting 'LLM_MODEL' 'DeepSeek 模型名' 'deepseek-flash'
$values.LLM_VISION_MODEL = Read-OptionalSetting 'LLM_VISION_MODEL' '视觉模型名 LLM_VISION_MODEL；未配置时关闭图片能力，需填写账号实际支持的模型'
$values.LLM_API_KEY = Read-PrivateSetting 'DeepSeek API Key'
$values.KNOWLEDGE_BASE_URL = Read-Setting 'KNOWLEDGE_BASE_URL' 'AnythingLLM 地址' 'http://127.0.0.1:3001'
$values.KNOWLEDGE_WORKSPACE_SLUG = Read-Setting 'KNOWLEDGE_WORKSPACE_SLUG' 'AnythingLLM 工作区 slug' 'ip-ops-kb'
$values.KNOWLEDGE_API_KEY = Read-PrivateSetting 'AnythingLLM API Key'
if ((Read-Host '是否配置 MinIO 对象存储？[y/N]') -match '^[yY]$') {
  $values.MINIO_ENDPOINT = Read-Setting 'MINIO_ENDPOINT' 'MinIO 地址（主机:端口）' '127.0.0.1:9002'
  $values.MINIO_ACCESS_KEY = Read-PrivateSetting 'MinIO Access Key'
  $values.MINIO_SECRET_KEY = Read-PrivateSetting 'MinIO Secret Key'
  $values.MINIO_BUCKET = Read-Setting 'MINIO_BUCKET' 'MinIO bucket' 'sim-workstation'
  $values.MINIO_SECURE = if ((Read-Host 'MinIO 是否使用 HTTPS？[y/N]') -match '^[yY]$') { 'true' } else { 'false' }
}
$values.JWT_SECRET_KEY = (& $Python -c 'import secrets;print(secrets.token_urlsafe(48))').Trim()
if ($LASTEXITCODE -ne 0) { throw '安全随机密钥生成失败' }
$values.FERNET_KEY = (& $Python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Fernet 密钥生成失败' }
$validationText = ($values | ConvertTo-Json -Compress) | & $Python $Preflight --validate-config-stdin
$validationExit = $LASTEXITCODE
try { $validation = ($validationText -join "`n") | ConvertFrom-Json } catch { throw '配置校验器未返回有效结果，未写入 .env。' }
if ($validationExit -ne 0 -or -not $validation.ok) {
  foreach ($issue in $validation.issues) { Write-Host ('[full] ' + $issue.key + '：' + $issue.message) }
  throw '配置未通过本地校验，未写入 .env。重跑向导可修改保留的非秘密项；密码和密钥需重新输入。'
}
$lines = @('# Receiver-owned full configuration. Never share this file in the delivery archive.')
foreach ($key in $values.Keys) { $lines += $key + '=' + (Quote-DotEnv $values[$key]) }
$bytes = [System.Text.Encoding]::UTF8.GetBytes(($lines -join "`n") + "`n")
# Create the new file with its private ACL atomically. An ordinary write handle
# cannot change a DACL afterwards, even when its owner can change the path ACL.
$security = New-Object System.Security.AccessControl.FileSecurity
$security.SetAccessRuleProtection($true, $false)
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow')
$security.AddAccessRule($rule)
$stream = [System.IO.FileStream]::new($Target, [System.IO.FileMode]::CreateNew, [System.Security.AccessControl.FileSystemRights]::Write, [System.IO.FileShare]::None, 4096, [System.IO.FileOptions]::None, $security)
try {
  $stream.Write($bytes, 0, $bytes.Length)
  $stream.Flush()
} finally {
  $stream.Dispose()
  [Array]::Clear($bytes, 0, $bytes.Length)
}
Write-Host '[full] 已安全写入新 .env；不回显凭据。配置下发默认仍需显式启用，定时采集默认关闭。'
