#!/usr/bin/env pwsh
#Requires -Version 5.1
<#
.SYNOPSIS
    Full ActivityWatch Tauri installer build for Windows.

.DESCRIPTION
    Runs 'make build' then 'make package' with TAURI_BUILD=true.
    Output: dist\activitywatch-setup.exe

.EXAMPLE
    .\scripts\build-tauri-win.ps1
    .\scripts\build-tauri-win.ps1 -SkipBuild         # package only (binary already built)
    .\scripts\build-tauri-win.ps1 -SkipPackage        # build only (no installer)
    .\scripts\build-tauri-win.ps1 -SkipServerRust     # skip aw-sync build
    .\scripts\build-tauri-win.ps1 -Python python3     # explicit Python binary
#>
param(
    # Python executable (default: python)
    [string]$Python = "python",
    # Poetry executable (default: poetry)
    [string]$Poetry = "poetry",
    # Skip 'make build' - use pre-existing binaries
    [switch]$SkipBuild,
    # Skip 'make package' - build only, no installer
    [switch]$SkipPackage,
    # Skip aw-server-rust (aw-sync) build
    [switch]$SkipServerRust,
    # Override TAURI_WATCHERS (default: aw-watcher-input aw-watcher-screenshot-mini aw-odoo-sync)
    [string]$TauriWatchers = ""
)

$ErrorActionPreference = "Stop"

# Move to repo root (script lives in scripts/)
$repoRoot = Split-Path $PSScriptRoot -Parent
Push-Location $repoRoot
try {

# locate make
$makeCommand = Get-Command make -ErrorAction SilentlyContinue
$make = if ($makeCommand) { $makeCommand.Source } else { $null }
if (-not $make) {
    foreach ($candidate in @(
        "$env:USERPROFILE\scoop\apps\make\current\bin\make.exe",
        "C:\Program Files\GnuWin32\bin\make.exe",
        "C:\msys64\usr\bin\make.exe"
    )) {
        if (Test-Path $candidate) { $make = $candidate; break }
    }
}
if (-not $make) {
    Write-Error "make not found in PATH. Install via: scoop install make"
    exit 1
}
Write-Host "[make] $make" -ForegroundColor DarkGray

# build args
$baseArgs = [System.Collections.Generic.List[string]]::new()
$baseArgs.Add("TAURI_BUILD=true")
$baseArgs.Add("PYTHON=$Python")
$baseArgs.Add("POETRY=$Poetry")
if ($SkipServerRust) { $baseArgs.Add("SKIP_SERVER_RUST=true") }
if ($TauriWatchers)  { $baseArgs.Add("TAURI_WATCHERS=$TauriWatchers") }

function Invoke-Make([string]$target) {
    $all = @($target) + $baseArgs
    Write-Host ""
    Write-Host "==> make $($all -join ' ')" -ForegroundColor Cyan
    $t0 = [System.Diagnostics.Stopwatch]::StartNew()
    & $make @all
    $t0.Stop()
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] make $target exited $LASTEXITCODE after $($t0.Elapsed.ToString('mm\:ss'))" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "[OK]   make $target done in $($t0.Elapsed.ToString('mm\:ss'))" -ForegroundColor Green
}

# build
if (-not $SkipBuild) {
    Invoke-Make "build"
}

# package
if (-not $SkipPackage) {
    Invoke-Make "package"
}

# report
Write-Host ""
$installer = Get-ChildItem "dist" -Filter "*setup*.exe" -ErrorAction SilentlyContinue |
             Sort-Object LastWriteTime -Descending |
             Select-Object -First 1
if ($installer) {
    $sizeMB = [math]::Round($installer.Length / 1MB, 1)
    Write-Host "Installer : $($installer.FullName)" -ForegroundColor Green
    Write-Host "Size      : ${sizeMB} MB"           -ForegroundColor Green
} else {
    Write-Host "No *setup*.exe found in dist\" -ForegroundColor Yellow
}

} finally {
    Pop-Location
}
