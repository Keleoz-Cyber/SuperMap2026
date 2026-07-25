# GeoModelingPlatform v0.4.1 答辩演示启动脚本（Windows 单机）
# 安全约束：不安装依赖、不删除数据、不结束任何进程、不写入凭据；
# 前端日志保留在当前窗口，便于现场诊断。
# 用法：scripts/start_demo.ps1 [-HostAddress 127.0.0.1] [-Port 8000] [-DataDir var/demo_v041] [-NoBrowser] [-CheckOnly]
param(
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8000,
  [string]$DataDir = "var/demo_v041",
  [switch]$NoBrowser,
  [switch]$CheckOnly
)

# 1. 独立数据目录（默认 var/demo_v041，与日常开发库隔离）
$env:GEOMODELING_DATA_DIR = $DataDir

# 2. 启动前检查（即使退出码 1 也要解析完整 JSON 报告）
# stdout/stderr 分离到临时文件：崩溃或附加输出可诊断，不会静默吞掉
$outFile = Join-Path $env:TEMP "geomodeling-demo-check-out.json"
$errFile = Join-Path $env:TEMP "geomodeling-demo-check-err.log"
geomodeling demo-check --json --host $HostAddress --port $Port --data-dir $DataDir > $outFile 2> $errFile
$checkExit = $LASTEXITCODE
$report = $null
try {
  $report = (Get-Content $outFile -Raw).Trim() | ConvertFrom-Json
} catch {
  $report = $null
}
if ($null -eq $report -or $null -eq $report.checks) {
  Write-Host "demo-check 输出无法解析为 JSON，stdout 与 stderr 如下："
  Get-Content $outFile | ForEach-Object { Write-Host $_ }
  Get-Content $errFile | ForEach-Object { Write-Host $_ }
  exit 1
}
foreach ($c in $report.checks) {
  $tag = "[PASSED]"
  if ($c.status -eq "warning") { $tag = "[WARNING]" }
  elseif ($c.status -eq "blocked") { $tag = "[BLOCKED]" }
  Write-Host "$tag $($c.id): $($c.message)"
}
if ($checkExit -ne 0) {
  Write-Host "预检存在阻断项，请按上面的修复建议处理后重试。"
  exit $checkExit
}

# 3. 端口上已是本平台健康实例 → 直接复用，不重启
if ($report.reuse_existing) {
  Write-Host "检测到 http://${HostAddress}:${Port}/ 已是本平台健康实例，直接复用。"
  if (-not $NoBrowser) { cmd /c start "" "http://${HostAddress}:${Port}/" }
  exit 0
}

if ($CheckOnly) {
  Write-Host "CheckOnly：预检完成，不启动服务。"
  exit 0
}

# 4. 前台启动单进程后端；后台只做有界健康等待后打开浏览器
Write-Host "启动 GeoModelingPlatform：http://${HostAddress}:${Port}/ （Ctrl+C 停止）"
if (-not $NoBrowser) {
  $null = Start-Job -ScriptBlock {
    param($u)
    for ($i = 0; $i -lt 60; $i++) {
      try {
        $h = Invoke-RestMethod -Uri "$u/api/health" -TimeoutSec 2
        if ($h.status -eq "ok") { cmd /c start "" $u; break }
      } catch {
        Start-Sleep -Seconds 1
      }
    }
  } -ArgumentList "http://${HostAddress}:${Port}/"
}

python -m uvicorn geomodeling.api.app:app --host $HostAddress --port $Port --workers 1
