<#
.SYNOPSIS
    Obsidian OS - strict QEMU boot test, for a Windows build host.

.DESCRIPTION
    Windows counterpart to tests/boottest.sh. It exists because the reference
    development host has no Linux qemu and no WSL2 (the Virtual Machine Platform
    feature is unavailable), and booting the ISO was otherwise untestable
    locally. Only QEMU is needed - the ISO is built in WSL1 and copied across.

    It deliberately shares tests/boot-markers.conf with boottest.sh instead of
    restating the markers. Two copies of the pass criteria is how a gate ends up
    green on the developer's machine and red in CI, or worse, the reverse.

    There is no soft mode. A soft mode was how the previous test passed on a
    completely broken image: it fell back to matching 'login:' and
    'Reached target', which a stock Debian live ISO prints too.

.PARAMETER Iso
    Path to the ISO to test.

.PARAMETER Timeout
    Seconds to wait for OBSIDIAN-OS-READY. Default 900. TCG emulation of a
    cold boot on a laptop-class CPU is slow; the timeout is generous on purpose
    and a slow pass is still a pass.

.PARAMETER Flavor
    If given, the serial log must contain "flavor=<Flavor>". Catches testing
    yesterday's image.

.PARAMETER Qemu
    Path to qemu-system-x86_64.exe. Defaults to the standard install location.

.PARAMETER Accel
    'auto' (default) probes WHpx and falls back to TCG. Pass 'whpx' or 'tcg' to
    skip the probe. TCG emulates the CPU, so a cold boot of a freshly built live
    image under TCG can take many minutes; WHpx is hardware-backed and takes
    seconds.

.EXAMPLE
    .\tests\boottest-win.ps1 -Iso out\obsidian-daily-trixie-amd64.iso -Flavor daily

.NOTES
    Exit: 0 = all required checks passed, 1 = failure (log tail printed),
          2 = bad usage or missing prerequisites.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Iso,

    [int]$Timeout = 900,

    [string]$Flavor = '',

    [string]$Qemu = "$env:ProgramFiles\qemu\qemu-system-x86_64.exe",

    # 'auto' probes WHpx and falls back to TCG. TCG always works but emulates
    # the CPU, so a cold boot of a freshly built live image can take many
    # minutes and will time out on a busy host. WHpx is hardware-backed and
    # turns the same boot into seconds. An explicit 'whpx' or 'tcg' skips the
    # probe; 'tcg' is worth pinning in CI when you want determinism over speed.
    [ValidateSet('auto', 'whpx', 'tcg')]
    [string]$Accel = 'auto'
)

$ErrorActionPreference = 'Stop'

function Write-Info($m) { Write-Host "  $m" }
function Write-Ok($m)   { Write-Host "  ok      $m" -ForegroundColor Green }
function Write-Miss($m)  { Write-Host "  MISSING $m" -ForegroundColor Red }

# Read the serial log even while QEMU holds it open for writing.
# [System.IO.File]::ReadAllText opens with FileShare.Read, which throws
# IOException while QEMU's `-serial file:` handle is alive (seen in the field:
# the whole test aborted mid-watch, leaving QEMU orphaned). Opening with
# FileShare.ReadWrite lets us poll a live log. Any IO failure is treated as a
# transient read (return '') rather than an abort; the caller retries.
function Read-SerialLog([string]$Path) {
    try {
        $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open,
                                     [System.IO.FileAccess]::Read,
                                     [System.IO.FileShare]::ReadWrite)
        try {
            $sr = [System.IO.StreamReader]::new($fs)
            try { return $sr.ReadToEnd() } finally { $sr.Dispose() }
        } finally { $fs.Dispose() }
    } catch {
        return ''
    }
}

# --- prerequisites --------------------------------------------------------- #

if (-not (Test-Path -LiteralPath $Iso)) {
    Write-Host "boottest: ISO not found: $Iso" -ForegroundColor Red
    exit 1
}
$Iso = (Resolve-Path -LiteralPath $Iso).Path

if (-not (Test-Path -LiteralPath $Qemu)) {
    Write-Host "boottest: qemu-system-x86_64.exe not found at $Qemu" -ForegroundColor Red
    Write-Host "           pass -Qemu <path> if it is installed elsewhere" -ForegroundColor DarkGray
    exit 2
}
$Qemu = (Resolve-Path -LiteralPath $Qemu).Path

$markersPath = Join-Path $PSScriptRoot 'boot-markers.conf'
if (-not (Test-Path -LiteralPath $markersPath)) {
    Write-Host "boottest: missing the shared marker list: $markersPath" -ForegroundColor Red
    exit 2
}

# --- the shared gate -------------------------------------------------------- #
# Same parse as boottest.sh: first field is the kind, the rest of the line is
# the marker, so markers may contain spaces.

$required  = [System.Collections.Generic.List[string]]::new()
$forbidden = [System.Collections.Generic.List[string]]::new()

foreach ($line in Get-Content -LiteralPath $markersPath) {
    if ($line -match '^\s*(#|$)') { continue }
    if ($line -match '^\s*(\S+)\s+(.*\S)\s*$') {
        switch ($Matches[1]) {
            'required'  { $required.Add($Matches[2]) }
            'forbidden' { $forbidden.Add($Matches[2]) }
        }
    }
}

if ($required.Count -eq 0) {
    # An empty list makes every image pass. That is the exact failure this
    # shared file exists to prevent, so refuse instead of proceeding.
    Write-Host "boottest: $markersPath lists no required markers; refusing to run" -ForegroundColor Red
    Write-Host "           a gate that cannot fail" -ForegroundColor Red
    exit 2
}

# --- accelerator ------------------------------------------------------------- #
# TCG is the safe default but it emulates the CPU. WHpx runs on the Windows
# hypervisor and is roughly an order of magnitude faster, which is the
# difference between a boot gate you can actually iterate against and one that
# times out on a loaded machine.
#
# Two things this must not do:
#   - trust a capability list. `qemu -accel help` prints what the *binary* was
#     built with, which says nothing about whether the host has the feature
#     enabled. (It is also the source of the spelling: the accelerator is
#     'whpx', not 'wphx'. A typo there fails closed into TCG, which looks like a
#     working test that is merely slow.)
#   - trust a machine-less probe. `-machine none` is rejected by the x86 machine
#     class in QEMU 11.1 before the accelerator is ever consulted, so it cannot
#     distinguish "accelerator unavailable" from "machine type refused".
# So: start a real `pc` machine with no boot media and no CPU execution, and see
# whether QEMU survives. If the accelerator cannot initialise, QEMU aborts
# immediately; if it can, the process sits there until we kill it.
function Test-Accel {
    param([string]$Name, [int]$ProbeSeconds = 8)

    $probeLog = Join-Path ([System.IO.Path]::GetTempPath()) `
               ("obsidian-accel-probe-{0}.txt" -f $Name)
    if (Test-Path -LiteralPath $probeLog) { Remove-Item -LiteralPath $probeLog -Force }

    try {
        $p = Start-Process -FilePath $Qemu -PassThru -NoNewWindow `
             -ArgumentList @('-accel', $Name, '-machine', 'pc', '-display', 'none',
                             '-nodefaults', '-S') `
             -RedirectStandardError $probeLog -RedirectStandardOutput "$probeLog.out" `
             -ErrorAction Stop
    } catch {
        Write-Info "accel $Name : could not start probe ($($_.Exception.Message))"
        return $false
    }

    # If it is still alive after the probe window, the accelerator initialised.
    $survived = -not $p.WaitForExit($ProbeSeconds * 1000)
    if (-not $survived) { $code = $p.ExitCode } else { $code = $null }
    if ($survived) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }

    $detail = ''
    if (Test-Path -LiteralPath $probeLog) {
        $t = Get-Content -LiteralPath $probeLog -Raw -ErrorAction SilentlyContinue
        if ($t) { $detail = ($t.Trim() -split "`r?`n" | Select-Object -First 1) }
    }

    if ($survived) {
        Write-Info "accel $Name : available"
        return $true
    }
    Write-Info "accel $Name : unavailable (qemu exited $code) $detail"
    return $false
}

$useAccel = $Accel
if ($Accel -eq 'auto') {
    # Fail closed: never auto-select something unproven, and never let a probe
    # failure abort the run. TCG is slow but always correct.
    $useAccel = if (Test-Accel 'whpx') { 'whpx' } else { 'tcg' }
    if ($useAccel -eq 'tcg') {
        Write-Info 'falling back to TCG: the boot will be slow, expect minutes not seconds'
    }
}
Write-Info "accelerator: $useAccel"

# --- boot ------------------------------------------------------------------- #

$log = Join-Path ([System.IO.Path]::GetTempPath()) `
      ("obsidian-boot-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

Write-Host "boottest: $Iso"
Write-Info "timeout=${Timeout}s  required=$($required.Count)  forbidden=$($forbidden.Count)"
if ($Flavor) { Write-Info "expecting flavor: $Flavor" }
Write-Info "serial log: $log"

if (Test-Path -LiteralPath $log) { Remove-Item -LiteralPath $log -Force }

$qemuArgs = @(
    '-m', '2048'
    '-smp', '2'
    '-boot', 'd'
    '-cdrom', $Iso
    '-display', 'none'
    # -accel is probed above and defaults to WHPX when the host supports it.
    '-accel', $useAccel
    "-serial", "file:$log"
    '-no-reboot'
)

$proc = Start-Process -FilePath $Qemu -ArgumentList $qemuArgs -PassThru -NoNewWindow

$deadline = (Get-Date).AddSeconds($Timeout)
$ready    = $false

while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) {
        Write-Host "boottest: qemu exited (code $($proc.ExitCode)) before the timeout" -ForegroundColor Red
        break
    }
    # Re-reading the whole log every 2s is fine at this size and avoids the
    # half-written-line races you get from holding a file handle open.
    if (Test-Path -LiteralPath $log) {
        $raw = Read-SerialLog $log
        if ($raw -and $raw.Contains('OBSIDIAN-OS-READY')) { $ready = $true; break }
    }
    Start-Sleep -Seconds 2
}

if (-not $proc.HasExited) {
    # The gate has already decided either way; stop the VM rather than leave it
    # burning a core for the rest of the session.
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}

# --- evaluate ---------------------------------------------------------------- #

$fail = $false
$logText = if (Test-Path -LiteralPath $log) { Read-SerialLog $log } else { '' }

if (-not $ready) {
    Write-Host "boottest: FAIL - never saw OBSIDIAN-OS-READY within ${Timeout}s" -ForegroundColor Red
    $fail = $true
} else {
    foreach ($m in $required) {
        if ($logText.Contains($m)) { Write-Ok $m } else { Write-Miss $m; $fail = $true }
    }
    foreach ($m in $forbidden) {
        if ($logText.Contains($m)) {
            Write-Host "  FORBIDDEN '$m' present - image is vanilla Debian, not Obsidian" -ForegroundColor Red
            $fail = $true
        }
    }
    if ($Flavor) {
        $needle = "flavor=$Flavor"
        if ($logText.Contains($needle)) {
            Write-Ok $needle
        } else {
            Write-Miss "$needle (wrong image?)"
            $fail = $true
        }
    }

    Write-Host '  --- attestation ---'
    $seen = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($line in ($logText -split "`r?`n")) {
        if ($line -match '(OBSIDIAN-CHECK[^\r\n]*)') {
            if ($seen.Add($Matches[1].Trim())) {
                Write-Host "  $($Matches[1].Trim())"
            }
        }
    }
}

if ($fail) {
    Write-Host 'boottest: FAIL' -ForegroundColor Red
    Write-Host '--- last 60 lines of serial log ---' -ForegroundColor Red
    if ($logText) {
        ($logText -split "`r?`n" | Select-Object -Last 60) | ForEach-Object {
            Write-Host "  $_"
        }
    } else {
        Write-Host '  (serial log is empty - the guest produced no output at all)' -ForegroundColor Red
    }
    exit 1
}

Write-Host "boottest: PASS (log: $log)" -ForegroundColor Green
exit 0
