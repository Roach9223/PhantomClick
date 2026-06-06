# lib/provision.ps1 — one-shot orchestrator: download artifacts, install
# Extension Pack, create the VM, apply stealth + USB filter, and start the
# unattended Windows install.
#
# All steps are idempotent so re-running on a half-finished setup picks up
# where it left off.

function Test-VBoxVersion {
    Assert-VBoxManage
    $v = (& $Script:VBoxManage --version 2>$null).Trim()
    if (-not ($v -match '^(\d+)\.')) { throw "Could not parse VBox version: $v" }
    $major = [int]$Matches[1]
    if ($major -lt 7) {
        throw "VirtualBox 7+ required (found $v). Win11 unattended install + TPM 2.0 emulation need 7+."
    }
    Write-Info "VirtualBox version: $v"
}

function Test-HostRam {
    $totalGb = [Math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
    $needGb  = [Math]::Round($Script:VmRamMb / 1024, 1)
    if ($totalGb -lt ($needGb + 4)) {
        Write-WarnMsg "Host has $totalGb GB RAM; VM wants $needGb GB. Consider reducing VmRamMb in phantom-vm.ps1 or closing apps."
    }
}

function New-VmIfMissing {
    if (Test-VmExists $Script:VmName) {
        Write-Ok "VM '$Script:VmName' already exists."
        return
    }
    Write-Step "Creating VM '$Script:VmName' (disk under $Script:DisksDir)"
    if (-not (Test-Path $Script:DisksDir)) {
        New-Item -ItemType Directory -Force -Path $Script:DisksDir | Out-Null
    }

    # createvm registers the VM and points its machine folder at our .vm/disks/
    Invoke-VBox createvm `
        --name $Script:VmName `
        --basefolder $Script:DisksDir `
        --ostype Windows11_64 `
        --register | Out-Null

    # CPU + RAM + chipset/firmware/TPM/SecureBoot — all needed for Win11.
    Invoke-VBox modifyvm $Script:VmName `
        --cpus $Script:VmCpus `
        --memory $Script:VmRamMb `
        --vram 128 `
        --chipset ich9 `
        --firmware efi `
        --rtcuseutc on `
        --graphicscontroller vmsvga `
        --audio-driver none `
        --usb on --usbehci on `
        --nic1 bridged --nictype1 82540EM `
        --bridgeadapter1 (Get-DefaultBridgeAdapter) `
        --boot1 dvd --boot2 disk --boot3 none --boot4 none | Out-Null

    # Win11 prereqs: TPM 2.0 + Secure Boot (UEFI). VBox 7+ emulates these.
    Invoke-VBox modifyvm $Script:VmName --tpm-type 2.0 | Out-Null
    Invoke-VBox modifyvm $Script:VmName --secure-boot on | Out-Null

    # Disk: dynamic 80 GB VDI under .vm/disks/<vm>/<vm>.vdi
    $vdi = Join-Path $Script:DisksDir "$Script:VmName/$Script:VmName.vdi"
    if (-not (Test-Path $vdi)) {
        Invoke-VBox createmedium disk --filename $vdi --size $Script:VmDiskMb --format VDI | Out-Null
    }
    Invoke-VBox storagectl $Script:VmName --name 'SATA' --add sata --controller IntelAHCI --portcount 2 --bootable on | Out-Null
    Invoke-VBox storageattach $Script:VmName --storagectl SATA --port 0 --device 0 --type hdd --medium $vdi | Out-Null

    # DVD slot for the install ISO (attached during unattended install below).
    Invoke-VBox storagectl $Script:VmName --name 'IDE' --add ide --controller PIIX4 --bootable on | Out-Null

    Write-Ok "VM created."
}

function Get-DefaultBridgeAdapter {
    # Prefer the adapter that has a default route — that's the user's actual
    # LAN-facing NIC. Falls back to the first up/non-loopback adapter.
    try {
        $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
            Sort-Object -Property RouteMetric | Select-Object -First 1
        if ($route) {
            $alias = (Get-NetAdapter -InterfaceIndex $route.ifIndex).InterfaceDescription
            if ($alias) { return $alias }
        }
    } catch {}
    $up = Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | Select-Object -First 1
    if ($up) { return $up.InterfaceDescription }
    throw "No usable network adapter found for bridged networking."
}

function Invoke-UnattendedInstall {
    $iso = Get-IsoPath
    if (-not (Test-Path $iso)) { throw "ISO missing at $iso" }

    Write-Step "Configuring unattended Win11 install"
    # Pre-clear any prior unattended state (idempotent re-runs).
    & $Script:VBoxManage unattended detect --iso=$iso 2>&1 | Out-Null

    $bootstrapTpl = Join-Path $Script:TplDir 'bootstrap.ps1'
    if (-not (Test-Path $bootstrapTpl)) {
        throw "Bootstrap template missing: $bootstrapTpl"
    }

    # `unattended install` builds an answer-file ISO, mounts it alongside the
    # Win11 ISO, and configures first-boot-only auto-login so the post-install
    # script runs once. We disable additions install (stealth) and time-zone
    # to UTC for predictable scheduling.
    $args = @(
        'unattended', 'install', $Script:VmName,
        "--iso=$iso",
        "--user=$Script:VmUser",
        "--password=$Script:VmPassword",
        '--full-user-name=Phantom',
        '--country=US',
        '--time-zone=UTC',
        "--hostname=$($Script:VmName.ToLower()).local",
        '--install-additions=false',
        "--post-install-template=$bootstrapTpl",
        '--start-vm=headless'
    )
    Write-Info "VBoxManage $($args -join ' ')"
    & $Script:VBoxManage @args
    if ($LASTEXITCODE -ne 0) {
        throw "Unattended install kickoff failed. Inspect the VBox log under $Script:DisksDir\$Script:VmName\Logs\."
    }
    Write-Ok "Unattended install started. Windows setup runs ~25 min; first-login bootstrap fires automatically afterward."
}

# -- Public dispatcher -----------------------------------------------------

function Invoke-Provision {
    Write-Step "PhantomClick VM provision starting"
    Test-VBoxVersion
    Test-HostRam

    # 1. Artifacts (idempotent download)
    Invoke-Download

    # 2. Extension Pack into VBox
    Install-Extpack

    # 3. Create the VM if absent
    New-VmIfMissing

    # 4. Anti-fingerprint extradata
    Invoke-Stealth -VmName $Script:VmName

    # 5. USB filter for the Arduino
    Invoke-Usb -VmName $Script:VmName

    # 6. Kick off Windows install (no-op if already installed)
    $state = Get-VmState -Name $Script:VmName
    if ($state -eq 'running') {
        Write-WarnMsg "VM already running. Skipping unattended install. Use 'phantom-vm.ps1 status' to track."
    } else {
        Invoke-UnattendedInstall
    }

    Write-Host ""
    Write-Ok "Provision pipeline kicked off. Next steps:"
    Write-Host "  - Wait ~25 min for Windows install to complete (the VM reboots itself once)."
    Write-Host "  - Watch progress with:  .\phantom-vm.ps1 status"
    Write-Host "  - Once SSH is reachable, install RuneScape NXT and log in (one-time, manual)."
    Write-Host "  - Then snapshot:  .\phantom-vm.ps1 snapshot create clean-baseline"
    Write-Host ""
}
