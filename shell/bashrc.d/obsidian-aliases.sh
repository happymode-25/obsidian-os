# Obsidian OS — bash/zsh Windows-isms (the "other side" of the unified shell)
# Source from ~/.bashrc or ~/.zshrc:
#   [ -f /usr/share/obsidian/shell/obsidian-aliases.sh ] && . /usr/share/obsidian/shell/obsidian-aliases.sh

# ---- Windows file-ops ---------------------------------------------------------
dir()   { ls -laF "$@"; }
copy()  { cp -v "$@"; }
move()  { mv -v "$@"; }
del()   { rm -v "$@"; }
type()  { cat "$@"; }
cls()   { clear; }
md()    { mkdir -p "$@"; }
ren()   { mv "$@"; }
tree()  { command tree -a "$@" 2>/dev/null || find "$@" -print | sed 's;[^/]*/;|--;g'; }
fc()    { diff -u "$@"; }
attrib() { ls -la "$@"; }

# ---- Windows network -----------------------------------------------------------
ipconfig() {
    echo "Windows-style ipconfig over Linux network state";
    ip -brief addr; echo; ip -brief route
}
netstat() { ss -tulpn "$@"; }
ping()    { command ping "$@"; }
tracert() { command traceroute "$@"; }
nslookup(){ command dig +short "$@"; }

# ---- Windows process/service ---------------------------------------------------
tasklist() {
    printf '%-22s %-7s %6s %8s  %s\n' IMAGE PID CPU% MEM% STATE
    ps -eo comm,pid,pcpu,rss,stat --no-headers | while read -r c p cpu r s; do
        printf '%-22s %-7s %5s %7sMB  %s\n' "$c" "$p" "$cpu" "$((r/1024))" "$s"
    done
}
taskkill() { kill "$@"; }
sc()       { systemctl "$@"; }
runas() {
    # runas /user:NAME command
    local j; for j in "$@"; do [ "${j#/user:}" != "$j" ] && u="${j#/user:}"; done
    if [ -n "$u" ]; then shift; shift; sudo -u "$u" -H sh -c "$*"; else sudo sh -c "$*"; fi
}
shutdownnow(){ systemctl poweroff; }
rebootnow(){ systemctl reboot; }
notepad(){
    command -v code  >/dev/null && code "$@"
    command -v nvim  >/dev/null && nvim "$@"
    command -v gedit >/dev/null && gedit "$@"
    nano "$@"
}

# ---- pwrsh bridge: `pwrsh cmd` runs PowerShell (Windows commands in bash) -------
pwrsh() { pwsh -NoProfile -Command "$*"; }
pw()    { pwsh -NoProfile -Command "$*"; }

# ---- prompt: Windows-style drive letter stub (cosmetic, optional) --------------
# PS1 with a DOS-ish flavour:  [C:\home\user]> pwd