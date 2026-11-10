#!/usr/bin/env python3
"""pad2touch — map a physical gamepad onto a virtual Android touchscreen.

Why: some Android games (e.g. Pokemon UNITE) are touch-only and ignore gamepads
entirely. Waydroid passes a controller through as a real joystick, which such a
game simply never reads. This daemon creates a *virtual touchscreen* with Linux
uinput, then translates the pad's stick and buttons into touch events at
configurable screen positions, so the game sees ordinary finger taps.

stdlib only. Run as root (needs /dev/uinput).

  pad2touch.py            run the mapper
  pad2touch.py --list     print the pad's axes/buttons and exit (debug)
"""

import fcntl
import os
import struct
import sys
import time

# ---------------------------------------------------------------- constants --
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0x00
BTN_TOUCH = 0x14A
ABS_MT_SLOT, ABS_MT_TOUCH_MAJOR, ABS_MT_POSITION_X, ABS_MT_POSITION_Y = 0x2F, 0x30, 0x35, 0x36
ABS_MT_PRESSURE = 0x3A
ABS_MT_TRACKING_ID = 0x39
ABS_X, ABS_Y, ABS_HAT0X, ABS_HAT0Y = 0x00, 0x01, 0x10, 0x11
ABS_RX, ABS_RY = 0x03, 0x04          # right stick -> camera pan
ABS_Z, ABS_RZ = 0x02, 0x05            # triggers: LT, RT

BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST = 0x130, 0x131, 0x133, 0x134
BTN_TL, BTN_TR, BTN_SELECT, BTN_START = 0x136, 0x137, 0x13A, 0x13B

UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045567
UI_SET_PROPBIT = 0x4004556E
UI_ABS_SETUP = 0x401C5504      # _IOW('U', 4, struct uinput_abs_setup)
UINPUT_ABS_SETUP = struct.Struct("<HHiiiiii")   # code, pad, value, min, max, fuzz, flat, res
INPUT_PROP_DIRECT = 0x01   # marks the node as a real touchscreen, not a touchpad
UI_DEV_SETUP = 0x405C5503

INPUT_EVENT = struct.Struct("<qqHHi")   # timeval, type, code, value  (64-bit)
UINPUT_SETUP = struct.Struct("<HHHH80sI")

CONF = "/etc/pad2touch.conf"
STATE = "/run/pad2touch.dev"
PAD_HINT = "/dev/waydroid-gamepad"
DEBUG = os.environ.get("PAD2TOUCH_DEBUG") == "1"


def log(msg):
    print(f"pad2touch: {msg}", flush=True)


# -------------------------------------------------------------------- config --
DEFAULTS = {
    # screen is 2560x1396 on this deck/desktop Waydroid image
    "width": 2560, "height": 1396,
    # left stick acts as a virtual joystick: touch at centre + direction*radius
    "move_cx": 300, "move_cy": 1080, "move_radius": 170, "deadzone": 0.20,
    # face buttons / shoulders / start, as screen coordinates
    "a_x": 2100, "a_y": 1130,
    "b_x": 1960, "b_y": 990,
    "x_x": 2240, "x_y": 990,
    "y_x": 2100, "y_y": 850,
    "lb_x": 2020, "lb_y": 740, "lb_w": 120, "lb_h": 70,
    "rb_x": 2280, "rb_y": 740, "rb_w": 120, "rb_h": 70,
    # right stick -> camera: a touch that starts in the camera zone and drags.
    # Default zone is open playfield, mid-screen; point it at the minimap if the
    # game only pans from there.
    "camera_cx": 1280, "camera_cy": 420,
    "camera_range": 220, "camera_deadzone": 0.25,
    # Unite Move and Recall are their own slots (the app writes these names
    # verbatim, so they must exist here or load_conf() silently drops them)
    "lt_x": 2370, "lt_y": 828,
    "recall_x": 2020, "recall_y": 1240,
    "start_x": 2430, "start_y": 120,
    "tap_ms": 90,
    # per-slot controller bindings: any key listed here survives load_conf()
    "bind_a": "A", "bind_b": "B", "bind_x": "X", "bind_y": "Y",
    "bind_lb": "LB", "bind_lt": "LT", "bind_recall": "BACK",          # how long a synthetic tap stays down
}


def load_conf():
    conf = dict(DEFAULTS)
    if os.path.exists(CONF):
        for line in open(CONF):
            line = line.split("#", 1)[0].strip()
            if "=" not in line:
                continue
            k, v = (s.strip() for s in line.split("=", 1))
            if k in conf:
                try:
                    # keep the default's type: bind_* are names ("RB"), not numbers,
                    # and forcing int()/float() silently discarded them
                    if isinstance(DEFAULTS[k], str):
                        conf[k] = v.upper()
                    else:
                        conf[k] = float(v) if "." in v else int(v)
                except ValueError:
                    log(f"ignoring bad value for {k}: {v!r}")
    return conf


# ------------------------------------------------------------------- uinput --
class Touchscreen:
    def __init__(self, width, height, name="Pad2Touch"):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        for ev in (EV_SYN, EV_KEY, EV_ABS):
            fcntl.ioctl(self.fd, UI_SET_EVBIT, ev)
        fcntl.ioctl(self.fd, UI_SET_KEYBIT, BTN_TOUCH)
        # ABS_X/ABS_Y are required: without them InputReader logs
        # "Touch device did not report support for X or Y axis" and treats
        # the node as a 1x1 mouse instead of a touchscreen.
        fcntl.ioctl(self.fd, UI_SET_PROPBIT, INPUT_PROP_DIRECT)
        for axis, (lo, hi) in {
            ABS_X: (0, width - 1),
            ABS_Y: (0, height - 1),
            ABS_MT_POSITION_X: (0, width - 1),
            ABS_MT_POSITION_Y: (0, height - 1),
            ABS_MT_SLOT: (0, 9),
            ABS_MT_TRACKING_ID: (0, 65535),
            ABS_MT_TOUCH_MAJOR: (0, 255),
            ABS_MT_PRESSURE: (0, 255),
        }.items():
            fcntl.ioctl(self.fd, UI_SET_ABSBIT, axis)
            # declare the real range: without this uinput reports min=max=0 and
            # Android maps the device to a 1x1 surface ("Device reconfigured: size 1x1")
            fcntl.ioctl(self.fd, UI_ABS_SETUP,
                        UINPUT_ABS_SETUP.pack(axis, 0, 0, lo, hi, 0, 0, 0))
        # device identity
        setup = UINPUT_SETUP.pack(0x06, 0x1, 0x1, 1, name.encode()[:79], 0)  # BUS_VIRTUAL
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        self.next_id = 1
        self.down = {}   # slot -> (x, y)

    def _emit(self, ev_type, code, value):
        now = time.monotonic()
        sec = int(now)
        usec = int((now - sec) * 1e6)
        os.write(self.fd, INPUT_EVENT.pack(sec, usec, ev_type, code, value))

    def _dbg(self, kind, slot, x=None, y=None):
        if not DEBUG:
            return
        # frames land in the journal in real order; a button press that is
        # followed by silence from slot 0 means the pad zeroed the stick
        ts_ms = int(time.time() * 1000) % 1000000
        extra = f" ({x:.0f},{y:.0f})" if x is not None else ""
        log(f"[{ts_ms}] {kind} slot={slot}{extra}")

    def sync(self):
        self._emit(EV_SYN, SYN_REPORT, 0)

    def touch(self, slot, x, y):
        self._emit(EV_ABS, ABS_MT_SLOT, slot)
        self._emit(EV_ABS, ABS_MT_TRACKING_ID, self.next_id)
        self.next_id = 1 if self.next_id >= 65535 else self.next_id + 1
        self._emit(EV_ABS, ABS_MT_POSITION_X, int(x))
        self._emit(EV_ABS, ABS_MT_POSITION_Y, int(y))
        self._emit(EV_ABS, ABS_X, int(x))
        self._emit(EV_ABS, ABS_Y, int(y))
        self._emit(EV_ABS, ABS_MT_TOUCH_MAJOR, 6)
        self._emit(EV_ABS, ABS_MT_PRESSURE, 200)
        self._emit(EV_KEY, BTN_TOUCH, 1)
        self.sync()
        self.down[slot] = (x, y)
        self._dbg("DOWN", slot, x, y)

    def move(self, slot, x, y):
        if slot not in self.down:
            return self.touch(slot, x, y)
        self._emit(EV_ABS, ABS_MT_SLOT, slot)
        self._emit(EV_ABS, ABS_MT_POSITION_X, int(x))
        self._emit(EV_ABS, ABS_MT_POSITION_Y, int(y))
        self._emit(EV_ABS, ABS_X, int(x))
        self._emit(EV_ABS, ABS_Y, int(y))
        self.sync()
        self.down[slot] = (x, y)
        self._dbg("MOVE", slot, x, y)

    def release(self, slot):
        if slot not in self.down:
            return
        self._emit(EV_ABS, ABS_MT_SLOT, slot)
        self._emit(EV_ABS, ABS_MT_TRACKING_ID, -1)
        del self.down[slot]
        if not self.down:
            self._emit(EV_KEY, BTN_TOUCH, 0)
        self.sync()
        self._dbg("UP", slot)

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)


def publish_node(name):
    """Record the created /dev/input/eventN so the container can be given it."""
    for entry in os.listdir("/sys/class/input"):
        if not entry.startswith("event"):
            continue
        try:
            with open(f"/sys/class/input/{entry}/device/name") as f:
                if f.read().strip() != name:
                    continue
            with open(f"/sys/class/input/{entry}/dev") as f:
                maj, minor = f.read().strip().split(":")
        except OSError:
            continue
        with open(STATE, "w") as f:
            f.write(f"/dev/input/{entry} {maj} {minor}\n")
        log(f"virtual touchscreen is {entry} ({maj}:{minor})")
        return f"/dev/input/{entry}"
    log("warning: could not locate the new input node in sysfs")
    return None


# --------------------------------------------------------------------- mapper --
def open_pad():
    path = PAD_HINT if os.path.exists(PAD_HINT) else None
    if path is None:
        for cand in os.listdir("/dev/input"):
            if cand.startswith("event"):
                try:
                    with open(f"/sys/class/input/{cand}/device/name") as f:
                        if "pad" in f.read().lower():
                            path = f"/dev/input/{cand}"
                            break
                except OSError:
                    pass
    if path is None:
        log("no gamepad found (/dev/waydroid-gamepad missing)")
        sys.exit(1)
    log(f"reading pad from {path}")
    return os.open(path, os.O_RDONLY | os.O_NONBLOCK)


EVIOCGABS = lambda code: (2 << 30) | (24 << 16) | (ord("E") << 8) | (0x40 + code)
EVIOCGKEY = lambda nbytes: (2 << 30) | (nbytes << 16) | (ord("E") << 8) | 0x18
ABSINFO = struct.Struct("<iiiiii")


def read_abs(fd, code):
    try:
        val, _min, _max, _fz, _fl, _res = ABSINFO.unpack(
            fcntl.ioctl(fd, EVIOCGABS(code), b"\0" * ABSINFO.size))
        return val
    except OSError:
        return None


def main():
    conf = load_conf()
    ts = Touchscreen(conf["width"], conf["height"])
    publish_node("Pad2Touch")
    pad = open_pad()

    stick = [0.0, 0.0]
    hat = [0.0, 0.0]
    moving = False
    last_move = None
    last_emit = 0.0
    engaged_at = 0.0
    center_since = 0.0
    last_resync = 0.0
    lt_held = False
    fast_reengage = False
    last_btn_at = 0.0
    last_key_at = 0.0
    keys_down = False
    # single-sample spike rejection for the axes (see set_axis)
    _pending = {}

    def set_axis(container, idx, raw):
        """Apply an axis sample unless it is a one-off spike.

        This pad jumps the stick by up to 2.0 in one report around a button
        press. Real movement is continuous, so a big jump is held back until a
        second sample confirms it (100 ms later) and otherwise discarded.
        """
        new_v = raw / 32767.0
        cur = container[idx]
        if abs(new_v - cur) > 0.5:
            key = (id(container), idx)
            p = _pending.get(key)
            if p is None or abs(p - new_v) > 0.5:
                _pending[key] = new_v
                return
            _pending.pop(key, None)
        container[idx] = new_v
    cam = [0.0, 0.0]
    cam_engaged = False
    cam_last = None
    cam_last_emit = 0.0
    cam_engaged_at = 0.0
    held = {}          # btn code -> slot
    # Which physical button drives which touch target is configurable
    # (bind_a / bind_lb / bind_rb / bind_x / bind_y / bind_select), so a user can
    # match the layout they are used to instead of editing this file.
    BIND_CODES = {"A": 0x130, "B": 0x131, "X": 0x133, "Y": 0x134,
                  "LB": 0x136, "RB": 0x137, "L2": 0x138, "R2": 0x139,
                  "BACK": 0x13A, "START": 0x13B}
    # Slot names are identical to the app's field names: what the app shows is
    # what this file holds is what this daemon presses. No renaming in between.
    BIND_DEFAULT = {"a": "A", "b": "B", "x": "X", "y": "Y",
                    "lb": "LB", "lt": "LT", "recall": "BACK"}
    # fixed MT slot per control. Slots are 0-9 ONLY: scanning for a free slot
    # could land on 10 and corrupt the whole multitouch stream, which showed up as
    # "after pressing a button nothing works at all".
    SLOT_MT = {"a": 1, "b": 2, "x": 3, "y": 4, "lb": 5, "lt": 6, "recall": 7}
    SLOT_KEYS = {"a": ("a_x", "a_y"), "b": ("b_x", "b_y"),
                 "x": ("x_x", "x_y"), "y": ("y_x", "y_y"),
                 "lb": ("lb_x", "lb_y"), "lt": ("lt_x", "lt_y"),
                 "recall": ("recall_x", "recall_y")}
    buttons = {}
    trig_slots = {}
    for _slot, _keys in SLOT_KEYS.items():
        _name = str(conf.get("bind_" + _slot, BIND_DEFAULT[_slot])).upper()
        if _name in ("LT", "RT"):
            trig_slots[_name] = _keys          # analog path (ABS_Z / ABS_RZ)
            # some pads report their triggers as digital buttons instead;
            # register both so a trigger binding works either way
            _tcode = BIND_CODES.get("L2" if _name == "LT" else "R2")
            if _tcode:
                buttons[_tcode] = (_keys[0], _keys[1], SLOT_MT[_slot])
            continue
        _code = BIND_CODES.get(_name)
        if _code:
            buttons[_code] = (_keys[0], _keys[1], SLOT_MT[_slot])
    log("bindings: " + ", ".join(
        "%s=%s(%s,%s)" % (str(conf.get("bind_" + sl, BIND_DEFAULT[sl])).upper(), sl,
                          conf.get(SLOT_KEYS[sl][0], "?"), conf.get(SLOT_KEYS[sl][1], "?"))
        for sl in SLOT_KEYS))
    log("running" + (" (debug)" if DEBUG else ""))
    try:
        while True:
            try:
                data = os.read(pad, INPUT_EVENT.size * 64)
            except BlockingIOError:
                # No new pad events. Do NOT skip the rest of the loop: the stick
                # state still has to be emitted, otherwise holding the stick
                # steady produces one tap at the centre and no drag at all.
                data = b""
                time.sleep(0.004)
            # resync from the kernel every ~100 ms: if the pad stops emitting
            # events we still know where the stick physically is
            if time.time() - last_resync >= 0.1:
                rx, ry = read_abs(pad, ABS_X), read_abs(pad, ABS_Y)
                crx, cry = read_abs(pad, ABS_RX), read_abs(pad, ABS_RY)
                if crx is not None:
                    set_axis(cam, 0, crx)
                if cry is not None:
                    set_axis(cam, 1, cry)
                try:
                    _ks = fcntl.ioctl(pad, EVIOCGKEY(96), b"\0" * 96)
                    keys_down = any((_ks[k // 8] >> (k % 8)) & 1 for k in BIND_CODES.values())
                except OSError:
                    keys_down = False
                if keys_down:
                    pass
                else:
                    for _c, _s in list(held.items()):
                        if isinstance(_c, int) and _c in BIND_CODES.values() and \
                                not ((_ks[_c // 8] >> (_c % 8)) & 1):
                            ts.release(_s)
                            held.pop(_c, None)
                if not keys_down and (time.time() - last_key_at) >= 0.15:
                    if rx is not None:
                        set_axis(stick, 0, rx)
                    if ry is not None:
                        set_axis(stick, 1, ry)
                last_resync = time.time()
            for off in range(0, len(data) - INPUT_EVENT.size + 1, INPUT_EVENT.size):
                _, _, etype, code, value = INPUT_EVENT.unpack_from(data, off)
                if etype != EV_ABS and etype != EV_KEY:
                    continue
                # This pad reports 0 on the stick axes around any button event;
                # that fake centre is what killed movement. Ignore near-zero
                # reports for a short window, but always honour real deflection.
                axis_ok = (not keys_down) and (time.time() - last_key_at) >= 0.15
                if code in (ABS_RX, ABS_RY):
                    if axis_ok:
                        set_axis(cam, 0 if code == ABS_RX else 1, value)
                elif code in (ABS_X, ABS_Y):
                    if axis_ok:
                        set_axis(stick, 0 if code == ABS_X else 1, value)
                elif code == ABS_HAT0X:
                    # d-pad keeps its own state: a button press makes many pads
                    # re-report the hat at 0,0, and sharing the variables wiped the
                    # analog stick value (movement died and only came back when the
                    # stick itself produced a new event).
                    hat[0] = float(value)
                elif code == ABS_HAT0Y:
                    hat[1] = float(value)
                elif etype == EV_KEY and code in buttons:
                    last_key_at = time.time()
                    if DEBUG:
                        log(f"btn {hex(code)} value={value} stick=({stick[0]:+.2f},{stick[1]:+.2f}) hat=({hat[0]:+.0f},{hat[1]:+.0f})")
                    kx, ky, mt = buttons[code]
                    if conf.get(kx, -1) < 0:          # button has no touch target
                        continue
                    if value:
                        last_btn_at = time.time()
                        if code in held:      # repeat event, already pressed
                            continue
                        for _c, _s in list(held.items()):
                            if _s == mt and isinstance(_c, int):
                                ts.release(mt)
                                held.pop(_c, None)
                        held[code] = mt
                        ts.touch(mt, conf[kx], conf[ky])
                    else:
                        slot = held.pop(code, None)
                        if slot is not None:
                            ts.release(slot)
                elif code in (ABS_Z, ABS_RZ):
                    # analog trigger acts as a button: >40% counts as pressed
                    which = "LT" if code == ABS_Z else "RT"
                    keys = trig_slots.get(which)
                    if keys is not None:
                        pressed = value > 100
                        tag = which + "_slot"
                        _tmt = keys[2] if len(keys) > 2 else 6
                        if pressed and tag not in held:
                            last_btn_at = time.time()
                            held[tag] = _tmt
                            ts.touch(_tmt, conf.get(keys[0], -1), conf.get(keys[1], -1))
                        elif not pressed and tag in held:
                            held.pop(tag, None)
                            ts.release(_tmt)
            # stick -> virtual joystick (one finger, slot 0)
            #
            # Games with a "floating" joystick treat the touch-down point as the
            # stick origin, so a finger that lands already displaced reads as a
            # single constant vector: the character lurches once and then cannot
            # be steered until release. Land on the centre first, then drag.
            vx = max(-1.0, min(1.0, stick[0] + hat[0]))
            vy = max(-1.0, min(1.0, stick[1] + hat[1]))
            mag = (vx ** 2 + vy ** 2) ** 0.5
            btn_down = bool(held)
            # Zeroed axes only count as "still holding" while a button event is
            # fresh: press, hold, and the ~1 s aftermath all keep the gesture.
            if mag > conf["deadzone"]:
                center_since = 0.0          # real deflection: never arm a release
                nx, ny = vx / mag, vy / mag
                scale = min(mag, 1.0)          # proportional, not always full tilt
                x = conf["move_cx"] + nx * conf["move_radius"] * scale
                y = conf["move_cy"] + ny * conf["move_radius"] * scale
                now = time.time()
                if not moving:
                    # land on the centre, and give the game a beat to register the
                    # touch-down before dragging: if down and drag arrive in the
                    # same frame the app can coalesce them into "finger started
                    # already offset", which reads as one lurch and no steering.
                    ts.touch(0, conf["move_cx"], conf["move_cy"])
                    moving = True
                    engaged_at = now
                    center_since = 0.0
                    last_move = None
                    last_emit = 0.0
                global_fast = fast_reengage
                drag_ready = global_fast or (now - engaged_at) >= 0.06
                fast_reengage = False
                # re-send periodically even when the position is unchanged: a
                # button press touches a different slot, and without a heartbeat
                # the game treats the stick as idle and stops movement until the
                # stick is moved again.
                if drag_ready and (last_move is None or now - last_emit >= 0.03
                                   or abs(x - last_move[0]) > 1 or abs(y - last_move[1]) > 1):
                    j = 1 if int(now * 10) & 1 else -1
                    ts.move(0, x + j, y - j)
                    last_move = (x, y)
                    last_emit = now
                    if DEBUG:
                        log(f"stick=({vx:+.2f},{vy:+.2f}) touch=({x:.0f},{y:.0f})")
            elif moving:
                # debounce: a button press can make cheap pads emit a single 0
                # on the stick axes. Releasing immediately killed movement until
                # the stick moved again, so wait for a sustained centre.
                if center_since == 0.0:
                    center_since = time.time()
                # 0.15 s was too eager: this pad reports centre for a few hundred
                # ms around every button event, and each bogus release forces the
                # game to re-grab the joystick (that reads as "can't move again").
                # 0.6 s costs nothing in feel but rides out the artefact.
                if (time.time() - center_since) >= 0.60:
                    ts.release(0)
                    # a release forced by the pad's axis artefact should re-engage
                    # instantly: no 60 ms landing pause on the way back
                    fast_reengage = (time.time() - last_key_at) < 1.0
                    moving = False
                    last_move = None
                    center_since = 0.0
                    if DEBUG:
                        log("stick released")
            # right stick -> camera pan (touch-drag inside the camera zone)
            cmag = (cam[0] ** 2 + cam[1] ** 2) ** 0.5
            if cmag > conf.get("camera_deadzone", 0.25):
                cnx, cny = cam[0] / cmag, cam[1] / cmag
                cscale = min(cmag, 1.0)
                cx = conf.get("camera_cx", 1280) + cnx * conf.get("camera_range", 220) * cscale
                cy = conf.get("camera_cy", 420) + cny * conf.get("camera_range", 220) * cscale
                cnow = time.time()
                if not cam_engaged:
                    ts.touch(9, conf.get("camera_cx", 1280), conf.get("camera_cy", 420))
                    cam_engaged = True
                    cam_last = None
                    cam_last_emit = 0.0
                    cam_engaged_at = cnow
                if cnow - cam_engaged_at >= 0.05 and (
                        cam_last is None or cnow - cam_last_emit >= 0.03
                        or abs(cx - cam_last[0]) > 1 or abs(cy - cam_last[1]) > 1):
                    ts.move(9, cx, cy)
                    cam_last = (cx, cy)
                    cam_last_emit = cnow
            elif cam_engaged:
                ts.release(9)
                cam_engaged = False
                cam_last = None

    except KeyboardInterrupt:
        pass
    finally:
        ts.close()
        try:
            os.unlink(STATE)
        except OSError:
            pass


if __name__ == "__main__":
    if "--list" in sys.argv:
        conf = load_conf()
        print("config:", conf)
        sys.exit(0)
    main()
