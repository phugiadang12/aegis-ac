<#
.SYNOPSIS
  Blue team: get AssaultCube's source, add the Aegis telemetry patch, build the server.

.DESCRIPTION
  1. Clones AssaultCube at the tested commit (skipped if the folder already exists).
  2. Copies telemetry.h and applies server.cpp.patch (skipped if already applied).
  3. Builds bin_win32\ac_server_aegis.exe with Visual Studio 2022 Build Tools.
  Safe to run again.

.EXAMPLE
  .\integrations\assaultcube\setup.ps1
  .\integrations\assaultcube\setup.ps1 -AcDir D:\src\assaultcube
#>
param(
    [string]$AcDir = (Join-Path $PSScriptRoot "..\..\assaultcube"),
    [switch]$SkipBuild
)
$ErrorActionPreference = "Continue"
$Commit = "13f0d8e"   # AssaultCube v1.3.0.2 line, protocol 1300

function Fail($msg) { Write-Host "[aegis] $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path (Join-Path $AcDir ".git"))) {
    Write-Host "[aegis] cloning AssaultCube into $AcDir (large download, one time)"
    git clone https://github.com/assaultcube/AC.git $AcDir
    if ($LASTEXITCODE -ne 0) { Fail "git clone failed" }
    git -C $AcDir checkout -q $Commit
    if ($LASTEXITCODE -ne 0) { Fail "checkout $Commit failed" }
}
$AcDir = (Resolve-Path $AcDir).Path

Copy-Item (Join-Path $PSScriptRoot "telemetry.h") (Join-Path $AcDir "source\src\") -Force
$patch = (Resolve-Path (Join-Path $PSScriptRoot "server.cpp.patch")).Path
git -C $AcDir apply --reverse --check $patch 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[aegis] server patch already applied"
} else {
    git -C $AcDir apply $patch
    if ($LASTEXITCODE -ne 0) { Fail "server patch did not apply (is the source at $Commit?)" }
    Write-Host "[aegis] server patch applied"
}

if (-not $SkipBuild) {
    cmd /c "`"$PSScriptRoot\build.bat`" `"$AcDir`""
    if ($LASTEXITCODE -ne 0) { Fail "build failed" }
}
Write-Host "[aegis] done. Start it with:  cd `"$AcDir`"; .\bin_win32\ac_server_aegis.exe" -ForegroundColor Green
