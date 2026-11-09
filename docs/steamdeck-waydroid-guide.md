# Waydroid on the Steam Deck — install, networking, and controller support

A complete path from a stock Steam Deck to playing **Pokémon UNITE Revival** (or any Android game)
in Waydroid, with working internet and a working controller.

Written from a working setup: SteamOS 3.9.5 (Deck LCD/OLED, SteamOS 3.6+), Waydroid 1.6.3, Android 13
GAPPS image, Xbox-style controller.

---

## 0. What you need

- Steam Deck in **Desktop Mode** (the installer uses Konsole and pacman).
- A keyboard/mouse or the touchscreen — you will type in Konsole.
- ~10 GB free on `/home` for Waydroid images plus your game data, or put the game data on the SD card.
- Your sudo password (the Deck's `deck` user has one if you ran `passwd`; the installer asks for it).
- The game files: `pokemon-unite-revival-<ver>.apk` and its data pack `pokemon-u-revival-data.tar`
  (several GB — get them from wherever the project distributes them).

---

## 1. Install Waydroid (SteamOS installer from GitHub)

### Pre-flight: does this Deck support it?

Run these first — they decide everything, and skipping them is how people burn an hour:

```bash
uname -r                    # kernel, e.g. 6.18.50-valve2-1-neptune-618
df -h /home | tail -1       # installer refuses with < 10 GB free
echo $XDG_SESSION_TYPE      # must be a Desktop Mode session (the script needs X/zenity)
```

Waydroid on SteamOS needs the **`binder_linux` kernel module**, and the installer only ships a
prebuilt module for **one exact kernel** (currently `6.18.50-valve2-1-neptune-618`). Check what your
installer copy supports:

```bash
ls ~/steamos-waydroid-installer/extras/kmod/
```

If that directory does not contain a folder named exactly `$(uname -r)`, the script's sanity check
will exit and you cannot build the module from SteamOS packages unless matching headers exist:

```bash
pacman -Ss "linux-neptune.*-headers" | grep -i headers
```

No headers for your `uname -r` means **stop** — Waydroid cannot run on that kernel yet. Either stay on
the kernel the repo targets, or wait for the project to ship a module for yours. (A Deck on a newer
kernel such as `7.2.7-valve2-2-neptune-72` hits exactly this wall: no module, no headers.)

Also note the branch naming: the repo publishes `testing` plus per-version branches (`3.8.28`, …).
**Use `testing` for current SteamOS**, and check the README for a branch matching your exact version:

```bash
git clone --depth=1 -b testing https://github.com/ryanrudolfoba/steamos-waydroid-installer
```

### Install

The maintained SteamOS installer is **ryanrudolfoba/steamos-waydroid-installer**:
<https://github.com/ryanrudolfoba/steamos-waydroid-installer>


It handles the three things Waydroid can't do by itself on SteamOS: installing the packages while
`steamos-readonly` is disabled, building the `binder_linux` kernel module for the Deck's kernel, and
downloading the Android image.

```bash
# in Desktop Mode → Konsole
cd ~
git clone --depth=1 https://github.com/ryanrudolfoba/steamos-waydroid-installer
cd steamos-waydroid-installer
chmod +x steamos-waydroid-installer.sh
./steamos-waydroid-installer.sh
```

Pick these in the menu:

1. **Install Waydroid**.
2. Image choice → **A13_GAPPS** (Android 13 with Google Play services — needed for a lot of games;
   the no-GApps image is lighter but some apps refuse to start without Play services).
3. Let it finish, then **exit** and go back to Game Mode. The script adds a Waydroid launcher to your
   Steam library, so you can start Android from Game Mode later without a terminal.

Sanity check in Desktop Mode:

```bash
waydroid status          # Session/Container should say RUNNING once launched
```

Notes:

- **Persistence:** a SteamOS update can wipe `/usr` (packages, binder module). Re-run the installer's
  *reinstall* option after big OS updates; your Android data in `/var/lib/waydroid` survives.
- The installer adds `firewalld` rules for `waydroid0` (`--add-interface=trusted`, forward, ports
  53/67) — that is SteamOS's equivalent of the Docker problem described in §3. Don't remove them.
- If the script complains about `cage` or `wlr-randr`, run it again; it retries package installs.

---

## 2. Put the game into Waydroid

Two things have to be inside Android: the APK and the data pack.

**Easiest path — from the Deck's terminal (Desktop Mode):**

```bash
# where your downloads are, adjust as needed
waydroid app install ~/Downloads/pokemon-unite-revival-1.0.1.apk
adb connect 192.168.240.112:5555          # or: waydroid adb connect
adb push ~/Downloads/pokemon-u-revival-data.tar /sdcard/Download/
```

If `adb` says `unauthorized`, run `waydroid adb connect` (it uses the Deck's own adb key, which is
already trusted by the container).

**Then in Android:** launch the game → it shows *"Pokémon U Revival · Game data — Import the game
data pack"* → **Import file** → **Downloads** → `pokemon-u-revival-data.tar`.

Give it room: the import can need roughly the size of the archive again while it unpacks. If
`/home` is tight, delete the `.tar` from Android (`adb shell rm /sdcard/Download/pokemon-u-revival-data.tar`)
after the import completes.

**Login:** the revival project's login goes through its own web backend. If the login screen is blank
while a normal web page loads fine, the project's server is the suspect, not you — check their
announcements. (In our case the worker's `/health` endpoint answered `200` while the login endpoint
returned `503` from three different networks: a server-side outage.)

---

## 3. Networking: "everything works but nothing loads"

**Symptom:** Android starts, apps open, but web views are blank, the store spins, login never
completes. Mouse and keyboard work fine.

**Cause:** the host firewall drops *forwarded* traffic. The common culprits:

| Host setup | What drops waydroid0 traffic |
|---|---|
| Docker installed | Docker sets `FORWARD` policy to `DROP`; Waydroid's own accept lives in another nftables table and cannot override it |
| firewalld | `waydroid0` not in a trusted zone / no forwarding |
| ufw | `DEFAULT_FORWARD_POLICY="DROP"` in `/etc/default/ufw` |

**Fast diagnosis** (container shell):

```bash
waydroid adb connect
adb -s 192.168.240.112:5555 shell
# inside Android:
ping -c2 192.168.240.1        # gateway — should work
ping -c2 8.8.8.8              # 100% loss = forwarded traffic is being dropped
```

DNS still resolving while ping fails is the signature: DHCP/DNS are answered locally by Waydroid's
own dnsmasq on `192.168.240.1`.

**Fix for Docker (Arch/Fedora/Debian alike):**

```bash
sudo iptables -I DOCKER-USER 1 -i waydroid0 -j ACCEPT
sudo iptables -I DOCKER-USER 2 -o waydroid0 -j ACCEPT
```

Make it survive reboots — either run the included script (`sudo ./waydroid-host-fix.sh fix`, it writes
a systemd oneshot unit), or drop this in `/etc/systemd/system/waydroid-docker-forward.service`:

```ini
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
```

**Fix for firewalld (what SteamOS uses):**

```bash
sudo firewall-cmd --zone=trusted --add-interface=waydroid0
sudo firewall-cmd --zone=trusted --add-forward
sudo firewall-cmd --zone=trusted --add-port={53,67}/udp
sudo firewall-cmd --runtime-to-permanent
```

**Fix for ufw:** set `DEFAULT_FORWARD_POLICY="ACCEPT"` in `/etc/default/ufw` and reload.

**On SteamOS specifically:** the installer already configures firewalld. If Android has no internet
after an OS update, re-run the installer's repair option — the firewalld zone for `waydroid0` is the
first thing to check. Docker is not normally installed on a Deck, so the Docker fix is usually not
needed there.

---

## 4. Controller support

**Why the pad does nothing:** Waydroid forwards only keyboard and pointer from the host seat (through
FIFOs at `/dev/input/wl_keyboard_events` and `wl_pointer_events` inside the container). A physical
gamepad is never passed through, so Android has no joystick device at all — the game can't see it even
though SteamOS does.

**What "working" looks like:** inside the container,
`adb -s 192.168.240.112:5555 shell dumpsys input | grep -E '^ *[0-9]+: '` lists your pad with
`Classes: KEYBOARD | GAMEPAD | JOYSTICK` next to `wayland_keyboard` / `wayland_pointer` / `wayland_tablet`.

**Automated fix:** `waydroid-host-fix.sh`

```bash
sudo ./waydroid-host-fix.sh check      # report only
sudo ./waydroid-host-fix.sh fix        # apply
```

It does four things:

1. **udev rule** — gives your controller a stable symlink `/dev/waydroid-gamepad` and mode 0666, so
   reconnects and changing `eventN` numbers don't matter.
2. **LXC device cgroup** — appends `lxc.cgroup2.devices.allow = a` to
   `/var/lib/waydroid/lxc/waydroid/config`. Without it Android gets `Permission denied` opening the
   injected node (`EventHub: could not open /dev/input/event20, Permission denied` in logcat).
3. **Injection helper** — `/usr/local/bin/waydroid-gamepad-add` enters the container's namespaces and
   creates `/dev/input/event20` pointing at the pad.
4. **Automatic trigger** — a udev rule on `waydroid0` appearing starts a systemd oneshot, so the pad is
   re-injected on every container start.

**The one subtlety worth knowing:** the node must be created with `mknod -m 666` in a single step.
Android's EventHub reacts to `IN_CREATE` and opens the device immediately; if you `mknod` and then
`chmod`, EventHub loses the race, logs `Permission denied`, and the pad stays invisible until the next
container start. The helper does it in one `mknod`.

**Do NOT** bind-mount the pad into `/dev/input` in the LXC config
(`lxc.mount.entry = /dev/input/eventX dev/input/...`). That replaces Waydroid's input FIFOs and the
**mouse stops working** — and Waydroid then regenerates nothing until restart.

**On the Deck:** the built-in controls and any controller appear to the host as an X-Box 360 pad
(Steam Input). Set the game's controller layout to **Gamepad with mouse trackpad** or a plain
**Gamepad** template in Game Mode before launching Waydroid, otherwise Steam keeps swallowing the
input as desktop mouse/keyboard. Then run `waydroid-host-fix.sh fix` once.

**If the pad works in the Android UI but not in the game:** the game binds gamepad actions per screen.
Fall back to a controller→touch mapper inside Android (e.g. a touch-profile app) or play with
mouse/touch on the Deck's touchscreen.

---

### Touch-only games: synthesise touch instead

If the game has no controller settings at all (Pokémon UNITE is like this), a gamepad will never work
as a gamepad — instead create a **virtual touchscreen** and map the pad onto the HUD.

1. `pad2touch` (in this folder) runs as root, creates a uinput multitouch device named `Pad2Touch`,
   reads the pad at `/dev/waydroid-gamepad`, and emits touches at configured coordinates.
2. Inject its event node into the container the same way as the pad (`mknod -m 666`), and re-inject on
   every Waydroid start — the `waydroid0` udev trigger already does this.
3. Calibrate: take a screenshot of a live match (`adb shell screencap -p /sdcard/x.png`, pull it),
   read the real centres of the joystick and each ability button, and write them into
   `/etc/pad2touch.conf`. `sudo systemctl restart pad2touch` applies them instantly.

Three things are required, and each failure has its own logcat message:

| Logcat | Meaning | Fix |
|---|---|---|
| `sources=MOUSE` (works in menus, not in game) | device treated as touchpad | set `INPUT_PROP_DIRECT` via `UI_SET_PROPBIT` |
| `Touch device ... did not report support for X or Y axis` | MT axes only | also declare `ABS_X`/`ABS_Y` |
| `Device reconfigured: size 1x1` | axes report min=max=0 | send `UI_ABS_SETUP` with real ranges per axis |

Working state looks like: `size 2560x1396, orientation 0, mode 1` and `sources=TOUCHSCREEN`.

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Blank web views, login never completes | forwarded traffic dropped | §3 |
| `UnsatisfiedLinkError ... libmain.so is for EM_AARCH64 instead of EM_X86_64` | ARM translation (`libhoudini`) missing — Waydroid's **overlay mount failed** | see below |
| `EventHub: could not open /dev/input/eventN, Permission denied` | device cgroup or the `chmod` race | §4 |
| Mouse stops working after fiddling with input | you bind-mounted something into `/dev/input` | remove that `lxc.mount.entry`, restart Waydroid |
| Container stuck `FROZEN` / adb hangs | Waydroid froze the container because no window is open | `waydroid show-full-ui` |
| `container failed to start` after manual pokes | stale `/run/waydroid-lxc/network_up` or the bridge gone | `sudo rm -f /run/waydroid-lxc/network_up /run/waydroid-lxc/dnsmasq.pid`, then restart Waydroid |

**ARM translation / the overlay trap.** Waydroid mounts an overlay from `/var/lib/waydroid/overlay`
(the GApps extras, `libhoudini.so`, key layouts) over the system image. That mount fails if another
overlay is already mounted from the same source — in practice, **if a Docker container is running**
when Waydroid starts. Waydroid then logs
`mount: /var/lib/waydroid/rootfs: overlay already mounted on /var/lib/docker/...` and
`Mounting overlays failed. The feature has been disabled.`, and every ARM-only game dies with the
`EM_AARCH64` error above.

```bash
docker ps                              # stop/quit containers first
sudo systemctl stop docker             # or just close Docker Desktop / stop your containers
waydroid session stop && waydroid show-full-ui
ls /var/lib/waydroid/rootfs/system/lib64/libhoudini.so   # must exist now
```

Then the game launches normally.

---

## 6. Files this setup creates

| Path | Purpose |
|---|---|
| `/etc/udev/rules.d/99-waydroid-gamepad.rules` | stable `/dev/waydroid-gamepad` symlink, mode 0666 |
| `/etc/udev/rules.d/99-waydroid-gamepad-trigger.rules` | starts the injection service when `waydroid0` appears |
| `/usr/local/bin/waydroid-gamepad-add` | injects the pad into the container |
| `/etc/systemd/system/waydroid-gamepad.service` | oneshot wrapper |
| `/etc/systemd/system/waydroid-docker-forward.service` | re-adds the DOCKER-USER accepts at boot |
| `/var/lib/waydroid/lxc/waydroid/config` | gains `lxc.cgroup2.devices.allow = a` |

All of it is removable with `sudo ./waydroid-host-fix.sh uninstall`.
