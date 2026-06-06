# lib/download.ps1 — fetch Win11 ISO + VirtualBox Extension Pack into .vm/
#
# Both downloads are idempotent (skipped when target file exists with sane
# size). The ISO uses Fido (https://github.com/pbatard/Fido), a community-
# maintained PS script that scrapes Microsoft's session-tokened URLs without
# requiring a Microsoft account. We download Fido on demand into the extpack
# cache and run it; if Microsoft changes their flow and Fido breaks, the
# script tells the user where to drop a hand-downloaded ISO and exits cleanly.
#
# Extension Pack version is pinned to whatever VBox is installed locally
# (queried via VBoxManage --version) so we never mismatch.

# -- Sizes used for "looks complete?" sanity check -------------------------
$Script:DownloadIsoMinSizeMb     = 4500   # Win11 ISO is ~5–6 GB
$Script:DownloadExtpackMinSizeKb = 5000   # extpack is ~10–25 MB

function Get-VBoxInstalledVersion {
    Assert-VBoxManage
    # VBoxManage --version returns e.g. "7.0.20r163906". We only want the dotted version.
    $raw = (& $Script:VBoxManage --version 2>$null).Trim()
    if ($raw -match '^(\d+\.\d+\.\d+)') { return $Matches[1] }
    throw "Could not parse VBoxManage --version output: '$raw'"
}

function Get-IsoPath {
    return Join-Path $Script:IsoDir 'Win11_x64.iso'
}

function Get-ExtpackPath {
    param([string]$Version)
    return Join-Path $Script:ExtpackDir "Oracle_VM_VirtualBox_Extension_Pack-$Version.vbox-extpack"
}

function Test-FileLooksComplete {
    param([string]$Path, [int]$MinKb = 100)
    if (-not (Test-Path $Path)) { return $false }
    return ((Get-Item $Path).Length / 1KB) -ge $MinKb
}

# -- ISO download via Fido --------------------------------------------------
function Get-FidoScript {
    $fidoPath = Join-Path $Script:VmRoot 'fido.ps1'
    if (Test-Path $fidoPath) { return $fidoPath }
    Write-Info "Downloading Fido.ps1 (Microsoft ISO scraper)..."
    $url = 'https://raw.githubusercontent.com/pbatard/Fido/master/Fido.ps1'
    Invoke-WebRequest -Uri $url -OutFile $fidoPath -UseBasicParsing
    return $fidoPath
}

function Invoke-DownloadIso {
    $iso = Get-IsoPath
    if (Test-FileLooksComplete -Path $iso -MinKb ($Script:DownloadIsoMinSizeMb * 1024)) {
        Write-Ok "ISO already cached: $iso"
        return
    }
    if (-not (Test-Path $Script:IsoDir)) { New-Item -ItemType Directory -Force -Path $Script:IsoDir | Out-Null }
    Write-Step "Downloading Windows 11 ISO via Fido (~5 GB, this takes a while)"
    try {
        $fido = Get-FidoScript
        # Fido args: Win=11, Edition=Pro, Lang=English, Arch=x64, GetUrl=true returns the URL.
        $url = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $fido `
            -Win 11 -Rel Latest -Ed Pro -Lang English -Arch x64 -GetUrl 2>$null
        if (-not $url -or $url -notmatch '^https?://') {
            throw "Fido returned no URL (Microsoft may have changed their flow)."
        }
        Write-Info "Fetched URL: $($url.Substring(0, [Math]::Min(80, $url.Length)))..."
        Invoke-WebRequest -Uri $url -OutFile $iso -UseBasicParsing
        Write-Ok "ISO saved: $iso"
    }
    catch {
        Write-WarnMsg "Auto-download failed: $($_.Exception.Message)"
        Write-Host ""
        Write-Host "Manual fallback:" -ForegroundColor Yellow
        Write-Host "  1. Visit https://www.microsoft.com/software-download/windows11"
        Write-Host "  2. Download the multi-edition x64 ISO (English)."
        Write-Host "  3. Place it at:"
        Write-Host "       $iso"
        Write-Host "  4. Re-run 'phantom-vm.ps1 provision'."
        throw "ISO download incomplete."
    }
}

# -- Extension Pack download -----------------------------------------------
function Invoke-DownloadExtpack {
    if (-not (Test-Path $Script:ExtpackDir)) {
        New-Item -ItemType Directory -Force -Path $Script:ExtpackDir | Out-Null
    }
    $version = Get-VBoxInstalledVersion
    $extpack = Get-ExtpackPath -Version $version
    if (Test-FileLooksComplete -Path $extpack -MinKb $Script:DownloadExtpackMinSizeKb) {
        Write-Ok "Extension Pack already cached: $extpack"
        return $extpack
    }
    $url = "https://download.virtualbox.org/virtualbox/$version/Oracle_VM_VirtualBox_Extension_Pack-$version.vbox-extpack"
    Write-Step "Downloading VBox Extension Pack $version"
    Write-Info $url
    try {
        Invoke-WebRequest -Uri $url -OutFile $extpack -UseBasicParsing
    }
    catch {
        Write-ErrMsg "Extension Pack download failed: $($_.Exception.Message)"
        Write-Host "Try: https://www.virtualbox.org/wiki/Downloads (manual download)"
        Write-Host "Place the .vbox-extpack file at: $extpack"
        throw
    }
    Write-Ok "Extension Pack saved: $extpack"
    return $extpack
}

function Test-ExtpackInstalled {
    param([string]$Version)
    $list = & $Script:VBoxManage list extpacks 2>$null
    if ($list -match 'Oracle VM VirtualBox Extension Pack' -and $list -match $Version) {
        return $true
    }
    return $false
}

function Install-Extpack {
    $version = Get-VBoxInstalledVersion
    if (Test-ExtpackInstalled -Version $version) {
        Write-Ok "Extension Pack $version already installed in VBox"
        return
    }
    $extpack = Get-ExtpackPath -Version $version
    if (-not (Test-Path $extpack)) { Invoke-DownloadExtpack | Out-Null }
    Write-Step "Installing Extension Pack into VirtualBox (admin elevation likely required)"
    Write-Info "Accepting license automatically; the user-facing prompt is bypassed."
    # --replace works around a previously-installed wrong-version pack.
    & $Script:VBoxManage extpack install --replace --accept-license=eb31505e56e9b4d0fbca139104da41ac6f6b98f8e78968bdf16443bd6d7df40b $extpack
    if ($LASTEXITCODE -ne 0) {
        # The license SHA is version-specific; a mismatch flow falls through here.
        # Fall back to interactive install.
        Write-WarnMsg "Auto-license-accept failed. Trying interactive install (you'll see a prompt)."
        & $Script:VBoxManage extpack install --replace $extpack
        if ($LASTEXITCODE -ne 0) { throw "Extension Pack install failed." }
    }
    Write-Ok "Extension Pack installed."
}

# -- Public dispatcher ------------------------------------------------------
function Invoke-Download {
    Write-Step "Verifying / fetching artifacts under $Script:VmRoot"
    Invoke-DownloadIso
    Invoke-DownloadExtpack | Out-Null
    Write-Ok "All artifacts ready."
}
