# Export exactly the checked manifest, including dist and dependency lock files.
param(
  [Parameter(Mandatory = $true)][string]$PreparedRoot,
  [ValidateSet('minimal', 'full', 'candidate')][string]$Mode = 'minimal'
)
$ErrorActionPreference = 'Stop'
$Python = Join-Path (Split-Path $PSScriptRoot -Parent) 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
& $Python -B (Join-Path $PSScriptRoot 'delivery.py') package --root $PreparedRoot --mode $Mode
exit $LASTEXITCODE
