# Gamepad on Android games in Waydroid — full setup guide

**What this gets you:** a physical controller working in a touch-only Android game running inside
Waydroid — including games that have no controller support at all — plus **Unite Mapper**, a small
Android app where you type or tap the on-screen positions of each control.

Written from a working setup: Arch desktop, Waydroid 1.6.3, Xbox 360 pad, Pokémon UNITE (Revival).

Everything here is free and open source:
**https://github.com/jkoehler11/waydroid-pad2touch**

---

## Contents

1. [Before you start](#1-before-you-start)
2. [Install Waydroid](#2-install-waydroid)
3. [Get a controller working](#3-get-a-controller-working)
4. [Install and set up Unite Mapper](#4-install-and-set-up-unite-mapper)
5. [Troubleshooting](#5-troubleshooting)
6. [Why it works this way](#6-why-it-works-this-way)

---

## 1. Before you start

| Requirement | Notes |
|---|---|
| **Wayland session** | Waydroid is a Wayland client. On X11 it needs `weston` or `cage` as a nested compositor. |
| **Kernel with binder** | Most distro kernels ship `binder_linux`. Check: `modprobe binder_linux devices="binder,hwbinder,vndbinder"` (no error = good). |
| **~10 GB disk** | System image plus apps. |
| **A gamepad** | Any XInput/DirectInput pad that shows up as `/dev/input/event*`. Xbox pads are the best tested. |
| **A game that runs in Waydroid** | This guide assumes it already launches and you can play it with a mouse. |

Two things worth knowing up front:

- **Android games cannot use a controller that Android itself can't see.** Waydroid has no gamepad
  input path at all, so the controller has to be injected — that's Section 3.
- **Overlay mapper apps from the Play Store will not work here.** Mantis, Octopus and friends
  activate over *wireless debugging*, and Waydroid's GAPPS image has no Wi-Fi interface, so
  wireless debugging cannot be enabled. That's why this project exists.

---

## 2. Install Waydroid

Official docs (always check these first): **https://docs.waydro.id/usage/install-on-desktops**

### Arch Linux

```bash
yay -S waydroid waydroid-image-gapps
# or, for a build without Google apps (smaller, no Play Store):
yay -S waydroid waydroid-image
```

Full instructions and troubleshooting: <https://wiki.archlinux.org/title/Waydroid>

Then initialise the image:

```bash
sudo waydroid init -s GAPPS      # omit -s GAPPS for the vanilla image
```

### Fedora

```bash
sudo dnf install waydroid
```

On Silverblue/Kinoite and other immutable spins:

```bash
rpm-ostree install waydroid
```

Launch Waydroid from the applications menu and, when it asks for OTA URLs, paste:

- System OTA: `https://ota.waydro.id/system`
- Vendor OTA: `https://ota.waydro.id/vendor`

### Debian / Ubuntu and derivatives

Check yours first — recent releases ship it:

| Release | How |
|---|---|
| Debian 14+, Ubuntu 26.10+ | In the official repository — just `sudo apt install waydroid` |
| Debian 13 (Trixie) | Available in **backports** — enable backports, then install |
| Older releases | Add the third-party repo, below |

```bash
# older Debian/Ubuntu only
sudo apt install curl ca-certificates -y
curl -s https://repo.waydro.id | sudo bash     # append  -s noble  etc. if detection fails
sudo apt update
sudo apt install waydroid -y
```

Make sure you're on a Wayland session before launching (Ubuntu 22.04+ defaults to it).

### openSUSE Tumbleweed / Slowroll

Community guide maintained here:
<https://github.com/waydroid/waydroid/discussions/1463>

### Void Linux

```bash
sudo xbps-install -S waydroid
```

Read `/usr/share/doc/waydroid/README.voidlinux` afterwards.

### Anything else

Check <https://docs.waydro.id/usage/install-on-desktops> — NixOS, postmarketOS, Sailfish, Zorin and
others all have instructions there.

### First run

```bash
# start the container (root), then the session (your user, separate terminal)
sudo waydroid container start
waydroid session start

# when it says "Android with user 0 is ready"
waydroid show-full-ui
```

To use the Play Store you need the **GAPPS** image. Google will report the device as uncertified
until you register it — get the Android ID with:

```bash
adb shell settings get secure android_id     # or: waydroid shell -- settings get secure android_id
```

then register it at <https://www.google.com/android/uncertified>.

### If web pages and logins don't work

This bites everyone running Docker on the same machine. Docker sets the IPv4 `FORWARD` policy to
`DROP`, and Waydroid's traffic dies even though DHCP and DNS work (Waydroid runs its own dnsmasq).
Symptom: apps load, but every page and login times out.

```bash
# allow forwarding for the waydroid bridge
sudo iptables -I DOCKER-USER 1 -i waydroid0 -j ACCEPT
sudo iptables -I DOCKER-USER 2 -o waydroid0 -j ACCEPT
```

To make it survive reboots, save those two rules as a systemd oneshot unit that runs after
`docker.service`. A ready-made `waydroid-docker-forward.service` is in the repo under `systemd/`.

---

## 3. Get a controller working

### The problem, precisely

Waydroid forwards **keyboard, pointer and tablet** events from your desktop into Android. It has no
equivalent path for gamepads, so a plugged-in controller is invisible to Android — `dumpsys input`
shows only `wayland_keyboard`, `wayland_pointer` and `wayland_tablet`.

The fix is to hand the pad to Android as a real input device, and to translate its buttons and
sticks into touches for the game.

```
gamepad (/dev/input/eventN)
      │  udev symlink
      ▼
/dev/waydroid-gamepad ──► pad2touch (host daemon, uinput)
                                │
                                ▼
                    Pad2Touch virtual touchscreen
                                │  injected into the container
                                ▼
                        /dev/input/event21 ──► Android ──► game
```

### Step 1 — give the pad a stable name

Find your pad's name:

```bash
cat /proc/bus/input/devices | grep -A2 -i "x-box\|gamepad\|controller"
```

Create `/etc/udev/rules.d/99-waydroid-gamepad.rules`, replacing the name with yours:

```
SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="Microsoft X-Box 360 pad", MODE="0666", SYMLINK+="waydroid-gamepad"
```

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
ls -l /dev/waydroid-gamepad      # should exist now
```

### Step 2 — pass the device into the container

Waydroid's LXC config already permits input devices; what it needs is a mount entry. Add to
`/usr/lib/waydroid/data/configs/config_4` (the `_4` suffix is the API level — use whichever
`config_*` your installation has):

```
lxc.mount.entry = /dev/waydroid-gamepad dev/input/event20 none bind,create=file,optional 0 0
```

Because the node must exist *inside* the container's own namespace, the cleanest approach is the
small helper in the repo (`waydroid-gamepad-add` + a systemd unit triggered by the `waydroid0`
interface appearing), which does an `mknod -m 666` in one step:

```bash
sudo install -m 755 waydroid-gamepad-add /usr/local/bin/
sudo cp systemd/waydroid-gamepad.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now waydroid-gamepad.service
```

> **Do not bind-mount a file over `/dev/input/event*` on a running container.** It takes Waydroid's
> keyboard/pointer FIFOs with it and your mouse stops working inside Android.

### Step 3 — install the mapper daemon

The repo has an installer that handles the whole chain — udev rule, container plumbing, daemon,
systemd units:

```bash
git clone https://github.com/jkoehler11/waydroid-pad2touch
cd waydroid-pad2touch
sudo ./waydroid-host-fix.sh check     # reports what is missing
sudo ./waydroid-host-fix.sh fix       # applies it
```

Then confirm Android can see the virtual touchscreen:

```bash
waydroid shell -- dumpsys input | grep -A2 Pad2Touch
#   Pad2Touch
#     Classes: TOUCH | TOUCH_MT
```

And that the pad is visible too:

```bash
waydroid shell -- dumpsys input | grep -i "x-box"
```

### Step 4 — check the mapping

`/etc/pad2touch.conf` holds the screen coordinates and the button bindings. You do **not** need to
edit it by hand — Section 4 sets it from an app — but the daemon prints what it resolved at
startup, which is the quickest way to confirm a config is live:

```bash
journalctl -u pad2touch.service -n 6 --no-pager | grep bindings
# pad2touch: bindings: B=a(2428,1228), RT=b(2080,1180), RB=x(2167,1011), ...
```

---

## 4. Install and set up Unite Mapper

**Unite Mapper** is a small Android app (about 20 KB, no dependencies) that owns the coordinates and
the button bindings. It can capture positions by having you tap the game, so you never guess pixels.

### Install the app

```bash
# from the repo
waydroid app install apk/UniteMapper.apk

# or build it yourself (needs only an Android SDK, no Gradle)
cd app && ./build.sh
```

Grant the overlay permission it needs for tap-to-capture:

```bash
waydroid shell -- appops set com.koehler.unitemapper SYSTEM_ALERT_WINDOW allow
```

### Install the host half

The app writes a JSON profile; a host script pulls it and applies it to the daemon.

```bash
sudo install -m 755 host/unite-profile-sync /usr/local/bin/
sudo cp systemd/unite-profile-sync.service systemd/unite-profile-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now unite-profile-sync.timer
```

The timer checks every 20 seconds. When the profile changes it rewrites `/etc/pad2touch.conf`,
restarts the daemon and re-injects the touch device — so **saving in the app is all you do.**

### Register your HUD

1. Open **Unite Mapper** in Waydroid.
2. Press **Capture coordinates by tapping the game**. The game comes to the front with a bar across
   the top reading `Tap 1/9`.
3. Tap the named control on screen. It advances to the next.
4. Nine taps, in this order:

   `Basic attack → Move 1 → Move 2 → Battle item → Score → Unite Move → Recall → joystick centre → camera area`

5. The ninth tap saves automatically. Within ~20 seconds the controller uses those positions.

Tapping the **bottom-left corner** cancels a capture.

### Set the button bindings

Each control row has a dropdown: `none, A, B, X, Y, LB, RB, LT, RT, START, BACK`. Pick whatever
matches the layout you're used to, then press **Save profile**. `none` disables that control.

Defaults (chosen to mirror a Switch-style layout): Basic attack **B**, Move 1 **RB**,
Move 2 **RT**, Battle item **X**, Score **Y**, Unite Move **LT**, Recall **BACK**.

**Apply default button mappings** restores the dropdowns without touching your captured
coordinates. **Load measured defaults** resets *both* — only use it if you want to start over.

### Manual numbers

You can also type coordinates in directly. The row layout on a 2560×1366 surface (the defaults):

| Control | X | Y |
|---|---|---|
| Movement stick centre | 410 | 1048 |
| Basic attack | 2428 | 1228 |
| Move 1 | 2167 | 1011 |
| Move 2 | 2080 | 1180 |
| Battle item | 2164 | 1265 |
| Score | 1638 | 1218 |
| Unite Move | 2370 | 828 |
| Recall | 1700 | 1300 |
| Camera area | 1280 | 420 |

Stick radius is 120 px; raise it if the character walks slowly at full tilt, lower it if a gentle
push runs at full speed.

### Changing screen size

Coordinates are absolute pixels. If you resize the Waydroid window, the touch device is rebuilt to
the new size automatically, but **the coordinates no longer line up** — re-capture. The app shows the
current resolution at the top so you can spot a mismatch.

---

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Nothing responds after a button press | More than 9 multitouch slots in use — the allocator ran past slot 9 and corrupted the stream | Use the repo's daemon (fixed per-control slots) — this is already fixed upstream |
| Movement stops when you press a button, or keeps going after you let go | The pad reports garbage axis values on button edges (real Xbox pads: `+1.00,+0.10` jumping to `-0.04,-0.09` in one sample) | Handled by spike rejection in the daemon; don't add axis "freezing" logic on top — it breaks releasing |
| 1–2 second freezes, repeatedly | The daemon is crash-looping; each restart re-registers the touch device with Android | `journalctl -u pad2touch.service \| grep -c Traceback` — fix the traceback first, never tune coordinates around it |
| Only some buttons work / bindings seem ignored | The config parser silently dropped unknown keys or non-numeric values | Compare `journalctl -u pad2touch.service \| grep bindings` with `/etc/pad2touch.conf`; they must match |
| Touch works in menus but not in game | Coordinates are off — they're absolute pixels, not percentages | Re-capture that control |
| Capture overlay opens the home screen instead of the game | The game's launcher activity is a downloader, not the game | Use the app from the repo, which targets the game activity directly |
| App can't save: "permission denied" | The profile file is owned by `shell` (e.g. copied in with `adb push`) | Re-capture or save from the app; if it persists, see the README note on fixing ownership from inside the container |
| Waydroid apps can't reach the internet | Docker's `FORWARD DROP` policy | Section 2, "If web pages and logins don't work" |
| Controller fine on desktop, dead in Android | Pad node missing inside the container | `waydroid shell -- ls -l /dev/input/` — if there's no injected node, re-run `sudo /usr/local/bin/pad2touch-inject` |

Restarting after a config change:

```bash
sudo systemctl restart pad2touch.service
sudo /usr/local/bin/pad2touch-inject     # required: a restart creates a new device node
```

---

## 6. Why it works this way

You might reasonably ask why the mapping cannot simply live in an Android app.

An Android app **cannot read a controller while another app has focus**. Android delivers input to
the window that has focus, so a mapper either has to *be* the game (a "space"/virtualisation app, as
Octopus does), run with **root**, or activate itself over **ADB wireless debugging**. Overlay mappers
take the ADB route. Waydroid's GAPPS image has no `wlan0`, `svc wifi enable` leaves *Wi-Fi is
disabled*, and `adb_wifi_enabled` resets to `0` — so that route is closed.

What's left is the split this project uses:

- the **app** owns the data you'd want a UI for — coordinates, button bindings, and a
  tap-to-capture overlay;
- the **host daemon** owns the input — it can read `/dev/input/event*` directly and produce a
  virtual touchscreen, no Android permissions required.

It also means the mapping keeps working if Android restarts, and that you can debug it with
`journalctl` instead of logcat.

---

## Credits and licence

MIT. Issues and pull requests: **https://github.com/jkoehler11/waydroid-pad2touch**

Waydroid itself: <https://waydro.id> · docs: <https://docs.waydro.id>

Guide tested on Arch Linux (KDE/Wayland), Waydroid 1.6.3 with GAPPS, Xbox 360 pad, Pokémon UNITE
Revival 1.0.1. Your distro's paths may differ slightly — `/usr/lib/waydroid/...` and
`/var/lib/waydroid/...` are the two you'll touch most.
