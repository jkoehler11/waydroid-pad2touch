#!/usr/bin/env bash
# waydroid-host-fix.sh — make Waydroid usable on a normal desktop Linux host.
#
# Fixes the two problems that make Waydroid look broken while it is not:
#
#   1. NETWORK — Docker sets the IPv4 FORWARD policy to DROP. Waydroid's own
#      nftables accept for waydroid0 cannot override a drop in another base
#      chain, so the container gets DHCP and DNS but no internet at all
#      (blank login web views, "no connection" in apps).
#
#   2. GAMEPAD — Waydroid only forwards keyboard and pointer. A physical
#      controller is never visible to Android, so games see no joystick.
#
# Usage:
#   sudo ./waydroid-host-fix.sh check        # report only, change nothing
#   sudo ./waydroid-host-fix.sh fix          # apply both fixes (idempotent)
#   sudo ./waydroid-host-fix.sh uninstall    # remove what this script added
#
# Tested on Arch + KDE + Docker + nftables (Waydroid 1.6.3, LXC 7).
# Re-runnable: safe to run after every Waydroid or Docker upgrade.

set -uo pipefail

HELPER=/usr/local/bin/waydroid-gamepad-add
UNIT_NET=/etc/systemd/system/waydroid-docker-forward.service
UNIT_PAD=/etc/systemd/system/waydroid-gamepad.service
UDEV_PAD=/etc/udev/rules.d/99-waydroid-gamepad.rules
UDEV_TRIG=/etc/udev/rules.d/99-waydroid-gamepad-trigger.rules
GEN_CONFIG=/var/lib/waydroid/lxc/waydroid/config
TPL_CONFIG=/usr/lib/waydroid/data/configs/config_4

c_ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m%s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m%s\033[0m\n' "$*"; }
hdr()    { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

need_root() {
    [ "$(id -u)" -eq 0 ] || { c_err "Run me with sudo."; exit 1; }
}

# ---------------------------------------------------------------- network ---

forward_policy() {
    # iptables-nft is what Docker uses; fall back to raw nftables query.
    iptables -S FORWARD 2>/dev/null | awk '/^-P FORWARD/ {print $3}'
}

check_network() {
    hdr "network"
    if ! command -v iptables >/dev/null; then
        c_warn "iptables not found — skipping network check"; return
    fi
    local pol; pol=$(forward_policy)
    echo "FORWARD policy: ${pol:-unknown}"
    if [ "${pol:-}" = "DROP" ]; then
        if iptables -C DOCKER-USER -i waydroid0 -j ACCEPT 2>/dev/null &&
           iptables -C DOCKER-USER -o waydroid0 -j ACCEPT 2>/dev/null; then
            c_ok "waydroid0 already accepted in DOCKER-USER"
        else
            c_err "FORWARD is DROP and waydroid0 is NOT accepted — container has no internet"
            echo "      fix: sudo $0 fix"
        fi
    else
        c_ok "FORWARD is not DROP — Docker is not blocking Waydroid"
    fi
}

fix_network() {
    hdr "network"
    local pol; pol=$(forward_policy)
    if [ "${pol:-}" != "DROP" ]; then
        c_ok "FORWARD policy is ${pol:-ACCEPT}; nothing to do"; return
    fi
    iptables -n -L DOCKER-USER >/dev/null 2>&1 || iptables -N DOCKER-USER
    iptables -C DOCKER-USER -i waydroid0 -j ACCEPT 2>/dev/null ||
        iptables -I DOCKER-USER 1 -i waydroid0 -j ACCEPT
    iptables -C DOCKER-USER -o waydroid0 -j ACCEPT 2>/dev/null ||
        iptables -I DOCKER-USER 2 -o waydroid0 -j ACCEPT
    c_ok "waydroid0 accepted ahead of Docker's drop"

    cat > "$UNIT_NET" <<'EOF'
[Unit]
Description=Allow Waydroid (waydroid0) traffic past Docker's FORWARD DROP policy
After=docker.service
Wants=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/bash -c 'iptables -C DOCKER-USER -i waydroid0 -j ACCEPT 2>/dev/null || iptables -I DOCKER-USER 1 -i waydroid0 -j ACCEPT; iptables -C DOCKER-USER -o waydroid0 -j ACCEPT 2>/dev/null || iptables -I DOCKER-USER 2 -o waydroid0 -j ACCEPT'

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now waydroid-docker-forward.service >/dev/null 2>&1
    c_ok "persisted as $UNIT_NET"
    echo "  verify inside the container:  ping -c2 8.8.8.8"
}

# ---------------------------------------------------------------- gamepad ---

find_pad() {
    local f
    for f in /dev/input/by-id/*-joystick; do
        [ -e "$f" ] || continue
        echo "$f"; return
    done
    return 1
}

pad_name() {  # given /dev/input/by-id/... -> device name from sysfs
    local ev; ev=$(readlink -f "$1")
    cat "/sys/class/input/$(basename "$ev")/device/name" 2>/dev/null
}

check_pad() {
    hdr "gamepad"
    local pad; pad=$(find_pad) || { c_warn "no controller found at /dev/input/by-id/*-joystick"; return; }
    echo "controller: $(pad_name "$pad") ($pad)"
    [ -e /dev/waydroid-gamepad ] && c_ok "udev symlink /dev/waydroid-gamepad present" \
                                 || c_err "no /dev/waydroid-gamepad symlink — udev rule missing"
    [ -f "$HELPER" ] && c_ok "injection helper installed" || c_err "injection helper missing"
    grep -q 'devices.allow' "$GEN_CONFIG" 2>/dev/null \
        && c_ok "LXC device cgroup rule present" \
        || c_err "LXC config lacks lxc.cgroup2.devices.allow (Android will get EPERM opening the pad)"
}

fix_pad() {
    hdr "gamepad"
    local pad name; pad=$(find_pad) || { c_warn "no controller found — skipping gamepad setup"; return; }
    name=$(pad_name "$pad")
    echo "controller: $name"

    cat > "$UDEV_PAD" <<EOF
# Give the controller a stable name and let the Waydroid container read it.
SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="$name", MODE="0666", SYMLINK+="waydroid-gamepad"
EOF
    udevadm control --reload-rules
    udevadm trigger --action=change --subsystem-match=input
    sleep 1
    [ -e /dev/waydroid-gamepad ] && c_ok "/dev/waydroid-gamepad -> $(readlink -f /dev/waydroid-gamepad)"

    cat > "$HELPER" <<'SCRIPT'
#!/bin/bash
# Inject the host gamepad into the running Waydroid container as an evdev node.
#
# Waydroid forwards only keyboard/pointer, so pads must be added by hand.
# The node MUST be created with mode 666 in one step (mknod -m 666): Android's
# EventHub reacts to IN_CREATE and opens immediately, so a chmod afterwards
# loses the race and the pad stays invisible until the next container start.
set -u
SRC=/dev/waydroid-gamepad
[ -e "$SRC" ] || { echo "no gamepad at $SRC"; exit 0; }
read -r MAJ MIN < <(stat -L -c '%Hr %Lr' "$SRC")
for _ in $(seq 1 90); do
    PID=$(pgrep -x -f "/system/bin/init second_stage" | head -1)
    if [ -n "${PID:-}" ] && nsenter -t "$PID" -m -p --root --wd -- /system/bin/sh -c 'test -d /dev/input' 2>/dev/null; then
        nsenter -t "$PID" -m -p --root --wd -- /system/bin/sh -c "
            /system/bin/rm -f /dev/input/event20
            /system/bin/mknod -m 666 /dev/input/event20 c $MAJ $MIN
        "
        echo "gamepad injected: c $MAJ:$MIN as /dev/input/event20"
        exit 0
    fi
    sleep 1
done
echo "waydroid container did not come up; gamepad not injected"
exit 1
SCRIPT
    chmod 755 "$HELPER"

    cat > "$UNIT_PAD" <<EOF
[Unit]
Description=Inject host gamepad into the Waydroid container

[Service]
Type=oneshot
ExecStart=$HELPER
TimeoutStartSec=120
EOF
    cat > "$UDEV_TRIG" <<'EOF'
# Waydroid recreates the waydroid0 bridge on every container start; inject the pad then.
SUBSYSTEM=="net", KERNEL=="waydroid0", ACTION=="add", TAG+="systemd", ENV{SYSTEMD_WANTS}="waydroid-gamepad.service"
EOF
    systemctl daemon-reload
    udevadm control --reload-rules
    c_ok "helper + service + udev trigger installed"

    # LXC device cgroup: without this Android gets EPERM opening the node.
    for cfg in "$GEN_CONFIG" "$TPL_CONFIG"; do
        [ -f "$cfg" ] || continue
        grep -q 'lxc.cgroup2.devices.allow' "$cfg" ||
            printf '\nlxc.cgroup2.devices.allow = a\n' >> "$cfg"
    done
    c_ok "LXC device cgroup opened (lxc.cgroup2.devices.allow = a)"

    if waydroid status 2>/dev/null | grep -q "Container:[[:space:]]*RUNNING"; then
        systemctl start waydroid-gamepad.service
        echo "  verify: adb -s 192.168.240.112:5555 shell dumpsys input | grep -i gamepad"
    else
        c_warn "Waydroid not running — the pad is injected automatically on the next start"
    fi
}

# -------------------------------------------------------------- uninstall ---

uninstall() {
    hdr "uninstall"
    systemctl disable --now waydroid-docker-forward.service >/dev/null 2>&1
    rm -f "$UNIT_NET" "$UNIT_PAD" "$UDEV_PAD" "$UDEV_TRIG" "$HELPER"
    iptables -D DOCKER-USER -i waydroid0 -j ACCEPT 2>/dev/null
    iptables -D DOCKER-USER -o waydroid0 -j ACCEPT 2>/dev/null
    for cfg in "$GEN_CONFIG" "$TPL_CONFIG"; do
        [ -f "$cfg" ] && sed -i '/lxc.cgroup2.devices.allow = a/d' "$cfg"
    done
    systemctl daemon-reload; udevadm control --reload-rules
    c_ok "removed (a running container keeps its device node until restart)"
}

# ------------------------------------------------------------------ main ---

case "${1:-check}" in
    check)     need_root; check_network; check_pad ;;
    fix)       need_root; fix_network; fix_pad ;;
    uninstall) need_root; uninstall ;;
    *)         echo "usage: sudo $0 {check|fix|uninstall}"; exit 1 ;;
esac
