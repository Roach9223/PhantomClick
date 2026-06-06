# Builds PhantomClick.exe with PyInstaller, pinned to Python 3.11
# (required by the rs3vision Rust core's ABI). Output: dist\PhantomClick.exe
$ErrorActionPreference = "Stop"

$py = "C:\Users\jrowb\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $py)) {
    # Fall back to the launcher's 3.11 if the absolute path moves.
    $py = "py"
    $pyArgs = @("-3.11")
} else {
    $pyArgs = @()
}

& $py @pyArgs -m PyInstaller PhantomClick.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Write-Host ""
Write-Host "Built: dist\PhantomClick.exe" -ForegroundColor Green
