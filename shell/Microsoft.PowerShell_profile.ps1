# Obsidian OS — PowerShell 7 profile (the "Windows side" of the unified shell)
# Makes a Windows refugee immediately productive on the Linux core:
#   dir, copy, move, del, type, cls, ipconfig, netstat, tasklist, sc, runas
# all work exactly as in Windows, while every native Linux command still works
# because pwsh runs on the Linux core with bash/zsh reachable, and the helpers
# below are thin wrappers over the real Linux tools.

$ErrorActionPreference = 'Continue'
Set-StrictMode -Version 2.0

# ---- prompt: Windows-style (C:\>) mapped to the Linux PWD ------------------
function prompt {
    $host.UI.RawUI.WindowTitle = "Obsidian [$($env:USER)]"
    "$(Get-Location)> "
}

# ---- filesystem --------------------------------------------------------------
function dir  { Get-ChildItem -Force @args }
function ls   { Get-ChildItem -Force @args }
function copy { Copy-Item @args }
function cp   { Copy-Item @args }
function move { Move-Item @args }
function mv   { Move-Item @args }
function del  { Remove-Item @args }
function rm   { Remove-Item @args }
function type { Get-Content @args }
function cat  { Get-Content @args }
function cls  { Clear-Host }
function tree { $p = @args; if ($p.Length -eq 0) { $p = '.' }; tree "$p" }
function md   { New-Item -ItemType Directory -Force @args }
function whichfile { Get-Command @args }

Set-Alias -Name ren -Value Rename-Item -ErrorAction SilentlyContinue
Set-Alias -Name md  -Value mkdir  -ErrorAction SilentlyContinue

# ---- network ----------------------------------------------------------------
function ipconfig {
    Write-Host ""
    Write-Host "Windows-style ipconfig over Linux network state"
    ip -brief address
    Write-Host ""
    ip -brief route
}
function netstat  { ss -tulpn @args }
function ping     { ping @args }
function tracert {
    # Windows-style traceroute via traceroute(1) if present
    $a = @args
    if ($a -match '^-') { $a = ($a | Where-Object { $_ -notmatch '^-' }) }
    traceroute @a
}
Set-Alias nslookup -Value dig -ErrorAction SilentlyContinue

# ---- process / service --------------------------------------------------------
function tasklist {
    Write-Host "IMAGE NAME          PID     CPU%  MEM(MB)  STATE"
    ps aux --no-headers -o comm,pid,pcpu,pmem,stat | ForEach-Object {
        $p = $_ -split '\s+'
        "{0,-20} {1,-7} {2,5} {3,7}  {4}" -f $p[0], $p[1], $p[2], [math]::Round($p[3]*[math]::Max([double]$env:OBSMEM,4),0), $p[4]
    }
}
function sc   { systemctl @args }
function Get-Process { Get-Process @args }   # native pwsh alias already exists; keep
function runas {
    # runas /user:NAME command  ->  sudo -u NAME command
    $i = [Array]::IndexOf(@args, "/user:")
    if ($i -ge 0) { $u = @args[$i].Substring(7); $rest = @args[($i+1)..(@args.Length-1)]
        sudo -u $u -H sh -c ($rest -join ' ') }
    else { sudo sh -c (@args -join ' ') }
}

# ---- misc Windows ports ---------------------------------------------------------
function whereis { Get-Command @args }
function attrib  { ls -la $args }
function format  { mkfs -t $args }
function taskkill { kill @args }
function shutdownnow { systemctl poweroff }
function rebootnow  { systemctl reboot }
function notepad  {
    # opens an editor; use obsidian-ai "edit" if installed
    if (Get-Command code -ErrorAction SilentlyContinue) { code @args }
    elseif (Get-Command nvim -ErrorAction SilentlyContinue) { nvim @args }
    else { nano @args }
}

# ---- shell parity (final): insist bash is there and gives the Linux feel -----
if (Get-Command bash -ErrorAction SilentlyContinue) {
    function bash { bash @args }
    function sh   { sh @args }
    function zsh  { if (Get-Command zsh -ErrorAction SilentlyContinue) { zsh @args } else { bash @args } }
}

# ReadLine: vim-free, Windows-style home/end, cycling history
Set-PSReadLineOption -EditMode Windows
Set-PSReadLineOption -HistorySearchCursorMovesToEnd $true
Set-PSReadLineKeyHandler -Key UpArrow   -Function HistorySearchBackward
Set-PSReadLineKeyHandler -Key DownArrow -Function HistorySearchForward

Write-Host "Obsidian unified shell: PowerShell 7 over Linux core (bash/zsh available)." -ForegroundColor Cyan
Write-Host "  try: dir, copy, ipconfig, netstat, tasklist, sc status, runas /user:root id"