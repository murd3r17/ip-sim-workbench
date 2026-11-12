# Read-only gates. Exit 0 = selected mode complete; 1 = failure; 2 = incomplete.
# Preparation/build/test is explicit: scripts\prepare-delivery.ps1.
param(
  [ValidateSet('minimal', 'full', 'candidate')][string]$Mode = 'minimal',
  [string]$SourceRoot = (Split-Path $PSScriptRoot -Parent),
  [switch]$SkipSlow
)
$ErrorActionPreference = 'Stop'
$Python = Join-Path (Split-Path $PSScriptRoot -Parent) 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
if ($SkipSlow) { Write-Host 'Check is read-only; missing preparation evidence stays INCOMPLETE.' }
& $Python -B (Join-Path $PSScriptRoot 'delivery.py') check --root $SourceRoot --mode $Mode
exit $LASTEXITCODE
