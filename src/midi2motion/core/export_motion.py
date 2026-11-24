"""export_motion.py: the inspector dataset (120 Hz, fullbody.finish + run2's extras) -> the player's compact motion file (schema verify.motion/1, 30 fps, int16 base64).
LIBRARY COPY of drum-benchmark/verify/export.py compact()/b64()/q() (unchanged), plus notes_of() (the source MIDI notes the player sounds, library schema 1.1 addition).
A motion file holds what the wrapped inspector reads to pose the android:
  names (the bones), delta  : per frame and bone the 3x4 bone delta, int16 base64: rotation x 32000, translation x 10000 (0.1 mm)
  sticks                    : per frame, hand L then R, butt xyz + tip xyz (m), int16 x 10000
  hat30, kick_plate, hat_plate : the hi-hat's openness (x 10000) and the two pedal boards (deg x 100), int16
  pen                       : whole-body penetration (mm, the frame's max over its four 120 Hz frames) x 10, int16
  collisions                : runs of frames over the 3 mm penetration limit, with the colliding pairs the checks named
  kit, chart, title         : the layout (pieces: id, c, n, r, depth, kind) and the chart
  notes (library, 1.1)      : [[t_s, row, velocity, zone], ...] the judged source notes, for the player's optional sound
"""
import base64, json, sys
import numpy as np
sys.dont_write_bytecode = True


def b64(a, dtype=np.int16):
    return base64.b64encode(np.ascontiguousarray(np.asarray(a), dtype=dtype).tobytes()).decode()


def q(a, s):
    return np.clip(np.round(np.asarray(a, float) * s), -32767, 32767)


def compact(D, key, title, audio=None):
    """the inspector dataset (fullbody.finish + run2's extras) -> the page's motion file"""
    ev = D["every"]; d = np.asarray(D["delta"], float); M, nb = d.shape[:2]; d = d.reshape(M, nb, 12); dq = np.empty_like(d)
    rot = [0, 1, 2, 4, 5, 6, 8, 9, 10]; tr = [3, 7, 11]; dq[..., rot] = q(d[..., rot], 32000); dq[..., tr] = q(d[..., tr], 10000)
    st = np.stack([np.concatenate([np.asarray(D["arms"][h]["stick"]["butt"], float)[::ev][:M], np.asarray(D["arms"][h]["stick"]["tip"], float)[::ev][:M]], 1) for h in "LR"], 1)
    pen120 = np.asarray(D["pen_mm"], float); N = len(pen120); pen = np.array([pen120[f * ev:f * ev + ev].max() if f * ev < N else 0.0 for f in range(M)])
    pairs = []
    for part in ("body", "arm L", "arm R"):
        r = D["checks"].get(f"C-COL-1 {part}") or {}
        for k, v in (r.get("pairs") or {}).items(): pairs.append(dict(pair=k if part == "body" else f"{k} ({part})", frames=v.get("frames"), max_mm=v.get("max_mm"), first=(v["first"] // ev) if v.get("first") is not None else None))
    over = pen > 3.0; runs = []; f = 0
    while f < M:
        if over[f]:
            g = f
            while g + 1 < M and over[g + 1]: g += 1
            near = [p["pair"] for p in pairs if p["first"] is not None and f - 2 <= p["first"] <= g + 2]
            runs.append(dict(f0=f, f1=g, max_mm=round(float(pen[f:g + 1].max()), 1), pairs=near or [p["pair"] for p in pairs])); f = g + 1
        else: f += 1
    pd = D["pedals"]; k = D["kit"]
    return dict(schema="verify.motion/1", key=key, title=title, fps=30, frames=M, names=D["names"], delta=b64(dq), sticks=b64(q(st, 10000)), hat30=b64(q(np.asarray(D["hat30"], float)[:M], 10000)),
                kick_plate=b64(q(np.asarray(pd["kick_plate"], float)[::ev][:M], 100)), hat_plate=b64(q(np.asarray(pd["hat_plate"], float)[::ev][:M], 100)), kick_foot=pd.get("kick_foot"), hat_foot=pd.get("hat_foot"),
                pen=b64(q(pen, 10)), collisions=runs, collision_pairs=pairs, kit=k, chart=D.get("chart"), audio=audio, preset=(D.get("layout") or {}).get("preset"))


def notes_of(J):
    """the judged source MIDI notes of a judgement -> [[t, row, vel, zone]] (the player plays these when its sound is on)"""
    return [[round(s["t"], 4), s["row"], s.get("vel"), s.get("zone")] for s in J["source"] if s.get("judged")]
