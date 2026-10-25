<#
.SYNOPSIS
    Installs or updates OffSpeak from the latest release:
        powershell -c "irm https://applirado.github.io/offspeak/install.ps1 | iex"
    Downloads the source code of the latest release into %LOCALAPPDATA%\Programs\OffSpeak and runs its
    setup.ps1, which installs uv, Python, the packages and the voice model for the current user.
    No admin rights needed. Remove OffSpeak again under Settings > Apps.
#>
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest is very slow with the progress bar in PowerShell 5.1
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$dir = Join-Path $env:LOCALAPPDATA "Programs\OffSpeak"
# for tests: a local .zip of the source tree instead of the latest release
$zip = $env:OFFSPEAK_SOURCE_ZIP

if (-not $zip) {
    $release = Invoke-RestMethod "https://api.github.com/repos/applirado/offspeak/releases/latest"
    Write-Host "Downloading OffSpeak $($release.tag_name)"
    $zip = Join-Path $env:TEMP "offspeak-$($release.tag_name).zip"
    Invoke-WebRequest "https://github.com/applirado/offspeak/archive/refs/tags/$($release.tag_name).zip" -OutFile $zip
}
$unpacked = Join-Path $env:TEMP "offspeak-install"
Remove-Item -Recurse -Force $unpacked -ErrorAction SilentlyContinue
Expand-Archive $zip -DestinationPath $unpacked
$source = Get-ChildItem $unpacked -Directory | Select-Object -First 1  # GitHub puts everything in offspeak-<tag>\

# OffSpeak 0.2 and 0.3 came with an installer (.exe) that used the same folder; remove that first,
# it keeps settings, history and models in %LOCALAPPDATA%\Offspeak
$oldUninstaller = Join-Path $dir "unins000.exe"
if (Test-Path $oldUninstaller) {
    Write-Host "Removing the OffSpeak installed with the old setup program"
    Start-Process $oldUninstaller -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
    for ($i = 0; $i -lt 30 -and (Test-Path $oldUninstaller); $i++) { Start-Sleep 1 }  # it finishes from a temp copy
}

# replace the code, keep .venv so an update does not download all packages again
New-Item -ItemType Directory -Force $dir | Out-Null
Remove-Item -Recurse -Force (Join-Path $dir "src") -ErrorAction SilentlyContinue
Copy-Item (Join-Path $source.FullName "*") $dir -Recurse -Force
Remove-Item -Recurse -Force $unpacked
if (-not $env:OFFSPEAK_SOURCE_ZIP) { Remove-Item $zip }

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dir "setup.ps1")
if ($LASTEXITCODE -ne 0) { throw "OffSpeak's setup failed; see the messages above. Run the same command again to retry." }
