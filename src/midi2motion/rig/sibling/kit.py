#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-android-drums/tools/kit.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""kit.py: the drum kit as numbers (one source for the solver, Blender and the inspector) and the note map.

Character space = world: the android sits at the origin on a throne, facing -Y, +X = its left, Z up, metres.
A right-handed five-piece-plus kit, real sizes (inches -> metres), simple cylinders and discs:
  kick 22x16 with a pedal and beater (right foot), snare 14x5.5, hi-hat 14 with a pedal (left foot) and two cymbals that close,
  tom1 10, tom2 12 (on the kick), tom3 13 (low rack, right), floor tom 16, crash 16 (left front), ride 20 with a bell zone (right).

A piece: id, kind (drum | cymbal | kick), c = centre of the playing surface, n = its unit normal, r, depth (shell depth or cymbal thickness).
"""
import math
import numpy as np

def _n(v): v = np.asarray(v, float); return v / np.linalg.norm(v)
def tilt(toward, deg):
    """a normal tilted `deg` from vertical toward the horizontal direction `toward` (x, y)"""
    t = _n([toward[0], toward[1], 0.0]); a = math.radians(deg); return t * math.sin(a) + np.array([0, 0, math.cos(a)])

SEAT_Z, SEAT_Y = 0.475, -0.07       # throne top, and its centre under the pelvis (the hips pitch forward)
ROOT = (0.0, 0.0, -0.36)            # the android's hips drop from standing (0.95) to seated
STICK_L, STICK_R, GRIP_DROP = 0.40, 0.007, 0.030          # stick length from the wrist to the tip, radius, how far the stick sits under the wrist (palm side)
ANKLE = {"R": np.array([-0.26, -0.45, 0.105]), "L": np.array([0.36, -0.42, 0.105])}

PIECES = [
    dict(id="kick",  kind="kick",   c=(-0.26, -0.74, 0.285), n=(0, 1, 0),                 r=0.280, depth=0.40, col=(0.10, 0.11, 0.16)),
    dict(id="snare", kind="drum",   c=(0.04, -0.57, 0.665),  n=(0, 0, 1),                 r=0.178, depth=0.12, col=(0.72, 0.74, 0.78)),
    dict(id="tom1",  kind="drum",   c=(-0.06, -0.90, 0.840), n=tuple(tilt((0, 1), 20)),   r=0.127, depth=0.19, col=(0.16, 0.18, 0.40)),
    dict(id="tom2",  kind="drum",   c=(-0.38, -0.90, 0.840), n=tuple(tilt((0, 1), 20)),   r=0.152, depth=0.21, col=(0.16, 0.18, 0.40)),
    dict(id="tom3",  kind="drum",   c=(-0.70, -0.84, 0.790), n=tuple(tilt((0.7, 0.7), 14)), r=0.165, depth=0.24, col=(0.16, 0.18, 0.40)),
    dict(id="floor", kind="drum",   c=(-0.66, -0.42, 0.640), n=(0, 0, 1),                 r=0.203, depth=0.40, col=(0.16, 0.18, 0.40)),
    dict(id="hat",   kind="cymbal", c=(0.43, -0.66, 0.900),  n=(0, 0, 1),                 r=0.178, depth=0.012, col=(0.80, 0.66, 0.30)),
    dict(id="crash", kind="cymbal", c=(0.30, -0.90, 1.140),  n=tuple(tilt((-0.3, 1), 12)), r=0.203, depth=0.010, col=(0.80, 0.66, 0.30)),
    dict(id="ride",  kind="cymbal", c=(-0.84, -0.46, 0.990), n=tuple(tilt((1, 0.45), 16)), r=0.254, depth=0.012, col=(0.80, 0.66, 0.30)),
]
P = {p["id"]: p for p in PIECES}
for p in PIECES: p["c"] = np.array(p["c"], float); p["n"] = _n(p["n"])
BELL_R, BELL_H = 0.055, 0.030       # the ride's bell: radius and dome height
HAT_GAP_OPEN, HAT_GAP_CLOSED = 0.026, 0.003

# ---- the note map (the author's drum MIDI notes; GM-like). zone = (piece, where on it). None = sounds, is not played by a limb (R-401)
NOTE_MAP = {
    36: ("kick", "beater", "RF"), 44: ("hat", "pedal", "LF"),
    38: ("snare", "head", "hand"), 40: ("snare", "rimshot", "hand"), 37: ("snare", "cross", "hand"),
    42: ("hat", "closed", "hand"), 46: ("hat", "open", "hand"),
    50: ("tom1", "head", "hand"), 48: ("tom1", "head", "hand"), 47: ("tom2", "head", "hand"), 45: ("tom3", "head", "hand"),
    43: ("floor", "head", "hand"), 41: ("floor", "head", "hand"),
    49: ("crash", "edge", "hand"), 57: ("crash", "edge", "hand"), 51: ("ride", "bow", "hand"), 53: ("ride", "bell", "hand"),
    39: None,   # clap: a layer, out of the motion
}
NAMES = {36: "kick", 37: "side stick", 38: "snare", 39: "clap", 40: "snare rim", 41: "floor tom (41)", 43: "floor tom (43)", 45: "tom 3 (45)", 47: "tom 2 (47)", 48: "tom 1 (48)", 50: "tom 1 (50)",
         42: "hat closed", 44: "hat pedal", 46: "hat open", 49: "crash", 51: "ride", 53: "ride bell"}
Q = {"head": 0.38, "rimshot": 0.70, "cross": 0.05, "closed": 0.72, "open": 0.72, "edge": 0.86, "bow": 0.55, "bell": 0.0}   # how far from the centre toward the player a zone is struck (x radius)

SHOULDER = {"L": np.array([0.175, 0.0, 1.385 + ROOT[2]]), "R": np.array([-0.175, 0.0, 1.385 + ROOT[2]])}


def plane_basis(p):
    n = p["n"]; a = np.cross(n, (1.0, 0, 0)); a = _n(a) if np.linalg.norm(a) > 1e-6 else np.array([0, 1.0, 0]); return a, np.cross(n, a)


def toward(p, target):
    """unit vector in the piece's surface plane pointing from its centre toward `target`"""
    v = np.asarray(target, float) - p["c"]; v = v - p["n"] * (v @ p["n"]); return _n(v)


def strike_point(piece, zone, hand, gap=0.0):
    p = P[piece]; u = toward(p, SHOULDER[hand] + np.array([0, -0.25, 0])); s = p["c"] + u * (Q[zone] * p["r"])
    if piece == "floor" or piece == "snare":            # two hands on one drum never share a spot
        a, b = plane_basis(p); side = np.cross(p["n"], u); s = s + side * (0.035 if hand == "R" else -0.035) * (1 if zone != "cross" else 0)
    if zone == "bell": s = s + p["n"] * BELL_H
    if piece == "hat": s = s + p["n"] * (0.012 + gap)   # the top cymbal's upper face
    return s


def solids():
    """collision volumes: (id, top centre, normal, radius, depth); drums are cylinders under their head, cymbals thin discs, the kick lies on its side"""
    out = []
    for p in PIECES:
        if p["kind"] == "kick": out.append((p["id"], p["c"], -p["n"] * 1.0, p["r"], p["depth"]))        # the batter head faces +Y; the shell runs to -Y, so its 'top' is the batter and it extends along -n... stored as n pointing OUT of the batter
        else: out.append((p["id"], p["c"], p["n"], p["r"], p["depth"]))
    out[0] = ("kick", P["kick"]["c"], P["kick"]["n"], P["kick"]["r"], P["kick"]["depth"])
    return out


def surfaces():
    """tops the wrists and forearms must stay above (rig.py's surface callables: (x, y) -> top z or None): the drum heads"""
    fs = []
    for p in PIECES:
        if p["kind"] != "drum": continue
        def top(x, y, p=p):
            d = np.array([x, y]) - p["c"][:2]
            if d @ d > (p["r"] + 0.01) ** 2: return None
            return float(p["c"][2] - (p["n"][0] * d[0] + p["n"][1] * d[1]) / p["n"][2])
        fs.append(top)
    return fs


def export():
    return dict(pieces=[dict(id=p["id"], kind=p["kind"], c=[round(float(v), 4) for v in p["c"]], n=[round(float(v), 4) for v in p["n"]], r=p["r"], depth=p["depth"], col=p["col"]) for p in PIECES],
                bell=dict(r=BELL_R, h=BELL_H), seat_z=SEAT_Z, seat_y=SEAT_Y, stick=dict(l=STICK_L, r=STICK_R, drop=GRIP_DROP), ankle={k: [float(x) for x in v] for k, v in ANKLE.items()},
                hat_gap=[HAT_GAP_CLOSED, HAT_GAP_OPEN])
