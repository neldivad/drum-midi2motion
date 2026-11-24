#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/drums2/kitdata.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""kitdata.py: drumkit.yaml -> ONE kit object for the chart, the planner, the checks, the inspector and the Blender scene (R-418: the kit is data).

    K = kitdata.load("standard")        # a preset of drumkit.yaml

The kit object IS the sibling drum lab's kit.py, loaded by path into a fresh module (never edited, never the shared `kit` module) with its tables replaced in memory
by this layout's: PIECES, P, NOTE_MAP, NAMES, Q, SHOULDER, ANKLE, SEAT_*, ROOT. Its own functions (toward, plane_basis, surfaces) then read the layout. Replaced here,
because the sibling's versions name pieces: strike_point (the two-hand offset was `floor or snare`), solids (the kick was `PIECES[0]`), export.

DERIVED, not typed (what R-418's audit found hard-coded):
  SHOULDER   the body rig's shoulders at the seated neutral posture (body_rig.Body, rig.yaml seated_neutral), not kit.py's constants
  PEDALS     a pedal given as `azimuth_deg` stands where that leg's foot falls: hip + thigh (splayed by the azimuth, sloping down to a knee that sits one shin above the
             ankle) + a shin leaning shin_fwd_deg forward. A piece placed `from_pedal` follows its pedal (the kick stands where the kick foot falls)
  FOOT_OF    which foot plays a pedal = the leg on the pedal's side of the pelvis (kick -> RF and hat -> LF fall out of the standard layout; a mirror swaps them)
  ANKLE      per FOOT, from the pedals
  PREF       hand preference per piece: how much farther the strike point is from this hand's shoulder than the other's + the piece's role against the lead hand
  GRIP       per hand, from the performer's {lead, weak} pair
A preset may be `mirror: <preset>` (x -> -x, lead hand swapped), may `add:` pieces from the library with a place, and may remap notes.
"""
import copy, importlib.util, json, math, pathlib, sys
sys.dont_write_bytecode = True
import numpy as np, yaml
HERE = pathlib.Path(__file__).resolve().parent; LAB = HERE.parent / "data"; DRUMS = HERE.parent / "sibling"      # midi2motion: package data and the packaged sibling modules
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
import arm_rig as AR, body_rig as BR

Z = np.array([0, 0, 1.0])
def _n(v): v = np.asarray(v, float); return v / np.linalg.norm(v)
def tilt(toward, deg):
    t = np.array([toward[0], toward[1], 0.0]); a = math.radians(deg)
    return Z.copy() if np.linalg.norm(t) < 1e-9 or abs(deg) < 1e-9 else _n(t) * math.sin(a) + Z * math.cos(a)


def performer(perf):
    """the body's own numbers at the seated neutral posture -> shoulders, hips, leg lengths"""
    root = np.array(perf["root"], float); b = BR.Body(True, root); ne = b.neutral; z = np.zeros(1)
    T = b.trunk(dict(lean=np.array([ne["lean"]]), side=np.array([ne["side"]]), turn=np.array([ne["turn"]]), shift=np.zeros((1, 3)), nod=z, tilt=z, look=z))["T"]
    return dict(body=b, shoulder={h: BR.pt(T["chest"], AR.HEAD[f"upper_arm.{h}"])[0] for h in "LR"}, hip={s: BR.pt(T["hips"], AR.HEAD[f"thigh.{s}"])[0] for s in "LR"}, thigh=b.L1, shin=b.L2, arm=AR.L_ARM)


def pedal_place(pf, perf, az_deg):
    """where a foot falls: the ankle of the leg on the azimuth's side (+ = the performer's left), thigh splayed by |azimuth|, the knee one shin above the ankle, the shin leaning forward"""
    s = "L" if az_deg > 0 else "R"; sg = 1.0 if s == "L" else -1.0; H = pf["hip"][s]; L1, L2 = pf["thigh"], pf["shin"]; be = math.radians(perf["legs"]["shin_fwd_deg"]); az = math.radians(abs(az_deg)); az_ = perf["legs"]["ankle_z"]
    sphi = (H[2] - az_ - L2 * math.cos(be)) / L1; cphi = math.sqrt(1 - sphi * sphi)
    knee = H + L1 * np.array([sg * math.sin(az) * cphi, -math.cos(az) * cphi, -sphi]); ankle = knee + L2 * np.array([sg * math.sin(az) * math.sin(be), -math.cos(az) * math.sin(be), -math.cos(be)])
    return s, ankle, dict(thigh_slope_deg=round(math.degrees(math.asin(sphi)), 1), knee_angle_deg=round(90 + math.degrees(be) - math.degrees(math.asin(sphi)), 1))


def resolve(name, Y=None):
    """a preset with mirror / add / note_map applied -> (pieces [dict], note_map, performer dict, meta)"""
    Y = Y or yaml.safe_load(open(LAB / "drumkit.yaml")); pr = Y["presets"][name]; perf = copy.deepcopy(Y["performer"]); nm = {int(k): v for k, v in Y["note_map"].items()}
    if "mirror" in pr:
        pieces, nm0, perf0, _ = resolve(pr["mirror"], Y); pieces = copy.deepcopy(pieces); nm = nm0; perf = perf0
        for p in pieces:
            if isinstance(p.get("c"), list): p["c"][0] = -p["c"][0]
            if "n" in p: p["n"] = [-p["n"][0], p["n"][1], p["n"][2]]
            if "tilt" in p: p["tilt"] = dict(p["tilt"], toward=[-p["tilt"]["toward"][0], p["tilt"]["toward"][1]])
            if "pedal" in p:
                q = dict(p["pedal"])
                if "azimuth_deg" in q: q["azimuth_deg"] = -q["azimuth_deg"]
                if "ankle" in q: q["ankle"] = [-q["ankle"][0], q["ankle"][1]]
                p["pedal"] = q
            if isinstance(p.get("c"), dict) and "from_pedal" in p["c"]: p["c"] = dict(p["c"], from_pedal=[-p["c"]["from_pedal"][0], p["c"]["from_pedal"][1]])
        perf["lead_hand"] = "L" if perf["lead_hand"] == "R" else "R"
    elif "base" in pr:                                                                 # 2026-11-20: a layout that is another preset with some pieces MOVED (data only: `move: {piece: [dx, dy, dz]}`, metres;
        pieces, nm0, perf0, _ = resolve(pr["base"], Y); pieces = copy.deepcopy(pieces); nm = nm0; perf = perf0      # a piece placed from its pedal keeps its pedal: the offset moves the cymbal on its stand)
        for p in pieces:
            d = (pr.get("move") or {}).get(p["id"])
            if not d: continue
            if isinstance(p.get("c"), dict) and "from_pedal" in p["c"]: p["c"] = dict(p["c"], from_pedal=[p["c"]["from_pedal"][0] + d[0], p["c"]["from_pedal"][1] + d[1]], z=p["c"]["z"] + d[2])
            else: p["c"] = [p["c"][0] + d[0], p["c"][1] + d[1], p["c"][2] + d[2]]
    else: pieces = copy.deepcopy(pr["pieces"])
    perf.update(pr.get("performer", {}))
    for a in pr.get("add", []):
        pieces.append(dict(Y["library"][a["id"] if "like" not in a else a["like"]], **a))
    for k, v in (pr.get("note_map") or {}).items(): nm[int(k)] = v
    return pieces, nm, perf, dict(Y=Y, preset=name, note=pr.get("note", ""), names=pr.get("names") or {})


def derive_pref(K, Y, sticking="crossed"):
    """hand preference per piece (and for the cross-stick): geometry + role, from the layout and the lead hand -> {key: {L:, R:}} in the sibling PREF's units.
    sticking "open" (2026-11-20): drumkit.yaml preference.open_handed overrides the roles (hi-hat to the weak hand, snare to the lead hand)"""
    pc = dict(Y["preference"]); lead = K.LEAD; weak = "L" if lead == "R" else "R"; out = {}; byp = {}
    if sticking == "open": oh = pc["open_handed"]; pc["role"] = dict(pc["role"], **oh.get("role", {})); byp = oh.get("role_by_piece", {})
    for p in K.PIECES:
        if p["kind"] == "kick": continue
        for key, zone in ((p["id"], "head" if p["kind"] == "drum" else "edge"),) + ((("cross", "cross"),) if p["role"] == "backbeat" else ()):
            d = {h: float(np.linalg.norm(K.strike_point(p["id"], zone, h) - K.SHOULDER[h])) for h in "LR"}; ro = pc["zone"].get(zone, byp.get(p["id"]) if key != "cross" and p["id"] in byp else pc["role"][p["role"]])
            out[key if key != "cross" else "cross"] = {h: round(pc["geo_per_m"] * max(0.0, d[h] - d["L" if h == "R" else "R"]) + ro[0 if h == lead else 1], 2) for h in "LR"}
    return out


def load(name, sticking="crossed"):
    pieces, nm, perf, meta = resolve(name); Y = meta["Y"]; pf = performer(perf)
    spec = importlib.util.spec_from_file_location(f"kit_{name}", DRUMS / "kit.py"); K = importlib.util.module_from_spec(spec); spec.loader.exec_module(K)       # the sibling's kit.py, a private copy in memory
    K.PRESET = name; K.NOTE = meta["note"]; K.PERF = perf; K.BODY = pf; K.LEAD = perf["lead_hand"]; K.ROOT = tuple(perf["root"]); K.SEAT_Z, K.SEAT_Y = perf["seat"]["z"], perf["seat"]["y"]
    K.STICK_L, K.STICK_R, K.GRIP_DROP = Y["stick"]["l"], Y["stick"]["r"], Y["stick"]["drop"]; K.Q = dict(Y["zones"]); K.BELL_R, K.BELL_H = Y["bell"]["r"], Y["bell"]["h"]; K.HAT_GAP_OPEN, K.HAT_GAP_CLOSED = Y["hat_gap"]["open"], Y["hat_gap"]["closed"]
    K.SHOULDER = {h: pf["shoulder"][h].copy() for h in "LR"}; K.PEDALS = {}; K.FOOT_OF = {}
    K.BAND = tuple(perf["reach"]["comfortable_m"]); K.TURNOUT = {}
    for p in pieces:                                                                 # pedals first: pieces may stand on them
        if "pedal" in p:
            q = p["pedal"]
            if "azimuth_deg" in q: s, ank, info = pedal_place(pf, perf, q["azimuth_deg"])
            else: ank = np.array([q["ankle"][0], q["ankle"][1], perf["legs"]["ankle_z"]]); s = "L" if ank[0] > 0 else "R"; info = dict(typed=True)
            K.PEDALS[p["id"]] = dict(side=s, ankle=ank, derived="azimuth_deg" in q, **info); K.FOOT_OF[p["id"]] = s
            if "turnout_deg" in q: K.TURNOUT["kick" if p["kind"] == "kick" else "hat"] = q["turnout_deg"]
    K.PIECES = []
    for p in sorted(pieces, key=lambda p: (p["kind"] != "kick", 0)):                 # kicks first (the sibling's scene reads pieces[0] as the kick)
        p = dict(p); c = p["c"]
        if isinstance(c, dict): a = K.PEDALS[p["id"]]["ankle"]; c = [a[0] + c["from_pedal"][0], a[1] + c["from_pedal"][1], c["z"]]
        p["c"] = np.array(c, float); p["n"] = _n(p["n"]) if "n" in p else tilt(p["tilt"]["toward"], p["tilt"]["deg"]); p.setdefault("role", "tom"); K.PIECES.append(p)
    K.P = {p["id"]: p for p in K.PIECES}
    K.ANKLE = {}
    for pid, q in K.PEDALS.items(): K.ANKLE.setdefault(q["side"], q["ankle"])       # a foot's home pedal: the first pedal on its side (a second kick shares the hat foot: see README, not planned)
    K.KICKS = [p["id"] for p in K.PIECES if p["kind"] == "kick"]; K.HAT = next((p["id"] for p in K.PIECES if "pedal" in p and p["kind"] == "cymbal"), None)
    K.NOTE_MAP = {}
    for note, m in nm.items():
        if m is None or m[0] not in K.P: K.NOTE_MAP[note] = None if m is None else None; continue
        K.NOTE_MAP[note] = (m[0], m[1], (K.FOOT_OF[m[0]] + "F") if m[2] == "foot" else "hand")
    K.NOTE_UNMAPPED = {note: m[0] for note, m in nm.items() if m is not None and m[0] not in K.P}
    K.NAMES = {int(k): v for k, v in Y["names"].items()}; K.NAMES.update({int(k): v for k, v in meta["names"].items()}); K.ROLE = {p["id"]: p["role"] for p in K.PIECES}

    def strike_point(piece, zone, hand, gap=0.0):
        p = K.P[piece]; u = K.toward(p, K.SHOULDER[hand] + np.array([0, -0.25, 0])); s = p["c"] + u * (K.Q[zone] * p["r"])
        if p.get("two_hands") and zone != "cross": s = s + np.cross(p["n"], u) * (0.035 if hand == "R" else -0.035)      # two hands on one drum never share a spot
        if zone == "bell": s = s + p["n"] * K.BELL_H
        if piece == K.HAT: s = s + p["n"] * (0.012 + gap)
        return s

    def solids():
        """(id, top centre, normal out of the playing surface, radius, depth): every piece the same way (the sibling special-cased PIECES[0])"""
        return [(p["id"], p["c"], p["n"], p["r"], p["depth"]) for p in K.PIECES]

    def export():
        """the perf's `kit` block as the sibling's drum_scene.py reads it. Its two pedal boards are drawn at ankle.R (the KICK board) and ankle.L (the HAT board):
        here those two slots carry the kick pedal's and the hat pedal's ankles, whichever foot plays them (the scene is not edited)."""
        ak = K.PEDALS[K.KICKS[0]]["ankle"]; ah = K.PEDALS[K.HAT]["ankle"] if K.HAT else ak * np.array([-1, 1, 1])
        if K.FOOT_OF[K.KICKS[0]] == "L": ah = ah - np.array([0.04, 0, 0])          # the scene draws the hat board 2 cm to +x of its slot; a mirrored hat pedal gets the same offset the other way
        return dict(pieces=[dict(id=p["id"], kind=p["kind"], c=[round(float(v), 4) for v in p["c"]], n=[round(float(v), 4) for v in p["n"]], r=p["r"], depth=p["depth"], col=p["col"]) for p in K.PIECES],
                    bell=dict(r=K.BELL_R, h=K.BELL_H), seat_z=K.SEAT_Z, seat_y=K.SEAT_Y, stick=dict(l=K.STICK_L, r=K.STICK_R, drop=K.GRIP_DROP), ankle=dict(R=[float(x) for x in ak], L=[float(x) for x in ah]),
                    hat_gap=[K.HAT_GAP_CLOSED, K.HAT_GAP_OPEN], preset=name, foot_of=dict(K.FOOT_OF), lead_hand=K.LEAD)
    K.strike_point = strike_point; K.solids = solids; K.export = export
    K.PREF = derive_pref(K, Y, sticking); weak = "L" if K.LEAD == "R" else "R"; K.GRIP = {K.LEAD: perf["grip"]["lead"], weak: perf["grip"]["weak"]}; K.CROSSING = Y["preference"]["crossing"] if sticking != "open" else Y["preference"]["open_handed"]["crossing"]
    K.SCATTER = Y.get("impact_scatter"); K.SUBST = Y["preference"].get("substitute") or {"max_edge_gap_m": 9.0, "never": []}       # 2026-11-20 (benchmark round 3)
    K.STICKING = sticking; K.HOME = {K.LEAD: (K.HAT, "closed"), weak: ("snare", "head")} if sticking != "open" else {K.LEAD: ("snare", "head"), weak: (K.HAT, "closed")}      # where a hand with nothing to play waits
    return K


def describe(K):
    return dict(preset=K.PRESET, note=K.NOTE, lead_hand=K.LEAD, grip=K.GRIP, shoulders={h: np.round(K.SHOULDER[h], 3).tolist() for h in "LR"}, hips={s: np.round(K.BODY["hip"][s], 3).tolist() for s in "LR"},
                pedals={k: dict(side=v["side"], ankle=np.round(v["ankle"], 3).tolist(), **{a: b for a, b in v.items() if a not in ("side", "ankle")}) for k, v in K.PEDALS.items()}, foot_of=K.FOOT_OF, ankle={s: np.round(a, 3).tolist() for s, a in K.ANKLE.items()},
                hand_preference=K.PREF, note_map={k: v for k, v in K.NOTE_MAP.items()}, notes_without_a_piece=K.NOTE_UNMAPPED,
                pieces=[dict(id=p["id"], kind=p["kind"], role=p["role"], c=np.round(p["c"], 3).tolist(), n=np.round(p["n"], 3).tolist(), tilt_deg=round(math.degrees(math.acos(min(1.0, abs(float(p["n"][2]))))), 1), r=p["r"]) for p in K.PIECES])

# midi2motion: the lab's command line (derived-kit dump) was dropped
