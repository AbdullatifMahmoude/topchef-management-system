<# 
.SYNOPSIS
    Build script for Top Chef Desktop POS
.DESCRIPTION
    1. Installs desktop dependencies
    2. Runs PyInstaller
    3. Copies runtime assets
    4. Optionally compiles Inno Setup installer
#>

param(
    [switch]$SkipInstall,
    [switch]$SkipInstaller,
    [string]$InnoSetupPath = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildDir    = $PSScriptRoot
$DistDir     = Join-Path $BuildDir "dist\TopChef"

Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Top Chef Desktop POS — Build Script" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── 1. Install dependencies ──────────────────
if (-not $SkipInstall) {
    Write-Host "[1/4] Installing desktop dependencies …" -ForegroundColor Yellow
    Push-Location $ProjectRoot
    pip install -r requirements-desktop.txt --quiet
    Pop-Location
    Write-Host "      ✓ Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "[1/4] Skipping dependency install" -ForegroundColor DarkGray
}

# ── 2. Run PyInstaller ───────────────────────
Write-Host "[2/4] Running PyInstaller …" -ForegroundColor Yellow
Push-Location $BuildDir

# Clean previous build
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build_temp") { Remove-Item -Recurse -Force "build_temp" }

pyinstaller topchef_desktop.spec --clean --workpath build_temp --distpath dist 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ PyInstaller failed!" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location
Write-Host "      ✓ EXE built → $DistDir" -ForegroundColor Green

# ── 3. Copy runtime files ────────────────────
Write-Host "[3/4] Copying runtime files …" -ForegroundColor Yellow

# settings.json
Copy-Item (Join-Path $ProjectRoot "desktop\settings.json") $DistDir -Force

# version.txt
Copy-Item (Join-Path $ProjectRoot "desktop\version.txt") $DistDir -Force

# assets folder
$AssetsSource = Join-Path $ProjectRoot "desktop\assets"
$AssetsDest   = Join-Path $DistDir "assets"
if (-not (Test-Path $AssetsDest)) { New-Item -ItemType Directory -Path $AssetsDest | Out-Null }
if (Test-Path $AssetsSource) {
    Copy-Item "$AssetsSource\*" $AssetsDest -Recurse -Force -ErrorAction SilentlyContinue
}

# Create empty data/logs dirs
New-Item -ItemType Directory -Path (Join-Path $DistDir "data")   -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $DistDir "logs")   -Force | Out-Null

Write-Host "      ✓ Runtime files copied" -ForegroundColor Green

# ── 4. Compile Inno Setup installer ──────────
if (-not $SkipInstaller) {
    if (Test-Path $InnoSetupPath) {
        Write-Host "[4/4] Compiling Inno Setup installer …" -ForegroundColor Yellow
        $IssFile = Join-Path $PSScriptRoot "..\installer\topchef_setup.iss"
        & $InnoSetupPath $IssFile
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ✗ Inno Setup failed!" -ForegroundColor Red
        } else {
            Write-Host "      ✓ Installer created" -ForegroundColor Green
        }
    } else {
        Write-Host "[4/4] Inno Setup not found at: $InnoSetupPath" -ForegroundColor DarkGray
        Write-Host "      Download from: https://jrsoftware.org/isinfo.php" -ForegroundColor DarkGray
    }
} else {
    Write-Host "[4/4] Skipping installer" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "══════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Build complete! Output: $DistDir" -ForegroundColor Green
Write-Host "══════════════════════════════════════════════" -ForegroundColor Green
