$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

try {
    & python -m PyInstaller --version | Out-Null
}
catch {
    throw "PyInstaller is not installed. Run: python -m pip install -r requirements-build.txt"
}

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Run: python -m pip install -r requirements-build.txt"
}

& python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name "GPO Halloween Macro" `
    gpo_halloween_macro_prototype.py

if ($LASTEXITCODE -ne 0) {
    throw "Windows build failed with exit code $LASTEXITCODE."
}

Write-Host "Build complete: $projectRoot\dist\GPO Halloween Macro\GPO Halloween Macro.exe"
