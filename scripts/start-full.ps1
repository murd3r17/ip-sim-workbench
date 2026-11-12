param(
  [string]$Root = (Split-Path $PSScriptRoot -Parent),
  [ValidateRange(1, 65535)][int]$BackendPort = 8000,
  [string]$BindHost = '127.0.0.1',
  [string]$LaunchReceipt
)
$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($Root)
$Python = Join-Path $Root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
  throw '缺少当前目录 Python 环境，请先按 full 启动指南准备依赖。'
}
$cli = @((Join-Path $Root 'backend\scripts\full_lifecycle.py'), 'start', '--root', $Root, '--port', $BackendPort)
 $cli += @('--host', $BindHost)
if ($LaunchReceipt) {
  $cli += @('--receipt', $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($LaunchReceipt))
}
& $Python -X utf8 @cli
if ($LASTEXITCODE -ne 0) { throw 'full 实例操作失败，请按上面的原因处理。' }
