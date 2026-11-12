# Copies a clean source snapshot to .runtime and runs only isolated sim validation.
param(
  [ValidateSet('minimal', 'full')][string]$Mode = 'minimal',
  [switch]$SkipSlow
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $Root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
$StepArguments = @('-B', (Join-Path $PSScriptRoot 'delivery.py'), 'prepare', '--root', $Root, '--mode', $Mode)
if ($SkipSlow) { $StepArguments += '--skip-slow' }
& $Python @StepArguments
exit $LASTEXITCODE
