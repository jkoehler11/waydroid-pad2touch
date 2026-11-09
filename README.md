# pad2touch — use a gamepad with touch-only Android games in Waydroid

A virtual touchscreen for Waydroid, driven by a physical controller.

Waydroid forwards keyboard and pointer from the host, and it will happily pass a controller
through as a real joystick — but an Android game that only reads touches never looks at it.
Pokémon UNITE is one of those: the mobile client has no controller settings at all.

`pad2touch` creates a **real multitouch device** with Linux `uinput`, named `Pad2Touch`, and
translates stick and button input into touch events at configurable screen positions. The game
cannot tell the difference from a finger.

```
gamepad ──► pad2touch ──► /dev/uinput (Pad2Touch) ──► injected into Waydroid ──► game sees touches
```

---

## What's in here

| Path | What it is |
|---|---|
| `pad2touch.py` | The mapper. Creates the virtual touchscreen, reads the pad, emits touches. stdlib only, runs as root. |
| `pad2touch.conf.example` | Config: joystick centre/radius and a screen position for every button. |
| `waydroid-host-fix.sh` | Fixes the two host problems that make Waydroid look broken: Docker's `FORWARD DROP` killing the container's internet, and gamepad injection. `check` / `fix` / `uninstall`. |
| `docs/waydroid-no-internet-docker-fix.md` | Write-up of the networking bug, for sharing. |
| `docs/steamdeck-waydroid-guide.md` | End-to-end Steam Deck walkthrough: installing Waydroid, installing a game, the networking fix, and this controller mapping. |
| `systemd/`, `udev/` | Unit and rule files, if you'd rather install by hand than run the script. |

---

## Quick start (Arch/KDE host with Waydroid already working)

```bash
# 1. host fixes: container internet (Docker) + gamepad visibility
sudo ./waydroid-host-fix.sh check
sudo ./waydroid-host-fix.sh fix

# 2. the touch mapper
sudo install -m 755 pad2touch.py /usr/local/bin/pad2touch.py
sudo cp pad2touch.conf.example /etc/pad2touch.conf
sudo cp systemd/pad2touch.service systemd/pad2touch-inject.service /etc/systemd/system/
sudo cp udev/99-waydroid-touch-trigger.rules /etc/udev/rules.d/
sudo systemctl daemon-reload && sudo udevadm control --reload-rules
sudo systemctl enable --now pad2touch.service
sudo systemctl start pad2touch-inject.service
```

Verify inside the container — you want a device with `TOUCHSCREEN` sources and a real size:

```bash
waydroid adb connect
adb -s 192.168.240.112:5555 shell dumpsys input | grep -A3 Pad2Touch
# size 2560x1396, orientation 0, mode 1, sources=TOUCHSCREEN | STYLUS
```

Then edit `/etc/pad2touch.conf` and `sudo systemctl restart pad2touch`.

---

## Three things that will bite you

Getting a uinput touchscreen recognised by Android needs all three. Each failure has its own
logcat signature, so check `adb logcat -d | grep -i pad2touch`:

| Logcat | Meaning | Fix |
|---|---|---|
| `sources=MOUSE` | Treated as a touchpad. Menus accept clicks, games ignore them. | set `INPUT_PROP_DIRECT` (`UI_SET_PROPBIT`) |
| `Touch device ... did not report support for X or Y axis` | Only `ABS_MT_*` axes declared | also declare `ABS_X` / `ABS_Y` |
| `Device reconfigured: ... size 1x1` | Axes report `min=max=0` | send `UI_ABS_SETUP` with real ranges per axis |

Injecting the device node into the container has two traps of its own:

- Use `mknod -m 666` in **one** step. Android's EventHub reacts to `IN_CREATE` and opens the node
  immediately; a `chmod` afterwards loses the race and the device stays invisible.
- The container's device cgroup must allow it: `lxc.cgroup2.devices.allow = a` in
  `/var/lib/waydroid/lxc/waydroid/config`, or Android gets `EPERM`.

---

## Calibrate against the real screen, don't guess

Screenshot a moment where the controls are visible, then read the pixel positions of the
joystick and buttons off it:

```bash
adb -s 192.168.240.112:5555 shell screencap -p /sdcard/hud.png
adb -s 192.168.240.112:5555 pull /sdcard/hud.png .
```

Guessed coordinates produce the maddening "works in the menu, does nothing in game" symptom,
because the touches land on empty screen. Two behaviours worth knowing once you have real numbers:

- **Floating joysticks use the touch-down point as the origin.** The mapper lands a finger at the
  stick centre, then drags outward — a finger that *appears* already displaced reads as a single
  lurch and no steering.
- **Movement while pressing buttons** needs the stick state emitted continuously (a ~30 ms
  heartbeat), not only when the pad reports a change. A pad with no new events must still move
  the finger.

---

## The video gamepad layout shipped as the example

The example config uses the Nintendo Switch layout for Pokémon UNITE:

| Input | Action | Touch target |
|---|---|---|
| Left stick | Move | joystick centre (410, 1048), r 120 |
| A | Basic attack | (2428, 1228) |
| B | Cancel move — no touch equivalent | disabled |
| X | Score | (1638, 1218) |
| Y | Battle items | (2164, 1265) |
| LB | Move 1 | (2167, 1011) |
| RB | Move 2 | (1996, 1224) |
| LT | Unite Move | (2370, 828) |
| Right stick | Camera pan | drag inside `camera_cx/camera_cy` zone |

Coordinates are for a 2560×1396 Waydroid surface. Every one of them is game- and
resolution-specific — recalibrate for anything else.

---

## Caveats

- Linux only, Waydroid only. Nothing here is Android-side.
- Requires root (opens `/dev/uinput`, injects device nodes into the container).
- The mapper is a heuristic, not an input driver: it cannot emulate rapid tap-chains perfectly,
  and analog triggers are thresholded.
- `waydroid-host-fix.sh uninstall` removes what it added; the running container keeps its device
  nodes until restarted.

MIT licensed.
