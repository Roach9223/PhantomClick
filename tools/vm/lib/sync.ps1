# lib/sync.ps1 — push the host's PhantomClick repo into the guest VM via SCP.
#
# Strategy: use scp + tar. We tar up the project on the host (excluding heavy/
# transient dirs like .vm, .venv, __pycache__, *.log), pipe it through ssh
# into a tar -x running inside the guest. This is dramatically faster than
# scp'ing each file separately and avoids the per-file SSH handshake cost.
#
# After the transfer, we restart the bot task so it picks up the changes.

$Script:SyncExcludePatterns = @(
    '.vm/*',
    '.git/*',
    '.venv/*',
    '__pycache__/*',
    '*/__pycache__/*',
    '*.pyc',
    '*.log',
    'phantomclick.log*',
    'templates/*.png'   # don't push captured templates — guest manages its own
)

function Resolve-TarBinary {
    # Windows 10 1803+ ships bsdtar.exe at C:\Windows\System32\tar.exe. We
    # also accept tar from PATH (Git Bash, MSYS2, WSL).
    $sysTar = "$env:SystemRoot\System32\tar.exe"
    if (Test-Path $sysTar) { return $sysTar }
    $cmd = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Path }
    throw "tar.exe not found. Win10 1803+ ships one at System32; older systems need Git Bash or WSL."
}

function Invoke-Sync {
    param(
        [string]$VmName = $Script:VmName,
        [string]$User   = $Script:VmUser
    )
    $state = Get-VmState -Name $VmName
    if ($state -ne 'running') { throw "VM is not running (state=$state). Start it first." }

    $ip = Get-VmIpAddress -VmName $VmName
    if (-not $ip) {
        throw "VM IP unknown. Confirm the VM has booted and SSH is reachable."
    }

    $tar = Resolve-TarBinary
    Write-Step "Syncing $Script:ProjectDir -> ${User}@${ip}:C:\PhantomClick"

    # Build tar exclude args.
    $excludeArgs = @()
    foreach ($p in $Script:SyncExcludePatterns) { $excludeArgs += @('--exclude', $p) }

    # Stream tar through SSH. We cd into the project dir so tar sees relative paths.
    Push-Location $Script:ProjectDir
    try {
        # The remote command:
        #   - mkdir target
        #   - extract incoming tar into the target (overwrite)
        $remote = "powershell -NoProfile -Command `"if (-not (Test-Path C:\PhantomClick)) { New-Item -ItemType Directory -Path C:\PhantomClick | Out-Null }; tar -xf - -C C:\PhantomClick`""

        # tar output → ssh stdin → remote tar -x.
        $tarArgs = @('-c') + $excludeArgs + @('-f', '-', '.')
        $sshArgs = @(
            '-o', 'StrictHostKeyChecking=accept-new',
            '-p', $Script:VmSshPort,
            "$User@$ip",
            $remote
        )

        # PowerShell's parser reserves '<' so we can't do `& ssh ... < file`.
        # Build a tar archive on disk, then ask cmd.exe to do the redirect —
        # cmd is happy with the operator and we don't need a streaming pipeline
        # between two native processes from PS.
        $tarFile = Join-Path $env:TEMP 'phantom-sync.tar'
        $tarProc = Start-Process -FilePath $tar -ArgumentList $tarArgs `
            -RedirectStandardOutput $tarFile -NoNewWindow -Wait -PassThru
        if ($tarProc.ExitCode -ne 0) { throw "tar failed (exit $($tarProc.ExitCode))" }

        Write-Info "Tar archive built; uploading via ssh..."
        # Pass the ssh arg list through cmd's redirection. We quote the path so
        # spaces in TEMP work; ssh args are pre-quoted by joining.
        $sshCmd = ('ssh "{0}"' -f ($sshArgs -join '" "'))
        & cmd.exe /c "$sshCmd < `"$tarFile`""
        $sshExit = $LASTEXITCODE
        Remove-Item $tarFile -Force -ErrorAction SilentlyContinue
        if ($sshExit -ne 0) { throw "ssh-tar transfer failed (exit $sshExit)" }
    }
    finally {
        Pop-Location
    }

    Write-Ok "Source synced."

    # Restart the bot task so the new code is picked up.
    try {
        Invoke-RestartBot
    } catch {
        Write-WarnMsg "Sync succeeded but bot restart failed: $($_.Exception.Message)"
        Write-WarnMsg "Run 'phantom-vm.ps1 restart-bot' once the task exists."
    }
}
