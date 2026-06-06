# lib/stealth.ps1 — apply anti-fingerprint extradata to a VirtualBox VM.
#
# The defaults are chosen to look like a budget Dell OptiPlex desktop. Nothing
# here defeats a kernel-level anti-cheat; the goal is "no obvious VBox strings"
# so casual fingerprinting (BIOS DMI, MAC prefix, hypervisor CPUID bit) doesn't
# trip. Pafish is the right tool to grade results from inside the guest.
#
# All settings are idempotent — re-running on a VM that already has them set
# is a no-op (VBoxManage just rewrites the same values).

# Realistic DMI pose. Picked from Dell OptiPlex 7090 because that's a common
# small-business desktop with a believable BIOS revision history.
$Script:StealthDmi = @{
    BIOSVendor          = 'Dell Inc.'
    BIOSVersion         = '2.18.0'
    BIOSReleaseDate     = '04/12/2024'
    SystemVendor        = 'Dell Inc.'
    SystemProduct       = 'OptiPlex 7090'
    SystemVersion       = '01'
    SystemSerial        = ''   # randomized per-VM below
    SystemSKU           = '0A1B'
    SystemFamily        = 'OptiPlex'
    BoardVendor         = 'Dell Inc.'
    BoardProduct        = '0A1B2C'
    BoardVersion        = 'A00'
    BoardSerial         = ''   # randomized per-VM below
    ChassisVendor       = 'Dell Inc.'
    ChassisType         = '3'   # Desktop
    ChassisVersion      = 'Rev 1.0'
    ChassisSerial       = ''
    OEMVendor           = 'Dell Inc.'
}

function New-RandomSerial {
    param([int]$Length = 7)
    -join ((48..57) + (65..90) | Get-Random -Count $Length | ForEach-Object { [char]$_ })
}

function New-RandomMac {
    # Realistic OUI: pick from a small pool of consumer-network-card prefixes
    # so the MAC doesn't shout "VirtualBox" (08:00:27 prefix is the giveaway).
    $ouis = @('001A2B', '00224D', '60E327', 'A4C361', 'D89EF3', 'F4D108')
    $oui = $ouis | Get-Random
    $tail = -join (1..3 | ForEach-Object { '{0:X2}' -f (Get-Random -Minimum 0 -Maximum 256) })
    return "$oui$tail"
}

function Set-VBoxExtraData {
    param(
        [string]$VmName,
        [string]$Key,
        [string]$Value
    )
    Invoke-VBox setextradata $VmName $Key $Value | Out-Null
}

function Invoke-Stealth {
    param([string]$VmName = $Script:VmName)

    if (-not (Test-VmExists $VmName)) {
        throw "VM '$VmName' does not exist. Run 'phantom-vm.ps1 provision' first."
    }

    Write-Step "Applying stealth profile to '$VmName'"

    # Randomized serials — distinct per machine so two PhantomBox installs
    # don't look identical to anyone aggregating fingerprints.
    $sysSerial    = New-RandomSerial 7
    $boardSerial  = New-RandomSerial 7
    $chassisSerial = New-RandomSerial 7
    $dmi = $Script:StealthDmi.Clone()
    $dmi.SystemSerial  = $sysSerial
    $dmi.BoardSerial   = $boardSerial
    $dmi.ChassisSerial = $chassisSerial

    # DMI strings live under VBoxInternal/Devices/pcbios/0/Config/Dmi*.
    Write-Info "DMI strings: $($dmi.SystemVendor) $($dmi.SystemProduct)"
    foreach ($pair in $dmi.GetEnumerator()) {
        if (-not $pair.Value) { continue }
        $key = "VBoxInternal/Devices/pcbios/0/Config/Dmi$($pair.Key)"
        Set-VBoxExtraData -VmName $VmName -Key $key -Value $pair.Value
    }

    # Disk model strings — without this, anti-cheat reads "VBOX HARDDISK" off SATA.
    Write-Info "Disk model -> ST500DM002-1BD142 (Seagate Barracuda)"
    Set-VBoxExtraData -VmName $VmName -Key 'VBoxInternal/Devices/ahci/0/Config/Port0/ModelNumber' -Value 'ST500DM002-1BD142'
    Set-VBoxExtraData -VmName $VmName -Key 'VBoxInternal/Devices/ahci/0/Config/Port0/FirmwareRevision' -Value 'KC45'
    Set-VBoxExtraData -VmName $VmName -Key 'VBoxInternal/Devices/ahci/0/Config/Port0/SerialNumber' -Value (New-RandomSerial 12)

    # Hide hypervisor CPUID bit (CPUID leaf 1, ECX bit 31). Without this, any
    # `cpuid` query that checks bit 31 of leaf 1.ECX immediately reveals
    # virtualization. We mask leaf 1.ECX and 80000001.ECX both.
    Write-Info "Hiding hypervisor CPUID bit"
    Invoke-VBox modifyvm $VmName --paravirtprovider none | Out-Null
    Set-VBoxExtraData -VmName $VmName -Key 'VBoxInternal/CPUM/HostCPUID/1/eax' -Value '000906EA'
    Set-VBoxExtraData -VmName $VmName -Key 'VBoxInternal/CPUM/HostCPUID/1/ebx' -Value '00100800'
    Set-VBoxExtraData -VmName $VmName -Key 'VBoxInternal/CPUM/HostCPUID/1/ecx' -Value '7FFAFBFF'
    Set-VBoxExtraData -VmName $VmName -Key 'VBoxInternal/CPUM/HostCPUID/1/edx' -Value 'BFEBFBFF'

    # Realistic MAC (NIC 1). VBox default 08:00:27:* is well-known — replace.
    $mac = New-RandomMac
    Write-Info "MAC -> $mac"
    Invoke-VBox modifyvm $VmName --macaddress1 $mac | Out-Null

    # Cosmetic VM-name hint that some malware/RAT scanners use. Cleared.
    Set-VBoxExtraData -VmName $VmName -Key 'VBoxInternal/Devices/pcbios/0/Config/DmiOEMVBoxVer' -Value 'string:'
    Set-VBoxExtraData -VmName $VmName -Key 'VBoxInternal/Devices/pcbios/0/Config/DmiOEMVBoxRev' -Value 'string:'

    Write-Ok "Stealth profile applied. Run Pafish inside the guest to grade results."
}
