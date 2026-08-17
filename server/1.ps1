param(
    [string]$AppRoot = $PSScriptRoot,
    [string]$BackendOrigin = "https://origin.toolpp.cn",
    [string]$PublicGateway = "https://docx.toolpp.cn"
)

$ErrorActionPreference = "Stop"

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor Cyan
}

function Get-EnvMap([string]$Path) {
    $result = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^\s*([A-Z][A-Z0-9_]*)=(.*)$') {
            $result[$matches[1]] = $matches[2].Trim()
        }
    }
    return $result
}

function Test-HttpUrl([string]$Name, [string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 15
        [pscustomobject]@{
            Name = $Name
            Url = $Url
            Status = [int]$response.StatusCode
            Result = "PASS"
            Detail = ""
        }
    }
    catch {
        $status = ""
        if ($_.Exception.Response) {
            try { $status = [int]$_.Exception.Response.StatusCode } catch {}
        }
        [pscustomobject]@{
            Name = $Name
            Url = $Url
            Status = $status
            Result = "FAIL"
            Detail = $_.Exception.Message
        }
    }
}

if ([string]::IsNullOrWhiteSpace($AppRoot)) {
    $AppRoot = (Get-Location).Path
}

$envFile = Join-Path $AppRoot ".env"

Write-Section "计划任务与本机监听"
$task = Get-ScheduledTask -TaskName "DocxtoolBackend" -ErrorAction SilentlyContinue
if ($task) {
    $taskInfo = Get-ScheduledTaskInfo -TaskName "DocxtoolBackend"
    [pscustomobject]@{
        State = $task.State
        LastRunTime = $taskInfo.LastRunTime
        LastTaskResult = $taskInfo.LastTaskResult
    } | Format-List
}
else {
    Write-Host "FAIL: 未找到 DocxtoolBackend 计划任务" -ForegroundColor Red
}

$listeners = Get-NetTCPConnection -LocalPort 9527 -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    $listeners | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize
}
else {
    Write-Host "FAIL: 9527 没有监听" -ForegroundColor Red
}

Write-Section "服务器配置（密钥不显示）"
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "未找到 $envFile"
}

$cfg = Get-EnvMap $envFile
$keys = @(
    "PRODUCTION_MODE",
    "FRONTEND_ORIGIN",
    "ADMIN_CONSOLE_ORIGIN",
    "COOKIE_SECURE",
    "ADMIN_COOKIE_SECURE",
    "TRUST_PROXY_HEADERS",
    "TRUSTED_PROXY_IPS",
    "ADMIN_TOKEN",
    "PROXY_SECRET"
)

foreach ($key in $keys) {
    $value = $cfg[$key]
    if ($key -in @("ADMIN_TOKEN", "PROXY_SECRET")) {
        $display = if ($value) { "SET(length=$($value.Length))" } else { "MISSING" }
    }
    else {
        $display = if ($null -eq $value) { "MISSING" } else { $value }
    }
    "{0}={1}" -f $key, $display
}

if ($cfg["ADMIN_TOKEN"] -and $cfg["PROXY_SECRET"] -and
    $cfg["ADMIN_TOKEN"] -eq $cfg["PROXY_SECRET"]) {
    Write-Host "FAIL: ADMIN_TOKEN 与 PROXY_SECRET 相同" -ForegroundColor Red
}

Write-Section "本机、Origin 与公网网关联通性"
$local = Test-HttpUrl "本机后端" "http://127.0.0.1:9527/health"
$origin = Test-HttpUrl "后端 Origin" ($BackendOrigin.TrimEnd("/") + "/health")
$gateway = Test-HttpUrl "公网网关" ($PublicGateway.TrimEnd("/") + "/api/health")

@($local, $origin, $gateway) |
    Select-Object Name, Status, Result, Url, Detail |
    Format-Table -Wrap -AutoSize

Write-Section "最近后端错误（已脱敏）"
$logFile = Join-Path $AppRoot "var\logs\公文排版工具.log"
if (Test-Path -LiteralPath $logFile) {
    Get-Content -LiteralPath $logFile -Tail 100 |
        Where-Object { $_ -match '\[(ERROR|WARNING)\]|error|failed|exception|proxy|upload' } |
        ForEach-Object {
            $_ -replace '(?i)(ADMIN_TOKEN|PROXY_SECRET|Authorization|Cookie)\s*[:=]\s*\S+', '$1=<redacted>'
        }
}
else {
    Write-Host "未找到后端日志：$logFile"
}

Write-Section "结论"
if ($local.Result -eq "PASS" -and ($origin.Result -ne "PASS" -or $gateway.Result -ne "PASS")) {
    Write-Host "本机后端正常，问题在 HTTPS Origin / Cloudflare Pages Worker 回源配置。" -ForegroundColor Yellow
}
elseif ($local.Result -ne "PASS") {
    Write-Host "本机后端未正常运行，先检查计划任务和后端日志。" -ForegroundColor Red
}
elseif ($gateway.Result -ne "PASS") {
    Write-Host "Pages 到后端的链路异常；重点核对 BACKEND_BASE_URL 和 PROXY_SECRET。" -ForegroundColor Yellow
}
else {
    Write-Host "基础链路正常；若上传仍失败，请提供浏览器 Network 中 /api/upload 的状态码与响应正文。" -ForegroundColor Green
}
