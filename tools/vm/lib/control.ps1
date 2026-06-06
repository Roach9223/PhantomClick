# lib/control.ps1 — start, stop, status, snapshot, com-port, monitor-url.
#
# Thin wrappers around VBoxManage + occasional SSH calls into the guest. Each
# function corresponds to one phantom-vm.ps1 subcommand.

# -- Helpers ---------------------------------------------------------------

function Get-VmGuestProperty {
    param([string]$VmName, [string]$Key)
    $out = & $Script:VBoxManage guestproperty get $VmName $Key 2>$null
    if ($out -match 'Value:\s*(.+)$') { return $Matches[1].Trim() }
    return $null
}

function Get-VmIpAddress {
    param([string]$VmName = $Script:VmName)
    # Guest Additions writes /VirtualBox/GuestInfo/Net/0/V4/IP. If Additions
    # aren't installed (we skip them for stealth), this returns nothing — and
    # we fall back to ARP-scanning the bridged-adapter MAC, but that's slow
    # and out-of-scope for v1. Recommend the user check their router DHCP
    # table or run `ipconfig` inside the VM via SSH once they know the IP.
    $ip = Get-VmGuestProperty -VmName $VmName -Key '/VirtualBox/GuestInfo/Net/0/V4/IP'
    if ($ip) { return $ip }
    return $null
}

function Invoke-SshGuest {
    <#
    Run a command inside the guest VM via SSH. Requires the guest's OpenSSH
    server to be running (bootstrap.ps1 enables it) and the user to have
    accepted the host key once. Returns stdout; throws on non-zero exit.
    #>
    param(
        [Parameter(Mandatory)][string]$Command,
        [string]$VmName = $Script:VmName,
        [string]$User   = $Script:VmUser,
        [int]$Port      = $Script:VmSshPort,
        [int]$TimeoutSec = 20
    )
    $ip = Get-VmIpAddress -VmName $VmName
    if (-not $ip) {
        throw "Could not determine VM IP. Ensure the VM is booted and the SSH server is up."
    }
    $sshArgs = @(
        '-o', 'StrictHostKeyChecking=accept-new',
        '-o', "ConnectTimeout=$TimeoutSec",
        '-p', $Port,
        "$User@$ip",
        $Command
    )
    $out = & ssh @sshArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "SSH command failed (exit $LASTEXITCODE):`n$($out | Out-String)"
    }
    return $out
}

# -- start / stop ----------------------------------------------------------

function Invoke-Start {
    param([string]$VmName = $Script:VmName)
    $headless = $true
    if ($Args -contains '--gui') { $headless = $false }
    $state = Get-VmState -Name $VmName
    if ($state -eq 'running') { Write-Ok "VM is already running."; return }
    if ($state -eq 'absent')  { throw "VM '$VmName' does not exist. Run provision first." }
    Write-Step "Starting '$VmName' (type=$(if ($headless) { 'headless' } else { 'gui' }))"
    $type = if ($headless) { 'headless' } else { 'gui' }
    Invoke-VBox startvm $VmName --type $type | Out-Null
    Write-Ok "VM started."
}

function Invoke-Stop {
    param([string]$VmName = $Script:VmName)
    $force = $false
    if ($Args -contains '--force') { $force = $true }
    $state = Get-VmState -Name $VmName
    if ($state -ne 'running') { Write-Ok "VM is not running (state=$state)."; return }
    if ($force) {
        Write-Step "Hard-power-off '$VmName'"
        Invoke-VBox controlvm $VmName poweroff | Out-Null
    } else {
        Write-Step "Sending ACPI shutdown to '$VmName'"
        Invoke-VBox controlvm $VmName acpipowerbutton | Out-Null
    }
    Write-Ok "Stop signal sent."
}

# -- status ----------------------------------------------------------------

function Invoke-Status {
    param([string]$VmName = $Script:VmName)
    $state = Get-VmState -Name $VmName
    Write-Host "VM:        $VmName" -ForegroundColor Cyan
    Write-Host "State:     $state"
    if ($state -eq 'absent') { return }
    $ip = Get-VmIpAddress -VmName $VmName
    Write-Host ("IP:        {0}" -f ($(if ($ip) { $ip } else { '(unknown — Guest Additions skipped; check router DHCP)' })))
    if ($state -eq 'running' -and $ip) {
        try {
            $bot = Invoke-SshGuest -Command 'powershell -NoProfile -Command "(Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like ''*main.py*'' } | Measure-Object).Count"'
            Write-Host "Bot procs: $($bot -join '')"
        } catch {
            Write-Host "Bot procs: (SSH unavailable: $($_.Exception.Message.Split([Environment]::NewLine)[0]))"
        }
    }
}

# -- snapshot --------------------------------------------------------------

function Invoke-Snapshot {
    param([string]$VmName = $Script:VmName)
    $sub = if ($Args.Length -gt 0) { $Args[0] } else { 'list' }
    $name = if ($Args.Length -gt 1) { $Args[1] } else { '' }
    switch ($sub) {
        'list' {
            & $Script:VBoxManage snapshot $VmName list --machinereadable 2>$null
            return
        }
        'create' {
            if (-not $name) { throw "snapshot create requires a name." }
            Write-Step "Creating snapshot '$name'"
            Invoke-VBox snapshot $VmName take $name | Out-Null
            Write-Ok "Snapshot '$name' created."
        }
        'revert' {
            if (-not $name) { throw "snapshot revert requires a name." }
            $state = Get-VmState -Name $VmName
            if ($state -eq 'running') { throw "VM must be powered off before revert. Run 'phantom-vm.ps1 stop --force' first." }
            Write-Step "Reverting to snapshot '$name'"
            Invoke-VBox snapshot $VmName restore $name | Out-Null
            Write-Ok "Reverted."
        }
        default { throw "Unknown snapshot sub-command: $sub (use list|create|revert)" }
    }
}

# -- com-port --------------------------------------------------------------

function Invoke-ComPort {
    Write-Step "Querying VM for Arduino COM port"
    $cmd = 'python -c "import serial.tools.list_ports as p; print('';''.join(x.device for x in p.comports() if (x.vid==0x2341)))"'
    try {
        $out = (Invoke-SshGuest -Command $cmd).Trim()
        if (-not $out) {
            Write-WarnMsg "No Arduino device visible inside the VM. Plug it in and check VBox Devices > USB."
            return
        }
        Write-Ok "Arduino COM(s): $out"
    } catch {
        Write-ErrMsg "Couldn't query the VM. Is it running and SSH-reachable?"
        throw
    }
}

# -- monitor-url -----------------------------------------------------------

function Invoke-MonitorUrl {
    $ip = Get-VmIpAddress
    if (-not $ip) {
        Write-WarnMsg "VM IP unknown. Boot the VM, then re-run this. (Or check your router's DHCP leases.)"
        return
    }
    # Read the Monitor token from the guest's config.json so we surface a
    # ready-to-paste URL.
    try {
        $token = (Invoke-SshGuest -Command 'powershell -NoProfile -Command "(Get-Content C:\PhantomClick\config.json -Raw | ConvertFrom-Json).monitor_token"').Trim()
    } catch {
        $token = ''
    }
    $port = 8765
    $suffix = if ($token) { "/?token=$token" } else { '/' }
    Write-Host ""
    Write-Host "Monitor URL (open on your phone, same Wi-Fi):" -ForegroundColor Cyan
    Write-Host "  http://${ip}:${port}${suffix}" -ForegroundColor Green
    Write-Host ""
}

# -- restart-bot -----------------------------------------------------------

function Invoke-RestartBot {
    Write-Step "Restarting PhantomClick task inside VM"
    # The bootstrap creates a Scheduled Task named 'PhantomClickBot' that runs
    # python main.py at user login. End-Task + Start-Task cycles it without
    # rebooting the VM.
    Invoke-SshGuest -Command 'schtasks /End /TN PhantomClickBot 2>nul & timeout /t 1 >nul & schtasks /Run /TN PhantomClickBot' | Out-Null
    Write-Ok "Bot task restarted."
}
