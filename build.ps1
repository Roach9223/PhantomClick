# Builds dist\PhantomClick.exe with PyInstaller under Python 3.11.
#
# 3.11 is not optional: rs3vision\_rs3vision.pyd is an abi3-py311 extension
# and the exe will fail on its first vision call under any other version.
#
#   pwsh -File build.ps1              # install deps, check backends, build
#   pwsh -File build.ps1 -SkipInstall # build only (deps already present)

param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# ---- Locate a Python 3.11 --------------------------------------------------

function Get-Python311 {
    # 1. The Windows launcher, which knows every registered install.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $v = & py -3.11 -c "import sys; print(sys.version_info[:2] == (3, 11))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -eq "True") {
            return @{ Exe = "py"; Args = @("-3.11") }
        }
    }
    # 2. Whatever `python` is on PATH, if it happens to be 3.11 (venvs).
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $v = & python -c "import sys; print(sys.version_info[:2] == (3, 11))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -eq "True") {
            return @{ Exe = "python"; Args = @() }
        }
    }
    return $null
}

$py = Get-Python311
if (-not $py) {
    Write-Host ""
    Write-Host "No Python 3.11 found." -ForegroundColor Red
    Write-Host "Install it from https://www.python.org/downloads/release/python-3119/"
    Write-Host "(or activate a 3.11 venv) and run this script again."
    exit 1
}
$exe = $py.Exe
$pyArgs = $py.Args
Write-Host "Using: $exe $($pyArgs -join ' ')" -ForegroundColor Cyan
& $exe @pyArgs -c "import sys; print(sys.executable, sys.version.split()[0])"

# ---- Dependencies -----------------------------------------------------------

if (-not $SkipInstall) {
    Write-Host "Installing requirements..." -ForegroundColor Cyan
    & $exe @pyArgs -m pip install -r requirements.txt -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }
}

# Optional keyboard backends. PyInstaller only bundles what it can import
# at build time, so a missing module here means the shipped exe silently
# lacks that backend and the Settings page will fall back to SendInput.
$optional = @(
    @{ Module = "serial";       Pip = "pyserial";            Backend = "Serial HID (Arduino)" },
    @{ Module = "interception"; Pip = "interception-python"; Backend = "Interception driver" }
)
foreach ($o in $optional) {
    & $exe @pyArgs -c "import $($o.Module)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARNING: '$($o.Module)' is not importable. The exe will not include the $($o.Backend) backend. Install with: pip install $($o.Pip)" -ForegroundColor Yellow
    }
}

# ---- Build stamp --------------------------------------------------------------
# ui/_build.py is committed with BUILD_HASH = "dev". The exe gets the real
# short hash and date so the deck's SYSTEM panel can name the build it is
# running. Rewritten in place; restored to the dev stamp after the build so
# the working tree stays clean.

$buildPy = Join-Path $PSScriptRoot "ui\_build.py"
$hash = "dev"
if (Get-Command git -ErrorAction SilentlyContinue) {
    $h = & git rev-parse --short HEAD 2>$null
    if ($LASTEXITCODE -eq 0 -and $h) { $hash = $h.Trim() }
}
$date = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
$stamp = @(
    '"""Build stamp. Rewritten by build.ps1 before PyInstaller runs; the',
    'committed copy is the dev stamp."""',
    '',
    "BUILD_HASH = `"$hash`"",
    "BUILD_DATE = `"$date`"",
    ''
) -join "`n"
$devStamp = @(
    '"""Build stamp. Rewritten by build.ps1 before PyInstaller runs; the',
    'committed copy is the dev stamp."""',
    '',
    'BUILD_HASH = "dev"',
    'BUILD_DATE = ""',
    ''
) -join "`n"
[System.IO.File]::WriteAllText($buildPy, $stamp)
Write-Host "Build stamp: $hash $date" -ForegroundColor Cyan

# ---- Build ------------------------------------------------------------------

try {
    & $exe @pyArgs -m PyInstaller PhantomClick.spec --noconfirm --clean
    $piExit = $LASTEXITCODE
} finally {
    [System.IO.File]::WriteAllText($buildPy, $devStamp)
}
if ($piExit -ne 0) { throw "PyInstaller failed (exit $piExit)" }

Write-Host ""
Write-Host "Built: dist\PhantomClick.exe" -ForegroundColor Green
