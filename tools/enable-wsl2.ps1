# Obsidian OS — one-time host setup: enable WSL2 (Virtual Machine Platform).
#
# WHY YOU NEED THIS
#   WSL2 needs the "Virtual Machine Platform" Windows optional feature in order
#   to create VMs. Without it, `wsl --import --version 2` fails with
#   HCS_E_HYPERV_NOT_INSTALLED. This is NOT a firmware/VT-x problem: on this
#   host VBS/HVCI is already running, which proves VT-x works.
#
# USAGE
#   Right-click this file -> "Run with PowerShell", OR open an ADMINISTRATOR
#   PowerShell and run:
#       powershell -ExecutionPolicy Bypass -File .\tools\enable-wsl2.ps1
#
# IT REQUIRES A REBOOT. It will offer to reboot at the end.

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "[warn] $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host "[fatal] $msg" -ForegroundColor Red; exit 1 }

Step "Checking elevation"
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Die "Not running as Administrator. Right-click -> 'Run with PowerShell', or relaunch this shell elevated."
}
Write-Host "    running as $($id.Name)"

Step "Verifying hardware virtualization is available to Windows"
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cs  = Get-CimInstance Win32_ComputerSystem
Write-Host "    CPU                  : $($cpu.Name)"
Write-Host "    HypervisorPresent    : $($cs.HypervisorPresent)"
if ($cs.HypervisorPresent) {
    Write-Host "    (a hypervisor is already present, so VT-x/SLAT flags may read False - that is expected)"
}

Step "Enabling VirtualMachinePlatform"
$vmPlat = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
Write-Host "    before: $($vmPlat.State)"
if ($vmPlat.State -ne 'Enabled') {
    $r = Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -NoRestart
    Write-Host "    after : $($r.RestartNeeded) (restart required)"
} else {
    Write-Host "    already enabled, nothing to do"
}

Step "Enabling Microsoft-Windows-Subsystem-Linux"
$wslFeat = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
if ($wslFeat.State -ne 'Enabled') {
    Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -NoRestart | Out-Null
    Write-Host "    enabled"
} else {
    Write-Host "    already enabled"
}

Step "Current WSL version"
try { wsl --version } catch { Warn "wsl --version unavailable" }

Write-Host ""
Write-Host "======================================================" -ForegroundColor Green
Write-Host " Done. REBOOT, then run:  wsl --set-version 2" -ForegroundColor Green
Write-Host " After the reboot, Obsidian OS can build ISOs in WSL2." -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Green

$answer = Read-Host "`nReboot now? (y/N)"
if ($answer -match '^[Yy]') {
    Restart-Computer
} else {
    Write-Host "Not rebooting. Remember: WSL2 will not work until you do."
}
