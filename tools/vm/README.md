# PhantomClick VM (PhantomBox)

PowerShell-driven local VirtualBox sandbox that runs PhantomClick + RuneScape in isolation from your work environment, with Arduino HID passthrough preserved and remote control + monitoring via the Monitor tab.

All artifacts (Win11 ISO, Extension Pack, VM disk, snapshots) live under `.vm/` at the project root — the entire bot environment is one folder.

## Prerequisites

- **Windows 10/11 host** with PowerShell 5.1+ (built in)
- **VirtualBox 7.0+** installed manually: <https://www.virtualbox.org/wiki/Downloads>
- **16 GB+ host RAM** (6 GB goes to the VM, you keep the rest)
- **80 GB+ free disk** on whichever drive holds this project
- **A local LAN with DHCP** (the VM uses a bridged adapter — no special router config)
- **Arduino Leonardo flashed with PhantomHID** (see `firmware/phantomhid/README.md`) — flash it on the host before starting the VM
- **OpenSSH client** (Win10 1809+ ships it; otherwise install via `Add-WindowsCapability`)

### Hyper-V conflict (read this first)

If Hyper-V is currently enabled on your host (you use WSL2, Docker Desktop, or Windows Sandbox), VirtualBox falls back to Microsoft's WHP hypervisor — usable but slower. Three options:

- **Disable Hyper-V** (fastest VM): `bcdedit /set hypervisorlaunchtype off`, reboot. WSL2/Docker stop working until you flip it back.
- **Accept the slowdown.** RS NXT still runs; expect ~10–20 % less CPU efficiency in the guest.
- **Switch to Hyper-V variant** (out of scope for this version — ask if VBox detection becomes a problem).

## Quick start

```powershell
cd F:\.programs\AutoClicker\tools\vm
.\phantom-vm.ps1 provision
```

`provision` is one-shot and idempotent. It:

1. Downloads the Win11 ISO and VBox Extension Pack into `.vm/` if missing
2. Installs the Extension Pack (admin elevation prompt)
3. Creates the VM with stealth fingerprint settings, TPM 2.0, Secure Boot, UEFI
4. Registers a USB filter for the Arduino (auto-attaches when plugged in)
5. Kicks off the unattended Win11 install and runs `bootstrap.ps1` at first login

Total time: ~30 minutes (mostly Windows install). Watch progress with `phantom-vm.ps1 status`.

After Windows finishes, the bootstrap inside the VM:

- Installs Python 3.12 + Git + OpenSSH server
- Configures the firewall to allow inbound SSH
- Registers a Scheduled Task that auto-starts PhantomClick at user login
- Detects the Arduino COM port (if plugged in already) and writes it to `config.json`

## Daily commands

```powershell
.\phantom-vm.ps1 start                    # boot the VM (headless by default; --gui for a window)
.\phantom-vm.ps1 status                   # state + IP + bot-process count
.\phantom-vm.ps1 sync                     # push host repo to VM, restart bot
.\phantom-vm.ps1 restart-bot              # restart the bot only (no VM reboot)
.\phantom-vm.ps1 com-port                 # what COM did the Arduino get?
.\phantom-vm.ps1 monitor-url              # ready-to-paste Monitor URL for your phone
.\phantom-vm.ps1 stop                     # graceful ACPI shutdown
.\phantom-vm.ps1 stop --force             # hard power off
```

## Snapshots

```powershell
.\phantom-vm.ps1 snapshot create clean-baseline  # take after first install
.\phantom-vm.ps1 snapshot list
.\phantom-vm.ps1 stop --force
.\phantom-vm.ps1 snapshot revert clean-baseline
```

Take the baseline snapshot **after** you've installed RuneScape NXT and logged in once. From there, anything you break — broken update, weird bot state, accidentally bricked Windows — is one revert away.

## Pushing code changes from host to VM

```powershell
# Edit code on host as usual, then:
.\phantom-vm.ps1 sync
```

`sync` tars your project (excluding `.vm/`, `.git/`, `__pycache__`, logs) and pipes it through SSH into `C:\PhantomClick\` on the guest, then restarts the bot via the Task Scheduler entry. Typical sync takes a few seconds.

## Anti-detection notes

What the provision applies automatically (`stealth.ps1`):

- DMI BIOS / system / board / chassis strings → realistic Dell OptiPlex
- Disk model → Seagate Barracuda (no `VBOX HARDDISK`)
- Hypervisor CPUID bit hidden (cpuid leaf 1.ECX bit 31 cleared)
- Random MAC outside the well-known VBox `08:00:27:` prefix
- Guest Additions skipped (the additions service is a giveaway)
- Paravirtualization provider disabled

What it can't do:

- The VBox kernel driver is detectable to anti-cheat that enumerates loaded drivers. NXT does not currently do this aggressively.
- Some ACPI strings persist regardless.
- A determined anti-cheat can fingerprint VBox at the hypervisor level via SLAT timing differences.
- **Behavior is the bigger detection vector.** PhantomClick's humanization (Bezier paths, log-normal timing, fatigue, distraction spikes, post-click drift) is the real defense. VM stealth is incremental.

Run [Pafish](https://github.com/a0rtega/pafish) inside the VM after provision to see what fingerprints leak. Goal isn't zero detections — it's "no obvious ones."

## Troubleshooting

**"VBoxManage.exe not found"** — Install VirtualBox 7+ first. The script checks `Program Files\Oracle\VirtualBox\` and PATH.

**"VirtualBox 7+ required"** — Upgrade VBox. v6 lacks TPM emulation and unattended Win11 support.

**"Could not parse VBoxManage --version"** — VBox is installed but `VBoxManage --version` returns something unexpected. Open a shell, run it manually, paste the output.

**Win11 ISO download fails (Fido)** — Microsoft sometimes changes their session-token flow and Fido needs an update. Manually download the ISO from <https://www.microsoft.com/software-download/windows11>, place it at `.vm/iso/Win11_x64.iso`, re-run `provision`.

**Extension Pack version mismatch** — `download.ps1` pins to your installed VBox version. If you upgrade VBox, run `phantom-vm.ps1 download` to grab the matching extpack, then re-install.

**VM boots to "no bootable medium" after install** — Windows installer didn't lay down a UEFI partition. Wipe and re-provision: `phantom-vm.ps1 stop --force; VBoxManage unregistervm PhantomBox --delete; .\phantom-vm.ps1 provision`.

**Arduino not detected inside VM** — Three things to check:
1. USB filter exists: `VBoxManage list usbfilters` should show `PhantomHID`.
2. Arduino is enumerated on the host: Device Manager → Ports (COM & LPT) shows `Arduino Leonardo (COMx)`.
3. VBox Extension Pack is installed: `VBoxManage list extpacks` includes `Oracle VM VirtualBox Extension Pack`.

**SSH says "could not resolve hostname" / "Connection refused"** — VM hasn't finished bootstrap yet (sshd installs ~5 min into bootstrap). Wait, then retry. `phantom-vm.ps1 status` reports the IP once it's reachable.

**`phantom-vm.ps1 status` shows IP `(unknown)`** — Guest Additions are intentionally skipped for stealth, so VBox doesn't know the IP. Either (a) check your router's DHCP leases for `phantombox.local`, or (b) inside the VM (via VBox console window) run `ipconfig` and note the IPv4 address. We can add a smarter detection later if needed.

**RuneScape NXT won't launch in the VM** — Make sure the VBox graphics controller is `vmsvga` (provision sets this). NXT needs DX11; vmsvga supports it. If it still fails, check for "hardware acceleration disabled" in NXT settings.

**"Unattended install kickoff failed"** — `VBoxManage unattended` is sensitive to the exact Win11 ISO build. Two options:
1. Run the ISO interactively: `VBoxManage modifyvm PhantomBox --boot1 dvd; VBoxManage storageattach PhantomBox --storagectl IDE --port 0 --device 0 --type dvddrive --medium .vm/iso/Win11_x64.iso; VBoxManage startvm PhantomBox --type gui` and click through the installer manually.
2. Use the fallback `templates/autounattend.xml` — see comments at the top of that file.

## File map

```
tools/vm/
├── README.md                  ← you are here
├── phantom-vm.ps1             single user-facing entry point
├── lib/
│   ├── download.ps1           ISO + Extension Pack download cache
│   ├── provision.ps1          one-shot setup orchestrator
│   ├── stealth.ps1            anti-fingerprint extradata
│   ├── usb.ps1                Arduino USB filter
│   ├── control.ps1            start/stop/snapshot/status/com-port/monitor-url
│   └── sync.ps1               SCP-based push from host to VM
└── templates/
    ├── autounattend.xml       fallback unattended answer file
    └── bootstrap.ps1          guest-side first-boot installer

.vm/                           ← downloaded artifacts + VM state (gitignored)
├── .gitignore
├── iso/Win11_x64.iso
├── extpack/Oracle_VM_VirtualBox_Extension_Pack-<ver>.vbox-extpack
├── disks/PhantomBox/
│   ├── PhantomBox.vbox
│   └── PhantomBox.vdi
└── snapshots/
```
