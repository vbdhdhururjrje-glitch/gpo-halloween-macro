param(
    [switch]$IncludePersonalProfile
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

function Invoke-Python {
    param([string[]]$Arguments)

    & python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

try {
    Invoke-Python -Arguments @("-m", "PyInstaller", "--version") | Out-Null
}
catch {
    throw "PyInstaller is not installed. Run: python -m pip install -r requirements-build.txt"
}

Invoke-Python -Arguments @(
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name",
    "GPO Halloween Macro",
    "gpo_halloween_macro_prototype.py"
)

$applicationDirectory = Join-Path $projectRoot "dist\GPO Halloween Macro"
$profileDirectory = Join-Path $applicationDirectory "profile"
if (Test-Path -LiteralPath $profileDirectory) {
    Remove-Item -LiteralPath $profileDirectory -Recurse -Force
}

$downloadInstructions = @"
GPO Halloween Macro - Windows

Download the latest release:
https://github.com/vbdhdhururjrje-glitch/gpo-halloween-macro/releases/latest

PowerShell:
`$zip = Join-Path `$HOME 'Downloads\GPO-Halloween-Macro-Windows.zip'
Invoke-WebRequest 'https://github.com/vbdhdhururjrje-glitch/gpo-halloween-macro/releases/latest/download/GPO-Halloween-Macro-Windows.zip' -OutFile `$zip
Expand-Archive -LiteralPath `$zip -DestinationPath (Join-Path `$HOME 'Downloads\GPO-Halloween-Macro') -Force
& (Join-Path `$HOME 'Downloads\GPO-Halloween-Macro\GPO Halloween Macro\Install-GPOHalloweenMacro.ps1') -ArchivePath `$zip

Official Windows Tesseract installer:
https://github.com/UB-Mannheim/tesseract/wiki

"@
Set-Content -LiteralPath (Join-Path $applicationDirectory "DOWNLOAD-AND-INSTALL.txt") -Value $downloadInstructions -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $projectRoot "Install-GPOHalloweenMacro.ps1") -Destination $applicationDirectory -Force

if ($IncludePersonalProfile) {
    $userDataDirectory = Join-Path $HOME "GPO_Halloween_Macro"
    $settingsPath = Join-Path $userDataDirectory "settings.json"
    if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
        throw "Personal settings were requested but not found: $settingsPath"
    }

    $settings = Get-Content -Raw -LiteralPath $settingsPath | ConvertFrom-Json
    $configuredRoute = [string]$settings.route_path
    $routePath = if ($configuredRoute) {
        [Environment]::ExpandEnvironmentVariables($configuredRoute)
    } else {
        Join-Path $userDataDirectory "route.json"
    }
    if (-not (Test-Path -LiteralPath $routePath -PathType Leaf)) {
        throw "Personal route was requested but not found: $routePath"
    }

    $settings.route_path = ""
    if ($null -eq $settings.ocr) {
        $settings | Add-Member -MemberType NoteProperty -Name ocr -Value ([pscustomobject]@{})
    }
    $settings.ocr.tesseract_cmd = ""
    $settings.door_cooldowns = @{}
    New-Item -ItemType Directory -Path $profileDirectory -Force | Out-Null
    $portableSettingsPath = Join-Path $profileDirectory "settings.json"
    $portableSettingsJson = $settings | ConvertTo-Json -Depth 50
    [System.IO.File]::WriteAllText(
        $portableSettingsPath,
        $portableSettingsJson,
        [System.Text.UTF8Encoding]::new($false)
    )
    Copy-Item -LiteralPath $routePath -Destination (Join-Path $profileDirectory "route.json") -Force
    Write-Host "Included the personal route and settings. Machine-specific paths were removed."
}

$archivePath = Join-Path $projectRoot "dist\GPO-Halloween-Macro-Windows.zip"
if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}
Compress-Archive -Path $applicationDirectory -DestinationPath $archivePath -CompressionLevel Optimal

Write-Host "Build complete: $projectRoot\dist\GPO Halloween Macro\GPO Halloween Macro.exe"
Write-Host "ZIP archive: $archivePath"
