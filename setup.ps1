<#
.SYNOPSIS
    Installs Offspeak for the current user: uv, Python 3.12, all packages, a voice model,
    a Start menu shortcut, and autostart at sign-in. Safe to run again to update or repair.
.PARAMETER NoAutostart
    Do not start Offspeak automatically when you sign in to Windows.
.PARAMETER NoModel
    Do not download the Parakeet voice model, even if it is not installed yet.
.PARAMETER NoLaunch
    Do not start Offspeak when the setup is done.
#>
param(
    [switch]$NoAutostart,
    [switch]$NoModel,
    [switch]$NoLaunch
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
Step "Installing Python 3.12 and Offspeak's packages (this can take a few minutes the first time)"
Push-Location $root
try {
    Invoke-Checked $uv sync --frozen --no-dev
} finally {
    Pop-Location
}
$offspeak = Join-Path $scripts "offspeak.exe"
$offspeakw = Join-Path $scripts "offspeakw.exe"
if (-not (Test-Path $offspeakw)) { throw "$offspeakw is missing after 'uv sync'." }

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

# -- Start menu shortcut -------------------------------------------------------
Step "Creating the Start menu shortcut"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Programs")) "Offspeak.lnk"
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
$shortcut.TargetPath = $offspeakw
$shortcut.Arguments = "run"
$shortcut.WorkingDirectory = $root
$shortcut.Description = "Offline voice dictation"
$shortcut.Save()
Write-Host $shortcutPath

# -- autostart -----------------------------------------------------------------
Step "Configuring autostart"
Invoke-Checked $offspeak autostart $(if ($NoAutostart) { "off" } else { "on" })

if (-not $NoLaunch) {
    Step "Starting Offspeak"
    Start-Process $offspeakw -ArgumentList "run"  # does nothing if it is already running
}

Write-Host "`nOffspeak is installed." -ForegroundColor Green
