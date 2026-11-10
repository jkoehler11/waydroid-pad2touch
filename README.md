# pad2touch + Unite Mapper — gamepad on touch-only Android games in Waydroid

Give a physical controller to an Android game that has no controller support, running in Waydroid.

**Unite Mapper** is a small Android app that owns the data: the screen position of every control and
which controller button fires it — with a tap-to-capture overlay so you never guess pixels.
**pad2touch** is a host daemon that reads the gamepad and produces a real multitouch device positioned
at those coordinates.

```
   gamepad (/dev/input/eventN)
        │  udev symlink
        ▼
  /dev/waydroid-gamepad ──► pad2touch (host, root, uinput)
                                  │
                                  ▼
                     Pad2Touch virtual touchscreen
                                  │  node injected into the container
                                  ▼
                   /dev/input/event21 ──► Android ──► the game sees a finger

  Unite Mapper (app) ──► unite_profile.json ──► unite-profile-sync (host, every 20 s)
                                                    │
                                                    ▼
                                          /etc/pad2touch.conf ──► pad2touch
```

## Why the split

An Android app **cannot** read a controller while another app holds focus without root or a paired
wireless-debug session — which is why every Play Store overlay mapper makes you enable wireless
debugging. Waydroid's GAPPS image has no Wi-Fi interface at all (`svc wifi enable` leaves *Wi-Fi is
disabled*, and `adb_wifi_enabled` resets to `0`), so that route is closed.

The app therefore owns what a UI is good for (coordinates, bindings, capture) and the host owns the
input, where reading `/dev/input/*` and creating a touchscreen need no Android permissions at all.

## What's in here

| Path | What it is |
|---|---|
| `app/` | **Unite Mapper** source — `MainActivity.java` (form, bindings, capture button), `CaptureService.java` (overlay), `build.sh` (SDK only: no Gradle, no AndroidX, no network). |
| `apk/UniteMapper.apk` | Pre-built app (~20 KB). `waydroid app install apk/UniteMapper.apk`. |
| `pad2touch.py` | The mapper: virtual touchscreen, pad reading, button→touch translation. stdlib only, root. |
| `pad2touch.conf.example` | Config reference (the app normally writes this for you). |
| `host/unite-profile-sync` | Pulls the app's profile over adb, rewrites `/etc/pad2touch.conf`, restarts the daemon, re-injects the device. |
| `host/waydroid-adb-connect` | Keeps a host→container adb link, re-established on each Waydroid start. |
| `waydroid-host-fix.sh` | Host fixes: Docker's `FORWARD DROP` killing container internet, and gamepad passthrough. `check` / `fix` / `uninstall`. |
| `systemd/`, `udev/` | Units and rules, if you prefer installing by hand. |
| `docs/waydroid-unite-mapper-guide.md` | **Full shareable guide** — Waydroid install per distro, controller, app setup, troubleshooting. HTML rendering alongside it. |
| `docs/waydroid-no-internet-docker-fix.md` | The networking bug, explained for sharing. |
| `docs/steamdeck-waydroid-guide.md` | Steam Deck walkthrough. |

## Quick start

Assumes Waydroid is already running and you can play the game with a mouse. Four steps.

```bash
# 1 — host fixes: container internet (Docker's FORWARD DROP) + gamepad passthrough
sudo ./waydroid-host-fix.sh check
sudo ./waydroid-host-fix.sh fix

# 2 — the mapper daemon
sudo install -m 755 pad2touch.py /usr/local/bin/pad2touch.py
sudo install -m 755 pad2touch-inject /usr/local/bin/pad2touch-inject
sudo cp pad2touch.conf.example /etc/pad2touch.conf
sudo cp systemd/pad2touch.service systemd/pad2touch-inject.service /etc/systemd/system/
sudo cp udev/99-waydroid-touch-trigger.rules /etc/udev/rules.d/
sudo systemctl daemon-reload && sudo udevadm control --reload-rules
sudo systemctl enable --now pad2touch.service
sudo systemctl start pad2touch-inject.service

# 3 — the app, and the host half that feeds it
waydroid app install apk/UniteMapper.apk
waydroid shell "appops set com.koehler.unitemapper SYSTEM_ALERT_WINDOW allow"
sudo install -m 755 host/unite-profile-sync /usr/local/bin/
sudo cp systemd/unite-profile-sync.service systemd/unite-profile-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now unite-profile-sync.timer
```

4 — open **Unite Mapper** in Waydroid, press **Capture coordinates by tapping the game**, and tap
the nine controls as the bar names them. It saves; the host applies it within ~20 seconds.

Verify at any point:

```bash
# Android sees the virtual touchscreen and the pad
waydroid shell "dumpsys input" | grep -A2 Pad2Touch
waydroid shell "dumpsys input" | grep -i "x-box"

# the daemon is up and resolved the config you expect
systemctl is-active pad2touch.service
journalctl -u pad2touch.service -n 6 --no-pager | grep bindings
```

## The app

### Rows

One row per control — **Basic attack, Move 1, Move 2, Battle item, Score, Unite Move, Recall /
teleport to base, Movement stick centre, Camera area** — each with an X and Y field, a stick radius,
and a dropdown for the controller button.

### Capture

`Capture coordinates by tapping the game` starts a nearly transparent overlay over the running game
(the game keeps running; taps are swallowed so nothing is cast) and prompts for nine taps:

`Basic attack → Move 1 → Move 2 → Battle item → Score → Unite Move → Recall → joystick centre → camera area`

Cancel with the bottom-left corner. The ninth tap saves automatically.

### Bindings

The dropdowns offer `none, A, B, X, Y, LB, RB, LT, RT, START, BACK`. `none` disables that control.
**Apply default button mappings** resets only the dropdowns; **Load measured defaults** resets
coordinates *and* bindings, so avoid it once you've captured.

Shipped defaults (Switch-style):

| Row | Default button |
|---|---|
| Basic attack | B |
| Move 1 | RB |
| Move 2 | RT |
| Battle item | X |
| Score | Y |
| Unite Move | LT |
| Recall | BACK |

Coordinates are **1:1 with the config**: the app's keys are `a, b, x, y, lb, lt, recall`, the file
holds `a_x/a_y … recall_x/recall_y`, and the daemon binds `bind_<same name>`. There is no renaming
layer between what you type and what gets pressed.

### Default coordinates

Measured on a 2560×1366 surface, in case you want to start from them:

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

Everything here is game- and resolution-specific. The coordinates are absolute pixels: resize the
Waydroid window and they need re-capturing (the touch device is rebuilt to the new size
automatically; the numbers are not).

## How the mapping behaves

- **Land, then drag.** A floating joystick treats the touch-down point as its origin, so a finger that
  appears already displaced reads as one lurch and no steering. The mapper lands at the stick centre
  and drags outward.
- **Proportional throw.** Half tilt creeps, full tilt runs — the radius scales with stick magnitude.
  Shrinking the radius to fix overshoot is a trap: too small and full deflection falls inside the
  game's deadzone, which reads as "movement stopped working".
- **Heartbeat.** Stick position is re-sent every ~30 ms even when unchanged, because a button press
  occupies another finger and an idle stick makes the game drop the gesture.
- **Spike rejection.** Cheap pads report garbage axes on button edges (measured on a 360 pad: a steady
  `+1.00,+0.10` dropping to `-0.04,-0.09` in one sample). Samples that jump more than 0.5 are held
  back until the next sample confirms them (~100 ms), so movement survives button presses.
- **Fixed multitouch slots.** Controls own slots `a=1 b=2 x=3 y=4 lb=5 lt=6 recall=7`, stick on 0,
  camera on 9. Multitouch slots only go up to 9 — an allocator that scans for a free slot can run
  past it and corrupt the whole touch stream, which looks like "after pressing a button nothing works".

## Config reference

`/etc/pad2touch.conf`, generated by the sync script:

```ini
width = 2560            height = 1366          # must match the live surface
move_cx = 410           move_cy = 1048         # stick centre
move_radius = 120       deadzone = 0.18
a_x = 2428              a_y = 1228             # …one pair per control
camera_cx = 1280        camera_cy = 420
camera_range = 220      camera_deadzone = 0.25
bind_a = B              bind_recall = BACK     # controller button per control
```

After editing by hand:

```bash
sudo systemctl restart pad2touch.service
sudo /usr/local/bin/pad2touch-inject    # required: a restart creates a new device node
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Nothing responds after a button press | More than 9 MT slots in use | Update — slots are fixed per control now |
| Movement stops on button press, or continues after release | Pad emits axis spikes on button edges | Handled by spike rejection; don't add axis gating — it freezes the stick |
| 1–2 s freezes, repeatedly | Daemon crash-looping; each restart re-registers the device | Check for tracebacks (below) before anything else |
| Bindings seem ignored | Config parser dropped unknown/non-numeric keys | Compare the startup `bindings:` line with the conf |
| Works in menus, nothing in game | Coordinates are absolute pixels and slightly off | Re-capture |
| Capture opens the home screen | Launcher activity is a downloader, not the game | Use this app, which targets the game activity directly |
| App can't save: "permission denied" | Profile owned by `shell` (e.g. copied with `adb push`) | Save again — the app unlinks and retries; see below |
| Container has no internet | Docker's `FORWARD DROP` | `sudo ./waydroid-host-fix.sh fix` |

```bash
# crash-looping? any output here is the real problem
journalctl -u pad2touch.service --since "-15min" | grep -c Traceback

# what mapping did it actually resolve?
journalctl -u pad2touch.service -n 6 --no-pager | grep bindings
```

**Never `adb push` into the app's own files directory.** It writes as `shell`, so
`Android/data/com.koehler.unitemapper/files/unite_profile.json` ends up owned by uid 2000 and the app
gets `EACCES`. Seed a profile from the app instead; if you must, fix ownership from inside the
container namespace (Waydroid's `data/media` is not visible from the host):

```bash
PID=$(pgrep -x -f "/system/bin/init second_stage")
sudo nsenter -t "$PID" -m -p --root --wd -- /system/bin/sh -c \
  'chown -R 10156:1078 /data/media/0/Android/data/com.koehler.unitemapper/files'
```

## Notes on the virtual device

Getting Android to treat a uinput node as a touchscreen needs three things — each has its own logcat
signature (`adb logcat -d | grep -i pad2touch`):

| Logcat | Meaning | Fix |
|---|---|---|
| `sources=MOUSE` | Treated as a touchpad | `INPUT_PROP_DIRECT` via `UI_SET_PROPBIT` |
| `did not report support for X or Y axis` | Only `ABS_MT_*` declared | also declare `ABS_X` / `ABS_Y` |
| `Device reconfigured: … size 1x1` | Axes report `min=max=0` | `UI_ABS_SETUP` with real ranges |

Injecting the node into the container has two traps:

- `mknod -m 666` in **one** step — EventHub reacts to `IN_CREATE` and a later `chmod` loses the race.
- The device cgroup must allow it (`lxc.cgroup2.devices.allow = a` in
  `/var/lib/waydroid/lxc/waydroid/config`), or Android gets `EPERM`.

## Building the app

```bash
cd app && ./build.sh          # uses $ANDROID_HOME, $ANDROID_SDK_ROOT or ~/android-sdk
```

aapt2 → javac `--release 11` → d8 → zipalign → apksigner. The script keeps its keystore at
`~/.unite-mapper-debug.keystore`; a fresh key per build makes updates fail with
`INSTALL_FAILED_UPDATE_INCOMPATIBLE`.

## Caveats

- Linux + Waydroid only. Nothing here runs on a real phone (an app there would need root or ADB).
- Root on the host for `/dev/uinput` and the container injection.
- A heuristic, not an input driver: analog triggers are thresholded and rapid tap-chains are not
  frame-perfect.
- Screenshots via `adb screencap` cost ~1.5 s, so they can't measure input timing — use the daemon's
  debug log (`PAD2TOUCH_DEBUG=1` in a systemd drop-in) for that.

MIT licensed. Full guide: [`docs/waydroid-unite-mapper-guide.md`](docs/waydroid-unite-mapper-guide.md)
