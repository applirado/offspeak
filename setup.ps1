<#
.SYNOPSIS
    Installs OffSpeak for the current user: uv, Python 3.12, all packages, a voice model,
    a Start menu shortcut, an entry in Settings > Apps, and autostart at sign-in.
    Safe to run again to update or repair.
.PARAMETER NoAutostart
    Do not start OffSpeak automatically when you sign in to Windows.
.PARAMETER NoModel
    Do not download the Parakeet voice model, even if it is not installed yet.
.PARAMETER NoLaunch
    Do not start OffSpeak when the setup is done.
.PARAMETER Uninstall
    Remove OffSpeak again (Settings > Apps runs this). Settings, history and models are kept.
#>
param(
    [switch]$NoAutostart,
    [switch]$NoModel,
    [switch]$NoLaunch,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest is very slow with the progress bar in PowerShell 5.1
$root = $PSScriptRoot
$scripts = Join-Path $root ".venv\Scripts"
$appExe = Join-Path $root ".venv\OffSpeak\OffSpeak.exe"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Programs")) "OffSpeak.lnk"
$appsKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\OffSpeak"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
# install.ps1 puts OffSpeak here; only this folder is deleted on uninstall, never a git checkout
$installDir = Join-Path $env:LOCALAPPDATA "Programs\OffSpeak"
$defaultVoiceModel = "parakeet-tdt-0.6b-v3"  # matches Mode.voice_model in config.py

function Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }

function Invoke-Checked {
    & $args[0] @($args | Select-Object -Skip 1)
    if ($LASTEXITCODE -ne 0) { throw "'$($args -join ' ')' failed with exit code $LASTEXITCODE" }
}

function Stop-OffSpeak {
    # only processes started from this folder
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -match '^(python|pythonw|offspeak|offspeakw)\.exe$' -and $_.CommandLine -like "*$root*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

# -- uninstall -----------------------------------------------------------------
if ($Uninstall) {
    Step "Removing OffSpeak"
    Stop-OffSpeak
    Remove-ItemProperty $runKey -Name "Offspeak" -ErrorAction SilentlyContinue  # winapi.RUN_VALUE
    Remove-Item $shortcutPath -ErrorAction SilentlyContinue
    Remove-Item $appsKey -Recurse -ErrorAction SilentlyContinue
    if ($root -eq $installDir) {
        # this script lives in the folder, so a separate process deletes it once this one has ended
        Start-Process cmd.exe -ArgumentList "/c timeout /t 2 >nul & rmdir /s /q `"$root`"" -WindowStyle Hidden
    } else {
        Remove-Item -Recurse -Force (Join-Path $root ".venv") -ErrorAction SilentlyContinue
    }
    $data = Join-Path $env:LOCALAPPDATA "Offspeak"
    Write-Host "`nOffSpeak is removed. Your settings, history and models are still in $data; delete that folder too if you no longer need them." -ForegroundColor Green
    exit 0
}

# -- uv (installs and manages Python itself) ---------------------------------
Step "Checking for uv"
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (-not (Test-Path $uv)) {
        Write-Host "uv not found, installing it from astral.sh"
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    }
    if (-not (Test-Path $uv)) { throw "uv was not installed to $uv; install it from https://docs.astral.sh/uv/ and run setup again." }
    $env:Path = "$(Split-Path $uv);$env:Path"
}
Invoke-Checked $uv --version

# -- Python 3.12 and packages --------------------------------------------------
Step "Installing Python 3.12 and OffSpeak's packages (this can take a few minutes the first time)"
Stop-OffSpeak  # an update replaces files the running app holds open
Push-Location $root
try {
    Invoke-Checked $uv sync --frozen --no-dev
} finally {
    Pop-Location
}
$offspeak = Join-Path $scripts "offspeak.exe"
if (-not (Test-Path $offspeak)) { throw "$offspeak is missing after 'uv sync'." }

# OffSpeak.exe runs the tray app; with plain pythonw.exe Windows lists its tray icon as "Python"
Invoke-Checked $offspeak create-exe --icon (Join-Path $root "assets\offspeak.ico")

# -- voice model ---------------------------------------------------------------
if (-not $NoModel) {
    Step "Checking for the voice model '$defaultVoiceModel'"
    $check = "import sys; from offspeak import models; from offspeak.config import Config; " +
             "sys.exit(0 if '$defaultVoiceModel' in models.voice_models(Config().settings.model_dirs()) else 1)"
    & (Join-Path $scripts "python.exe") -c $check
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Already installed."
    } else {
        Write-Host "Downloading '$defaultVoiceModel'"
        Invoke-Checked $offspeak download-model $defaultVoiceModel
    }
}

# -- Start menu shortcut and Settings > Apps -----------------------------------
Step "Creating the Start menu shortcut"
Remove-Item $shortcutPath -ErrorAction SilentlyContinue  # file names ignore case, so this also renames "Offspeak.lnk"
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
$shortcut.TargetPath = $appExe
$shortcut.Arguments = "-m offspeak run"
$shortcut.WorkingDirectory = $root
$shortcut.Description = "Offline voice dictation"
$shortcut.Save()
Write-Host $shortcutPath

$version = (Select-String -Path (Join-Path $root "pyproject.toml") -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
New-Item $appsKey -Force | Out-Null
$entry = @{
    DisplayName     = "OffSpeak"
    DisplayVersion  = $version
    Publisher       = "Applirado"
    DisplayIcon     = $appExe
    InstallLocation = $root
    URLInfoAbout    = "https://applirado.github.io/offspeak/"
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$root\setup.ps1`" -Uninstall"
}
foreach ($name in $entry.Keys) { Set-ItemProperty $appsKey -Name $name -Value $entry[$name] }
foreach ($name in "NoModify", "NoRepair") { Set-ItemProperty $appsKey -Name $name -Value 1 -Type DWord }

# -- autostart -----------------------------------------------------------------
Step "Configuring autostart"
Invoke-Checked $offspeak autostart $(if ($NoAutostart) { "off" } else { "on" })

if (-not $NoLaunch) {
    Step "Starting OffSpeak"
    Start-Process $appExe -ArgumentList "-m", "offspeak", "run"  # does nothing if it is already running
}

Write-Host "`nOffSpeak is installed." -ForegroundColor Green
