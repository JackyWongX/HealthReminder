$ErrorActionPreference = "Stop"

$taskName = "HealthReminder"
$scriptPath = Join-Path $PSScriptRoot "health_reminder.py"
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not (Test-Path $scriptPath)) {
    throw "找不到程序脚本：$scriptPath"
}

$pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pythonLauncher) {
    $pythonPath = (& $pythonLauncher.Source -3 -c "import sys; print(sys.executable)" | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $pythonPath) {
        throw "无法通过 Python Launcher 找到 Python 3。"
    }
    $pythonwPath = Join-Path (Split-Path -Parent $pythonPath) "pythonw.exe"
} else {
    $pythonwCommand = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if (-not $pythonwCommand) {
        throw "未找到 Python 3。请安装 Python，并确保 py.exe 或 pythonw.exe 在 PATH 中。"
    }
    $pythonwPath = $pythonwCommand.Source
}

if (-not (Test-Path $pythonwPath)) {
    throw "找不到 pythonw.exe：$pythonwPath"
}

$action = New-ScheduledTaskAction `
    -Execute $pythonwPath `
    -Argument ('"{0}"' -f $scriptPath) `
    -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$trigger.Delay = "PT30S"
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "用户登录后延迟 30 秒在后台启动健康提醒。" `
    -Force | Out-Null

Write-Host "已创建计划任务：$taskName（登录后延迟 30 秒启动）"