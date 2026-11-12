# Sync knowledge corpus from ip-sim-source (authoritative) to workbench copy.
# Ingest only NN-*.md (skip 00-*.md). Use -Check to report diffs without copying.
# Usage:
#   .\scripts\sync-corpus.ps1
#   .\scripts\sync-corpus.ps1 -Check
param(
  [switch]$Check
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
# 语料权威源：优先环境变量 CORPUS_SRC，其次仓库同级的 ..\ip-sim-source\md
$SrcRoot = $env:CORPUS_SRC
if (-not $SrcRoot) { $SrcRoot = Join-Path (Split-Path $Root -Parent) "ip-sim-source\md" }
$DstRoot = Join-Path $Root "knowledge\corpus\huawei-ip"

if (-not (Test-Path $SrcRoot)) { throw "Source corpus not found: $SrcRoot（可用环境变量 CORPUS_SRC 指定）" }
if (-not (Test-Path $DstRoot)) { throw "Workbench corpus not found: $DstRoot" }

$copied = 0
$skipped = 0
$missing = 0
$differ = 0

Get-ChildItem -Path $SrcRoot -Recurse -Filter "*.md" | Where-Object {
  $_.Name -match '^\d{2}-' -and $_.Name -notmatch '^00-'
} | ForEach-Object {
  $rel = $_.FullName.Substring($SrcRoot.Length).TrimStart('\')
  $dst = Join-Path $DstRoot $rel
  if (-not (Test-Path $dst)) {
    $missing++
    if ($Check) { Write-Host "MISSING $rel" }
    else {
      New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
      Copy-Item $_.FullName $dst -Force
      $copied++
      Write-Host "COPIED $rel"
    }
    return
  }
  $srcHash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
  $dstHash = (Get-FileHash $dst -Algorithm SHA256).Hash
  if ($srcHash -eq $dstHash) {
    $skipped++
  } else {
    $differ++
    if ($Check) { Write-Host "DIFF $rel" }
    else {
      Copy-Item $_.FullName $dst -Force
      $copied++
      Write-Host "UPDATED $rel"
    }
  }
}

Write-Host ("done: copied={0} unchanged={1} missing={2} differ={3} check={4}" -f $copied, $skipped, $missing, $differ, [bool]$Check)
if ($Check -and ($missing -gt 0 -or $differ -gt 0)) { exit 1 }
exit 0
