# lib/usb.ps1 — register a USB device filter so the Arduino auto-attaches to
# the VM the moment it's plugged into the host.
#
# Without a filter, you'd have to manually pick the device from VBox's
# Devices > USB menu every time. With it, plug-in == passthrough.
#
# Default targets the Leonardo PhantomHID firmware (VID=0x2341, PID=0x8036).
# Different boards / clones may need different IDs — see lspci/Device Manager
# on the host. The filter name doubles as an idempotency key so re-running
# this doesn't pile up duplicate filters.

$Script:UsbDefaults = @{
    FilterName    = 'PhantomHID'
    VendorId      = '2341'    # Arduino LLC
    ProductId     = '8036'    # Leonardo
}

function Get-UsbFilters {
    param([string]$VmName = $Script:VmName)
    $info = & $Script:VBoxManage showvminfo $VmName --machinereadable 2>$null
    $names = @()
    foreach ($line in $info) {
        if ($line -match '^USBFilterName\d+="([^"]+)"') { $names += $Matches[1] }
    }
    return $names
}

function Test-UsbFilterExists {
    param([string]$VmName, [string]$FilterName)
    return (Get-UsbFilters -VmName $VmName) -contains $FilterName
}

function Invoke-EnsureUsbController {
    param([string]$VmName = $Script:VmName)
    # USB 2.0 (EHCI) is enough for the Leonardo at full-speed and is the
    # baseline EHCI controller the Extension Pack provides. We avoid xHCI/3.0
    # because the Leonardo enumerates as 1.1/2.0 and xHCI sometimes adds
    # spurious detection latency.
    Invoke-VBox modifyvm $VmName --usb on --usbehci on | Out-Null
}

function Invoke-Usb {
    param(
        [string]$VmName     = $Script:VmName,
        [string]$FilterName = $Script:UsbDefaults.FilterName,
        [string]$VendorId   = $Script:UsbDefaults.VendorId,
        [string]$ProductId  = $Script:UsbDefaults.ProductId
    )

    if (-not (Test-VmExists $VmName)) {
        throw "VM '$VmName' does not exist. Run 'phantom-vm.ps1 provision' first."
    }

    Write-Step "Registering USB filter '$FilterName' (VID=$VendorId PID=$ProductId)"
    Invoke-EnsureUsbController -VmName $VmName

    if (Test-UsbFilterExists -VmName $VmName -FilterName $FilterName) {
        Write-Ok "Filter already exists; leaving as-is."
        return
    }

    & $Script:VBoxManage usbfilter add 0 `
        --target $VmName `
        --name $FilterName `
        --vendorid $VendorId `
        --productid $ProductId | Out-Null

    if ($LASTEXITCODE -ne 0) {
        throw "VBoxManage usbfilter add failed (exit $LASTEXITCODE)."
    }
    Write-Ok "USB filter registered. Plugging in the Arduino now will auto-attach it to the VM."
}
