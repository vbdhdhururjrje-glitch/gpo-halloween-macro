param(
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA "Programs\GPO Halloween Macro"),
    [string]$UserDataDirectory = (Join-Path $HOME "GPO_Halloween_Macro"),
    [string]$ArchivePath,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$releaseUrl = "https://github.com/vbdhdhururjrje-glitch/gpo-halloween-macro/releases/latest/download/GPO-Halloween-Macro-Windows.zip"
$downloadDirectory = Join-Path $env:TEMP ("GPO-Halloween-Macro-" + [guid]::NewGuid().ToString("N"))
$downloadedArchivePath = Join-Path $downloadDirectory "GPO-Halloween-Macro-Windows.zip"
$extractDirectory = Join-Path $downloadDirectory "extracted"
$applicationName = "GPO Halloween Macro"
$executableName = "GPO Halloween Macro.exe"

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    New-Item -ItemType Directory -Path $extractDirectory -Force | Out-Null
    if ($ArchivePath) {
        if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
            throw "The specified archive does not exist: $ArchivePath"
        }
        $sourceArchivePath = (Resolve-Path -LiteralPath $ArchivePath).Path
    } else {
        Write-Host "Downloading the latest Windows release..."
        Invoke-WebRequest -Uri $releaseUrl -OutFile $downloadedArchivePath
        $sourceArchivePath = $downloadedArchivePath
    }
    Expand-Archive -LiteralPath $sourceArchivePath -DestinationPath $extractDirectory -Force

    $applicationSource = Join-Path $extractDirectory $applicationName
    $executableSource = Join-Path $applicationSource $executableName
    if (-not (Test-Path -LiteralPath $executableSource -PathType Leaf)) {
        throw "The downloaded archive does not contain $executableName."
    }

    New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
    Copy-Item -Path (Join-Path $applicationSource "*") -Destination $InstallDirectory -Recurse -Force

    $settingsDestination = Join-Path $UserDataDirectory "settings.json"
    $routeDestination = Join-Path $UserDataDirectory "route.json"
    $profileDirectory = Join-Path $InstallDirectory "profile"
    $settingsSource = Join-Path $profileDirectory "settings.json"
    $routeSource = Join-Path $profileDirectory "route.json"

    if ((Test-Path -LiteralPath $settingsSource -PathType Leaf) -and
        (Test-Path -LiteralPath $routeSource -PathType Leaf)) {
        if (-not (Test-Path -LiteralPath $settingsDestination) -and
            -not (Test-Path -LiteralPath $routeDestination)) {
            New-Item -ItemType Directory -Path $UserDataDirectory -Force | Out-Null
            Copy-Item -LiteralPath $settingsSource -Destination $settingsDestination
            Copy-Item -LiteralPath $routeSource -Destination $routeDestination
            Write-Host "Imported the bundled sample route and settings."
        } else {
            Write-Host "Existing settings or route found; keeping them and skipping the sample profile."
        }
    }

    $executablePath = Join-Path $InstallDirectory $executableName
    Write-Host "Installed to: $InstallDirectory"
    if (-not $NoLaunch) {
        Start-Process -FilePath $executablePath -WorkingDirectory $InstallDirectory
    }
}
finally {
    if (Test-Path -LiteralPath $downloadDirectory) {
        Remove-Item -LiteralPath $downloadDirectory -Recurse -Force
    }
}
