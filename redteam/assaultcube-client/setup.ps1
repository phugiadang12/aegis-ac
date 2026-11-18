<#
.SYNOPSIS
  Red team (optional): build the LAN-only lab cheat client (ESP + aimbot) for AssaultCube.

.DESCRIPTION
  Self-contained, so it can be used on its own to test any anti-cheat running
  on your own LAN AssaultCube server, not just Aegis.
  1. Clones AssaultCube at the tested commit (skipped if the folder already exists).
  2. Copies aegis_lab.h and applies client.patch (skipped if already applied).
  3. Builds bin_win32\ac_client_lab.exe with Visual Studio 2022 Build Tools.

  The client refuses to connect to any non-LAN address. That lock is in the code.

.EXAMPLE
  .\redteam\assaultcube-client\setup.ps1
#>
param(
    [string]$AcDir = (Join-Path $PSScriptRoot "..\..\assaultcube"),
    [switch]$SkipBuild
)
$ErrorActionPreference = "Continue"
$Commit = "13f0d8e"

function Fail($msg) { Write-Host "[aegis] $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path (Join-Path $AcDir ".git"))) {
    Write-Host "[aegis] cloning AssaultCube into $AcDir (large download, one time)"
    git clone https://github.com/assaultcube/AC.git $AcDir
    if ($LASTEXITCODE -ne 0) { Fail "git clone failed" }
    git -C $AcDir checkout -q $Commit
    if ($LASTEXITCODE -ne 0) { Fail "checkout $Commit failed" }
}
$AcDir = (Resolve-Path $AcDir).Path

Copy-Item (Join-Path $PSScriptRoot "aegis_lab.h") (Join-Path $AcDir "source\src\") -Force
$patch = (Resolve-Path (Join-Path $PSScriptRoot "client.patch")).Path
git -C $AcDir apply --reverse --check $patch 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[aegis] client patch already applied"
} else {
    git -C $AcDir apply $patch
    if ($LASTEXITCODE -ne 0) { Fail "client patch did not apply (is the source at $Commit?)" }
    Write-Host "[aegis] client patch applied"
}

if (-not $SkipBuild) {
    cmd /c "`"$PSScriptRoot\build.bat`" `"$AcDir`""
    if ($LASTEXITCODE -ne 0) { Fail "build failed" }
}
Write-Host "[aegis] done. Run it with:" -ForegroundColor Green
Write-Host "  cd `"$AcDir`"; .\bin_win32\ac_client_lab.exe --home=lab-home --init -t0 `"-ename Cheater; connect localhost`""
