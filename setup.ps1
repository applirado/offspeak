<#
.SYNOPSIS
    Installs OffSpeak for the current user: uv, Python 3.12, all packages, a voice model,
    a Start menu shortcut, and autostart at sign-in. Safe to run again to update or repair.
.PARAMETER NoAutostart
    Do not start OffSpeak automatically when you sign in to Windows.
.PARAMETER NoModel
    Do not download the Parakeet voice model, even if it is not installed yet.
.PARAMETER NoLaunch
    Do not start OffSpeak when the setup is done.
.PARAMETER Installer
    Used by OffSpeak-Setup.exe: use the bundled uv, keep Python inside this folder, and leave the
    Start menu shortcut, autostart and launch to the installer.
#>
param(
    [switch]$NoAutostart,
    [switch]$NoModel,
    [switch]$NoLaunch,
    [switch]$Installer
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest is very slow with the progress bar in PowerShell 5.1
$root = $PSScriptRoot
$scripts = Join-Path $root ".venv\Scripts"
$defaultVoiceModel = "parakeet-tdt-0.6b-v3"  # matches Mode.voice_model in config.py

function Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }

function Invoke-Checked {
    & $args[0] @($args | Select-Object -Skip 1)
    if ($LASTEXITCODE -ne 0) { throw "'$($args -join ' ')' failed with exit code $LASTEXITCODE" }
}

# -- uv (installs and manages Python itself) ---------------------------------
Step "Checking for uv"
if ($Installer) {
    # everything lives in the install folder, so uninstalling leaves nothing behind
    $uv = Join-Path $root "bin\uv.exe"
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $root "python"
    $env:UV_PYTHON_PREFERENCE = "only-managed"
    $env:UV_CACHE_DIR = Join-Path $env:TEMP "offspeak-setup-uv-cache"
    if (-not (Test-Path $uv)) { throw "The bundled uv is missing: $uv" }
} else {
    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
}
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
Push-Location $root
try {
    Invoke-Checked $uv sync --frozen --no-dev
} finally {
    Pop-Location
    if ($Installer) { Remove-Item -Recurse -Force $env:UV_CACHE_DIR -ErrorAction SilentlyContinue }
}
$offspeak = Join-Path $scripts "offspeak.exe"
$offspeakw = Join-Path $scripts "offspeakw.exe"
if (-not (Test-Path $offspeakw)) { throw "$offspeakw is missing after 'uv sync'." }

# OffSpeak.exe runs the tray app; with plain pythonw.exe Windows lists its tray icon as "Python"
$icon = @((Join-Path $root "offspeak.ico"), (Join-Path $root "assets\offspeak.ico")) | Where-Object { Test-Path $_ } | Select-Object -First 1
Invoke-Checked $offspeak create-exe --icon $icon
$appExe = Join-Path $root ".venv\OffSpeak\OffSpeak.exe"

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

if ($Installer) {
    Write-Host "`nOffSpeak is installed." -ForegroundColor Green
    exit 0  # the installer creates the shortcut and the autostart entry and starts OffSpeak itself
}

# -- Start menu shortcut -------------------------------------------------------
Step "Creating the Start menu shortcut"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Programs")) "OffSpeak.lnk"
Remove-Item $shortcutPath -ErrorAction SilentlyContinue  # file names ignore case, so this also renames "Offspeak.lnk"
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
$shortcut.TargetPath = $appExe
$shortcut.Arguments = "-m offspeak run"
$shortcut.WorkingDirectory = $root
$shortcut.Description = "Offline voice dictation"
$shortcut.Save()
Write-Host $shortcutPath

# -- autostart -----------------------------------------------------------------
Step "Configuring autostart"
Invoke-Checked $offspeak autostart $(if ($NoAutostart) { "off" } else { "on" })

if (-not $NoLaunch) {
    Step "Starting OffSpeak"
    Start-Process $appExe -ArgumentList "-m", "offspeak", "run"  # does nothing if it is already running
}

Write-Host "`nOffSpeak is installed." -ForegroundColor Green
