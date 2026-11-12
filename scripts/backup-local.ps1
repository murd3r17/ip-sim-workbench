# 本地数据备份：MySQL(sim_workspace) + MinIO 对象 → .runtime\backup\<时间戳>\
# 保留 7 天（超过自动清理）。可挂计划任务每日执行。
# 用法: .\scripts\backup-local.ps1
$ErrorActionPreference = "Stop"
# 原生命令（mysqldump / python）的输出按 UTF-8 解码，避免中文日志乱码
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = "1"
$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$BackupRoot = Join-Path $Runtime "backup"
$Log = Join-Path $Runtime "logs\backup.log"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Target = Join-Path $BackupRoot $Timestamp
$RetentionDays = 7

function Write-Log($Msg) {
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Msg
  Add-Content -Path $Log -Value $line -Encoding UTF8
  Write-Host $line
}

New-Item -ItemType Directory -Force -Path $Target | Out-Null
Write-Log "备份开始 -> $Target"

# == 1) MySQL（从根 .env 读凭据；mysqldump 在 .runtime\mysql-server\bin）==
$EnvFile = Join-Path $Root ".env"
function Get-EnvValue($Key) {
  if (Test-Path $EnvFile) {
    $line = Select-String -Path $EnvFile -Pattern "^$Key=" | Select-Object -First 1
    if ($line) { return $line.Line.Substring($Key.Length + 1).Trim() }
  }
  return $null
}
$DbUser = Get-EnvValue "DB_USER"; if (-not $DbUser) { $DbUser = "sim_admin" }
$DbPass = Get-EnvValue "DB_PASSWORD"
$DbPort = Get-EnvValue "DB_PORT"; if (-not $DbPort) { $DbPort = "13307" }
$DbName = Get-EnvValue "DB_NAME"; if (-not $DbName) { $DbName = "sim_workspace" }
$Mysqldump = Join-Path $Runtime "mysql-server\bin\mysqldump.exe"

if (-not $DbPass) { Write-Log "!! 未从根 .env 读到 DB_PASSWORD，跳过 MySQL 备份"; $mysqlOk = $false }
elseif (-not (Test-Path $Mysqldump)) { Write-Log "!! mysqldump 不存在: $Mysqldump"; $mysqlOk = $false }
else {
  $mysqlOk = $false
  $DumpFile = Join-Path $Target "mysql_$DbName.sql"
  $DumpErr = Join-Path $Target "mysql_$DbName.err"
  # 用 MYSQL_PWD 传密码，避免 CLI -p 的明文警告（该警告在 Stop 模式下会被当错误）
  # 说明：sim_admin 无 RELOAD 权限且 root 密码与 .env 不一致（历史轮换过），
  #   MySQL 9.5 的 --single-transaction 无条件执行 FLUSH（需 RELOAD）→ 放弃事务级一致性，
  #   改用 --skip-lock-tables（夜间单用户备份、无并发写，逐表一致足够）。
  # --set-gtid-purged=OFF 消除 GTID 警告。
  # --result-file 让 mysqldump 自己写字节，不经 PowerShell 文本管道。
  #   旧写法 `... 2>&1 | Set-Content -Encoding UTF8` 会给 dump 加 UTF-8 BOM，
  #   并按控制台编码把中文转码（日志里已出现过乱码），恢复时可能失败。
  $env:MYSQL_PWD = $DbPass
  try {
    $dumpArgs = @(
      "-h", "127.0.0.1", "-P", $DbPort, "-u", $DbUser,
      "--skip-lock-tables", "--no-tablespaces", "--set-gtid-purged=OFF",
      "--routines", "--triggers", "--result-file=$DumpFile", $DbName
    )
    $proc = Start-Process -FilePath $Mysqldump -ArgumentList $dumpArgs -NoNewWindow -Wait -PassThru `
      -RedirectStandardError $DumpErr
    if ($proc.ExitCode -ne 0) {
      $errText = ""
      if (Test-Path $DumpErr) { $errText = (Get-Content $DumpErr -Raw -Encoding UTF8).Trim() }
      Write-Log "!! MySQL 备份失败 (exit=$($proc.ExitCode)): $errText"
    } elseif (-not (Test-Path $DumpFile) -or (Get-Item $DumpFile).Length -eq 0) {
      Write-Log "!! MySQL 备份为空文件"
    } else {
      Write-Log "MySQL OK: $DumpFile ($([math]::Round((Get-Item $DumpFile).Length/1KB,1)) KB)"
      $mysqlOk = $true
      Remove-Item $DumpErr -Force -ErrorAction SilentlyContinue
    }
  } catch {
    Write-Log "!! MySQL 备份失败: $($_.Exception.Message)"
  } finally {
    # 无论成败都要清掉进程环境里的明文密码
    Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
    # 失败时不留误导性的空/半截 dump
    if (-not $mysqlOk -and (Test-Path $DumpFile)) {
      Remove-Item $DumpFile -Force -ErrorAction SilentlyContinue
    }
  }
}

# == 2) MinIO（用 backend venv 的 minio SDK）==
$Py = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { Write-Log "!! 未找到 venv python，跳过 MinIO 备份"; $minioOk = $false }
else {
  $minioOut = Join-Path $Target "minio.out"
  $minioErr = Join-Path $Target "minio.err"
  try {
    # 用 Start-Process 重定向到文件：既拿到完整 traceback，也避免 `2>&1 |` 在
    # $ErrorActionPreference=Stop 下把 stderr 首行当终止错误而截断后续输出。
    $proc = Start-Process -FilePath $Py `
      -ArgumentList @((Join-Path $Root "backend\scripts\backup_minio.py"), $Target) `
      -NoNewWindow -Wait -PassThru -RedirectStandardOutput $minioOut -RedirectStandardError $minioErr
    if (Test-Path $minioOut) { Get-Content $minioOut -Encoding UTF8 | Where-Object { $_ -ne "" } | ForEach-Object { Write-Log "  $_" } }
    if ($proc.ExitCode -eq 0) {
      $minioOk = $true
      Remove-Item $minioOut, $minioErr -Force -ErrorAction SilentlyContinue
    } else {
      $minioOk = $false
      if (Test-Path $minioErr) {
        Get-Content $minioErr -Encoding UTF8 | Where-Object { $_ -ne "" } | Select-Object -Last 8 | ForEach-Object { Write-Log "  ! $_" }
      }
      Write-Log "!! MinIO 备份失败 (exit=$($proc.ExitCode))"
    }
  } catch { Write-Log "!! MinIO 备份失败: $($_.Exception.Message)"; $minioOk = $false }
}

# == 3) AnythingLLM storage (documents + lancedb; skip engines) ==
$AllmOk = $true
$AllmRoot = Get-EnvValue "KNOWLEDGE_ANYTHINGLLM_STORAGE"
if (-not $AllmRoot) {
  $AllmRoot = Join-Path $env:APPDATA "anythingllm-desktop\storage"
}
if (-not (Test-Path $AllmRoot)) {
  # 知识库是可选组件（health 里标 optional），未安装不应让整次备份判失败
  Write-Log "WARN: 未发现 AnythingLLM 存储目录，跳过知识库备份: $AllmRoot"
} else {
  $AllmDest = Join-Path $Target "anythingllm"
  New-Item -ItemType Directory -Force -Path $AllmDest | Out-Null
  foreach ($Sub in @("documents", "lancedb")) {
    $src = Join-Path $AllmRoot $Sub
    if (Test-Path $src) {
      try {
        Copy-Item -Path $src -Destination (Join-Path $AllmDest $Sub) -Recurse -Force
        Write-Log "AnythingLLM OK: $Sub"
      } catch {
        Write-Log "!! AnythingLLM copy failed ($Sub): $($_.Exception.Message)"
        $AllmOk = $false
      }
    } else {
      Write-Log "WARN: AnythingLLM 缺少子目录（可能尚未灌库），跳过: $Sub"
    }
  }
}

# == 4) 保留期清理 ==
$removed = 0
Get-ChildItem $BackupRoot -Directory -ErrorAction SilentlyContinue | Where-Object {
  $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays)
} | ForEach-Object { Remove-Item $_.FullName -Recurse -Force; $removed++ }
if ($removed -gt 0) { Write-Log "已清理 $removed 个超过 ${RetentionDays} 天的旧备份" }

if ($mysqlOk -and $minioOk -and $AllmOk) { Write-Log "备份完成（全部成功）" }
else { Write-Log "备份完成（存在失败项，请检查上方日志）"; exit 1 }
