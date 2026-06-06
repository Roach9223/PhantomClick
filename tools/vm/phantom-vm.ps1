<#
.SYNOPSIS
  PhantomClick VM control plane — single entry point for VirtualBox automation.

.DESCRIPTION
  Provisions, controls, and updates a sandboxed Windows VM that runs PhantomClick
  + RuneScape with Arduino HID passthrough. All artifacts (ISO, Extension Pack,
  VM disk) live under .vm/ at the project root so the entire bot environment is
  self-contained.

.EXAMPLE
  .\phantom-vm.ps1 provision
  .\phantom-vm.ps1 start
  .\phantom-vm.ps1 sync
  .\phantom-vm.ps1 status
  .\phantom-vm.ps1 snapshot create clean-baseline

.NOTES
  Runs on PowerShell 5.1+ (built into Win10/11) and PowerShell 7+. Requires
  VirtualBox 7+ installed on the host (manual one-time install). The Extension
  Pack is downloaded automatically into .vm/extpack/ during provision.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = 'help',

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# -- Paths -------------------------------------------------------------------
# Resolve once and stash on script scope so lib/* functions inherit them.
$Script:ToolsDir   = Split-Path -Parent $PSCommandPath
$Script:ProjectDir = (Resolve-Path (Join-Path $ToolsDir '..\..')).Path
$Script:LibDir     = Join-Path $ToolsDir 'lib'
$Script:TplDir     = Join-Path $ToolsDir 'templates'
$Script:VmRoot     = Join-Path $ProjectDir '.vm'
$Script:IsoDir     = Join-Path $VmRoot 'iso'
$Script:ExtpackDir = Join-Path $VmRoot 'extpack'
$Script:DisksDir   = Join-Path $VmRoot 'disks'

# -- VM identity (override via env if you ever run multiple VMs) -------------
$Script:VmName     = if ($env:PHANTOM_VM_NAME) { $env:PHANTOM_VM_NAME } else { 'PhantomBox' }
$Script:VmUser     = 'phantom'
$Script:VmPassword = 'phantom'   # local-only credentials, VM has no inbound from outside LAN
$Script:VmCpus     = 4
$Script:VmRamMb    = 6144
$Script:VmDiskMb   = 81920
$Script:VmSshPort  = 22

# -- VBoxManage discovery ----------------------------------------------------
# Resolved lazily. `help` and `download` (with manual ISO drop) work without
# VBox; everything else calls Assert-VBoxManage which throws a clear error.
function Get-VBoxManagePath {
    $candidates = @(
        "$env:ProgramFiles\Oracle\VirtualBox\VBoxManage.exe",
        "${env:ProgramFiles(x86)}\Oracle\VirtualBox\VBoxManage.exe"
    )
    foreach ($p in $candidates) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    $found = Get-Command VBoxManage.exe -ErrorAction SilentlyContinue
    if ($found) { return $found.Path }
    return $null
}

$Script:VBoxManage = Get-VBoxManagePath

function Assert-VBoxManage {
    if (-not $Script:VBoxManage) {
        throw "VBoxManage.exe not found. Install VirtualBox 7+ from https://www.virtualbox.org/wiki/Downloads and re-run."
    }
}

# -- Logging helpers ---------------------------------------------------------
function Write-Step    ([string]$Msg) { Write-Host "==> $Msg" -ForegroundColor Cyan }
function Write-Info    ([string]$Msg) { Write-Host "  - $Msg" -ForegroundColor Gray }
function Write-Ok      ([string]$Msg) { Write-Host "  + $Msg" -ForegroundColor Green }
function Write-WarnMsg ([string]$Msg) { Write-Host "  ! $Msg" -ForegroundColor Yellow }
function Write-ErrMsg  ([string]$Msg) { Write-Host "  x $Msg" -ForegroundColor Red }

# -- VBoxManage wrapper ------------------------------------------------------
# Runs VBoxManage and returns stdout. Throws with stderr on non-zero exit so
# the caller doesn't silently miss failures.
function Invoke-VBox {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    Assert-VBoxManage
    $out = & $Script:VBoxManage @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        $msg = ($out | Out-String).Trim()
        throw "VBoxManage $($Arguments -join ' ') failed (exit $LASTEXITCODE):`n$msg"
    }
    return $out
}

function Test-VmExists {
    param([string]$Name = $Script:VmName)
    Assert-VBoxManage
    $list = & $Script:VBoxManage list vms 2>$null
    return ($list | Select-String -Pattern "`"$([regex]::Escape($Name))`"" -Quiet)
}

function Get-VmState {
    param([string]$Name = $Script:VmName)
    Assert-VBoxManage
    if (-not (Test-VmExists $Name)) { return 'absent' }
    $info = & $Script:VBoxManage showvminfo $Name --machinereadable 2>$null
    foreach ($line in $info) {
        if ($line -match '^VMState="([^"]+)"') { return $Matches[1] }
    }
    return 'unknown'
}

# -- Dot-source lib/* --------------------------------------------------------
# Each lib script defines one or more Invoke-* functions. They share script
# scope (so $Script:VBoxManage etc. are visible) without reaching for module
# semantics — keeps the surface area tiny and discoverable.
foreach ($lib in @('download', 'stealth', 'usb', 'control', 'sync', 'provision')) {
    $path = Join-Path $LibDir "$lib.ps1"
    if (Test-Path $path) { . $path }
    else { Write-WarnMsg "Missing lib: $path (subcommand may fail)" }
}

# -- Help text ---------------------------------------------------------------
function Show-Help {
    @"
PhantomClick VM control plane

USAGE:
  .\phantom-vm.ps1 <command> [args...]

COMMANDS:
  provision                One-shot: download Win11 ISO + extpack, create VM,
                           apply stealth, register Arduino USB filter, boot for
                           Windows install. ~30 min total. Idempotent.
  start                    Power on the VM (headless by default; pass --gui for
                           a window).
  stop                     Graceful shutdown via ACPI. Use 'stop --force' for
                           hard power-off.
  status                   VM state, IP, bot state, last sync time.
  sync                     Push host repo to VM via SCP, restart the bot task.
  restart-bot              Restart the PhantomClick task only (no VM reboot).
  snapshot create <name>   Take a snapshot.
  snapshot revert <name>   Revert to a snapshot. VM must be powered off.
  snapshot list            List snapshots for the VM.
  stealth-recheck          Re-apply anti-fingerprint extradata (idempotent).
  com-port                 Query VM via SSH, print Arduino's COM port.
  monitor-url              Print the Monitor-tab URL pointing at VM's LAN IP.
  download                 Just download the ISO + extpack into .vm/, no VM ops.
  help                     This message.

ENV:
  PHANTOM_VM_NAME          Override the VM name (default: PhantomBox).

PATHS:
  ProjectDir : $ProjectDir
  VmRoot     : $VmRoot
  VBoxManage : $($Script:VBoxManage)
"@
}

# -- Dispatch ----------------------------------------------------------------
try {
    switch -Regex ($Command) {
        '^(help|--help|-h|/\?)$' { Show-Help; break }

        '^download$'        { Invoke-Download; break }
        '^provision$'       { Invoke-Provision @Args; break }
        '^start$'           { Invoke-Start @Args; break }
        '^stop$'            { Invoke-Stop @Args; break }
        '^status$'          { Invoke-Status @Args; break }
        '^sync$'            { Invoke-Sync @Args; break }
        '^restart-bot$'     { Invoke-RestartBot @Args; break }
        '^snapshot$'        { Invoke-Snapshot @Args; break }
        '^stealth-recheck$' { Invoke-Stealth -VmName $Script:VmName; break }
        '^com-port$'        { Invoke-ComPort @Args; break }
        '^monitor-url$'     { Invoke-MonitorUrl @Args; break }
        default {
            Write-ErrMsg "Unknown command: $Command"
            Show-Help
            exit 2
        }
    }
}
catch {
    Write-ErrMsg $_.Exception.Message
    if ($env:PHANTOM_VM_DEBUG) { Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
    exit 1
}
