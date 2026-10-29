$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = (Get-ChildItem -LiteralPath $here -Filter '*.exe' | Select-Object -First 1).FullName
if (-not $exe -or -not (Test-Path $exe)) {
    Write-Host "[ERROR] launcher exe not found under: $here" -ForegroundColor Red
    exit 1
}

$taskName = 'DailyLauncher'

Write-Host "Launcher : $exe"
Write-Host "Task name: $taskName"
Write-Host ""

# ---- 1) 创建计划任务（最高权限运行，不弹 UAC） ----
try {
    $action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $here
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
                                            -DontStopIfGoingOnBatteries `
                                            -StartWhenAvailable `
                                            -ExecutionTimeLimit ([TimeSpan]::Zero)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
                                            -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal `
                           -Settings $settings -Force | Out-Null
    Write-Host "[1/2] scheduled task created" -ForegroundColor Green
} catch {
    Write-Host ("[1/2] FAILED to create task: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}

# ---- 2) 桌面快捷方式 ----
try {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $lnkName = [System.IO.Path]::GetFileNameWithoutExtension($exe) + '.lnk'
    $lnkPath = Join-Path $desktop $lnkName
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($lnkPath)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $here
    $lnk.IconLocation = "$exe,0"
    $lnk.Description = 'Daily launcher (no UAC) / 一键日常启动器'
    $lnk.Save()
    Write-Host "[2/2] desktop shortcut: $lnkPath" -ForegroundColor Green
} catch {
    Write-Host ("[2/2] shortcut failed: " + $_.Exception.Message) -ForegroundColor Yellow
}

# ---- 3) 阻止 Nahimic 等第三方 DLL 注入 MAA ----
# MAA 启动时报：C:\ProgramData\A-Volute\A-Volute.Nahimic\...\AudioDevProps2.dll
# 注入的 DLL 会破坏 WPF 渲染和 ONNX/DML 推理（闪退、界面异常、OCR 失败）。
# 用 Windows 攻击防护的"禁用扩展点"从系统层面挡掉，不影响音频功能。
$maaExe = $null
try {
    $cfgPath = Join-Path $here 'config.json'
    if (Test-Path $cfgPath) {
        $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.maa -and $cfg.maa.path -and (Test-Path $cfg.maa.path)) {
            $maaExe = Split-Path -Leaf $cfg.maa.path
        }
    }
} catch { }
if (-not $maaExe) { $maaExe = 'MAA.exe' }

try {
    Set-ProcessMitigation -Name $maaExe -Enable DisableExtensionPoints -ErrorAction Stop
    Write-Host "" -ForegroundColor Green
    Write-Host "[3/3] DLL injection blocked for $maaExe" -ForegroundColor Green
    Write-Host "      (this is what MAA warns about: Nahimic AudioDevProps2.dll)" -ForegroundColor Green
} catch {
    Write-Host "" -ForegroundColor Yellow
    Write-Host ("[3/3] could not set mitigation for " + $maaExe + ": " + $_.Exception.Message) -ForegroundColor Yellow
    Write-Host "      Manual path: Windows Security -> App & browser control ->" -ForegroundColor Yellow
    Write-Host "      Exploit protection -> Program settings -> add MAA.exe ->" -ForegroundColor Yellow
    Write-Host "      'Disable extension points' = Override system settings (On)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. From now on, double-click the launcher (or the desktop shortcut)."
Write-Host "It will start as administrator WITHOUT a UAC prompt, so MuMu's device"
Write-Host "process also inherits the rights and stops asking."
Write-Host ""
Write-Host "To undo:  schtasks /delete /tn $taskName /f"
