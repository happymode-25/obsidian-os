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

    [string]$Qemu = "$env:ProgramFiles\qemu\qemu-system-x86_64.exe"
)

$ErrorActionPreference = 'Stop'

function Write-Info($m) { Write-Host "  $m" }
function Write-Ok($m)   { Write-Host "  ok      $m" -ForegroundColor Green }
function Write-Miss($m)  { Write-Host "  MISSING $m" -ForegroundColor Red }

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
    # -accel tcg: the reference host exposes no VT-x to the guest, so KVM and
    # WHPX are unavailable. TCG is slow but deterministic, which is what a gate
    # wants. Drop this on a host with acceleration to iterate faster.
    '-accel', 'tcg'
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
        $raw = [System.IO.File]::ReadAllText($log)
        if ($raw.Contains('OBSIDIAN-OS-READY')) { $ready = $true; break }
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
$logText = if (Test-Path -LiteralPath $log) {
    [System.IO.File]::ReadAllText($log)
} else { '' }

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
