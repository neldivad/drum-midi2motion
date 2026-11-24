#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/drums2/reach.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""reach.py: the reach check that runs BEFORE any solve (R-418): every piece of a layout against the performer's reach envelope (arm + stick, from the trunk
postures the planner may use), with the reason when a piece is outside it and a proposed placement.


Two stages per piece zone and hand:
  1. GEOMETRY (instant): the strike point's distance from that hand's shoulder at the seated neutral posture, from the nearest COMFORTABLE trunk posture
     (lean <= +10 deg over neutral, turn <= 12, side bend <= 6) and from the nearest posture of the planner's whole grid (rig.yaml body.reach_plan.drums), against
     the comfortable band the trunk planner itself uses (drumkit.yaml performer.reach.comfortable_m: 0.45..0.76 m, stick tip from the shoulder) and the arm's geometric limit
     (0.97 x arm + the stick tip's lever from the wrist).
  2. CONTACT POSE (the planner's own probe, stroke_plan.homes, with that hand's grip): from neutral, from the best comfortable posture and from the best posture of all,
     is there a pose with the wrist inside its ellipse and the arm inside 0.93 x reach?
Verdict per zone and hand: relaxed (a contact pose from the neutral seat, inside the comfortable band) > trunk (needs a comfortable lean or turn) > stretch (needs the
trunk past comfort, or the arm past the comfortable band) > out (no posture gives a contact pose). A PIECE's verdict is its dealing hand's worst zone (the hand the
derived preference gives it to; both hands when the preference is within 1.0).
Proposal for every piece that is not relaxed: slide it along the line shoulder -> strike point until the strike point is `place_at` (0.62 m) from the dealing shoulder,
re-aim its tilt at the player, and name the pieces the new place would overlap.
Feet: each pedal's knee angle, thigh splay and the shank rotation a foot square on its board would need.
"""
import json, math, pathlib, sys
sys.dont_write_bytecode = True
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent; LAB = HERE.parents[1]; sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
import arm_rig as AR, body_rig as BR, stroke_plan as SP, kitdata
from arm_rig import CFG
RP = CFG["body"]["reach_plan"]; KD = RP["drums"]; PLACE_AT = 0.62; COMF = dict(lean=10.0, side=6.0, turn=12.0); ORDER = ["relaxed", "trunk", "stretch", "out"]


def postures(K):
    body = K.BODY["body"]; ne = body.neutral; G = np.array([(l, s, t) for l in np.arange(*KD["lean"]) for s in np.arange(*KD["side"]) for t in np.arange(*KD["turn"])], float); G = np.vstack([[0.0, 0.0, 0.0], G]); z = np.zeros(len(G))
    T = body.trunk(dict(lean=ne["lean"] + G[:, 0], side=ne["side"] + G[:, 1], turn=ne["turn"] + G[:, 2], shift=np.zeros((len(G), 3)), nod=z, tilt=z, look=z))["T"]; caps = body.caps(T)
    comf = (G[:, 0] <= COMF["lean"] + 1e-6) & (np.abs(G[:, 1]) <= COMF["side"] + 1e-6) & (np.abs(G[:, 2]) <= COMF["turn"] + 1e-6); cost = ((G / np.array([RP["trunk_cost"][k] for k in ("lean", "side", "turn")])) ** 2).sum(1)
    return dict(G=G, T=T, caps=caps, comf=comf, cost=cost, Sh={h: BR.pt(T["chest"], AR.HEAD[f"upper_arm.{h}"]) for h in "LR"})


def zones_of(K):
    out = {}
    for note, m in K.NOTE_MAP.items():
        if m and m[2] == "hand": out.setdefault(m[0], [])
        if m and m[2] == "hand" and m[1] not in out[m[0]]: out[m[0]].append(m[1])
    for p in K.PIECES:
        if p["kind"] != "kick": out.setdefault(p["id"], ["head" if p["kind"] == "drum" else "edge"])       # a piece no note reaches is still checked
    return out


def dealers(K, pid, zone):
    pr = K.PREF["cross" if zone == "cross" else pid]; best = min(pr, key=pr.get); return [h for h in "LR" if pr[h] - pr[best] < 1.0]


def lever(K, h):
    g = SP.Grip(AR.ArmRig(side=h), K.GRIP[h], quick="probe"); return float(np.linalg.norm(g.f + SP.R_TIP * g.s0))


def probe(K, PO, g, h, pid, zone, A):
    rs = AR.ArmRig(PO["T"]["chest"][g], [(n, a[g], b[g], r) for n, a, b, r in PO["caps"]], h); s = dict(piece=pid, zone=zone, A=A, kind="hit"); SP.homes(rs, SP.Grip(rs, K.GRIP[h], quick="probe"), [s]); p = s["probe"]
    return dict(ok=bool(p["ellipse"] <= 1.0 and 0.50 <= p["ratio"] <= 0.93), wrist_ellipse=round(float(np.sqrt(p["ellipse"])), 2), reach=round(float(p["ratio"]), 2), wrist_flex=round(float(p["flex"])), wrist_dev=round(float(p["dev"])), pron=round(float(p["pron"])))


def check(K, with_probe=True):
    PO = postures(K); G = PO["G"]; rows = []; lev = {h: lever(K, h) for h in "LR"}; hard = {h: 0.97 * AR.L_ARM + lev[h] for h in "LR"}; tmin, tmax = K.BAND
    for pid, zs in zones_of(K).items():
        for zone in zs:
            for h in "LR":
                A = K.strike_point(pid, zone, h); d = np.linalg.norm(A - PO["Sh"][h], axis=1); d0 = float(d[0])
                def cands(mask, k):                                                 # the cheapest postures that bring the point into the comfortable band; else the ones that bring it nearest to the band
                    ok = mask & (d <= tmax) & (d >= tmin); i = np.nonzero(ok)[0]
                    if len(i): return [int(x) for x in i[np.argsort(PO["cost"][i])][:k]], True
                    i = np.nonzero(mask)[0]; gap = np.maximum(d[i] - tmax, tmin - d[i]); return [int(x) for x in i[np.argsort(gap + 1e-3 * PO["cost"][i])][:k]], False
                Cc, okc = cands(PO["comf"], 12); Ca, oka = cands(np.ones(len(G), bool), 6); gc, ga = Cc[0], Ca[0]
                r = dict(piece=pid, zone=zone, hand=h, grip=K.GRIP[h], dealer=h in dealers(K, pid, zone), strike_point=np.round(A, 3).tolist(), dist_neutral_m=round(d0, 3), band_m=[tmin, tmax], arm_limit_m=round(hard[h], 3))
                S = PO["Sh"][h][0]; rel = A - S; sg = 1.0 if h == "L" else -1.0; r["across_body_m"] = round(float(-sg * rel[0]), 3); r["above_shoulder_m"] = round(float(rel[2]), 3)
                geo = "relaxed" if tmin <= d0 <= tmax else "trunk" if okc else "stretch" if (oka or d[ga] <= hard[h]) else "out"; r["geometry"] = geo
                if with_probe:
                    def first(C):
                        q = None
                        for g in C:
                            q = probe(K, PO, g, h, pid, zone, A); q["posture"] = G[g].tolist(); q["g"] = g
                            if q["ok"]: break
                        return q
                    pr = {"neutral": first([0])}; pr["comfortable"] = pr["neutral"] if pr["neutral"]["ok"] else first(Cc); pr["any"] = pr["comfortable"] if pr["comfortable"]["ok"] else first(Ca); r["probe"] = pr
                    if pr["comfortable"]["ok"] and pr["comfortable"]["g"] != 0: gc = pr["comfortable"]["g"]
                    if pr["any"]["ok"]: ga = pr["any"]["g"]
                    pose = "relaxed" if pr["neutral"]["ok"] else "trunk" if pr["comfortable"]["ok"] else "stretch" if pr["any"]["ok"] else "out"; v = ORDER[max(ORDER.index(geo), ORDER.index(pose))]
                    if geo == "out" and pr["any"]["ok"]: v = "stretch"
                else: v = geo
                r.update(dist_comfortable_m=round(float(d[gc]), 3), posture_comfortable=G[gc].tolist(), dist_any_m=round(float(d[ga]), 3), posture_any=G[ga].tolist())
                r["verdict"] = v; why = []
                if d0 > tmax: why.append(f"the strike point is {d0:.2f} m from the {'left' if h == 'L' else 'right'} shoulder at rest: {d0 - tmax:.2f} m beyond the comfortable {tmax:.2f} m (arm {AR.L_ARM:.2f} m + stick lever {lev[h]:.2f} m = {hard[h]:.2f} m at full stretch)")
                if d0 < tmin: why.append(f"the strike point is {d0:.2f} m from the shoulder: nearer than the {tmin:.2f} m a stick needs")
                if v == "trunk": why.append(f"reached by leaning {G[gc][0]:+.0f} deg, bending {G[gc][1]:+.0f}, turning {G[gc][2]:+.0f}")
                if v == "stretch" and with_probe and r["probe"]["comfortable"]["ok"]: why.append(f"from the trunk's comfortable limit (lean {G[gc][0]:+.0f} deg, bend {G[gc][1]:+.0f}, turn {G[gc][2]:+.0f}) the tip is still {d[gc]:.2f} m from the shoulder: the arm plays it at {r['probe']['comfortable']['reach']:.2f} of its length, past its comfortable band")
                elif v == "stretch": why.append(f"needs the trunk at lean {G[ga][0]:+.0f} deg, bend {G[ga][1]:+.0f}, turn {G[ga][2]:+.0f} (past the comfortable {COMF['lean']:.0f} / {COMF['side']:.0f} / {COMF['turn']:.0f})" if oka else f"still {d[ga]:.2f} m away from the trunk's best posture: the arm plays it past its comfortable band")
                if v == "out": why.append(f"{d[ga]:.2f} m from the shoulder even at the trunk's limit" + (f"; arm limit {hard[h]:.2f} m" if d[ga] > hard[h] else ""))
                if with_probe and not r["probe"]["any"]["ok"]:
                    q = r["probe"]["any"]; why.append("no contact pose: " + (f"the wrist would be at {q['wrist_ellipse']:.2f} x its range" if q["wrist_ellipse"] > 1 else f"the arm at {q['reach']:.2f} x its length") + f" with the {K.GRIP[h]} grip")
                if r["across_body_m"] > RP["cross_free"]: why.append(f"{r['across_body_m']:.2f} m across the body (free up to {RP['cross_free']:.2f})")
                r["why"] = why; rows.append(r)
    pieces = {}
    for p in K.PIECES:
        if p["kind"] == "kick": continue
        rs = [r for r in rows if r["piece"] == p["id"] and r["dealer"]]; worst = max(rs, key=lambda r: ORDER.index(r["verdict"])); pv = dict(verdict=worst["verdict"], dealing_hands=sorted({r["hand"] for r in rs}), why=worst["why"], dist_neutral_m={r["hand"] + ":" + r["zone"]: r["dist_neutral_m"] for r in rs})
        if worst["verdict"] != "relaxed": pv["proposal"] = propose(K, p, rs)
        pieces[p["id"]] = pv
    return dict(preset=K.PRESET, lead_hand=K.LEAD, grip=K.GRIP, band_m=[tmin, tmax], arm_limit_m={h: round(hard[h], 3) for h in "LR"}, stick_lever_m={h: round(lev[h], 3) for h in "LR"}, comfortable_trunk=COMF, pieces=pieces, feet=feet(K), rows=rows)


def propose(K, p, rs):
    """slide the piece toward its dealing shoulder(s) until its strike point is PLACE_AT away; re-aim the tilt at the player; name what the new place overlaps"""
    hs = sorted({r["hand"] for r in rs}); S = np.mean([K.SHOULDER[h] for h in hs], 0); wz = max(rs, key=lambda r: (ORDER.index(r["verdict"]), r["dist_neutral_m"]))["zone"]; A = np.mean([np.array(r["strike_point"]) for r in rs if r["zone"] == wz], 0); u = (A - S) / np.linalg.norm(A - S); d = float(np.linalg.norm(A - S))
    target = min(max(PLACE_AT, K.BAND[0] + 0.05), d) if d > K.BAND[1] else max(d, K.BAND[0] + 0.08); c = p["c"] + u * (target - d); tl = math.degrees(math.acos(min(1.0, float(p["n"][2])))); tw = -c[:2] + np.array([0, K.SEAT_Y])
    n = kitdata.tilt(tw, tl); hit = []
    for q in K.PIECES:
        if q["id"] == p["id"]: continue
        dz = abs(c[2] - q["c"][2]); dxy = float(np.linalg.norm(c[:2] - q["c"][:2]));
        if q["kind"] == "kick": lo = q["c"][2] - q["r"]; hi = q["c"][2] + q["r"]; over = (c[2] - p["depth"] < hi) and (c[2] > lo) and abs(c[0] - q["c"][0]) < q["r"] + p["r"] and (q["c"][1] - q["depth"] - p["r"] < c[1] < q["c"][1] + p["r"])
        else: over = dxy < p["r"] + q["r"] + 0.01 and (c[2] - (p["depth"] if p["kind"] == "drum" else 0.03) < q["c"][2] + 0.02) and (q["c"][2] - (q["depth"] if q["kind"] == "drum" else 0.03) < c[2] + 0.02)
        if over: hit.append(q["id"])
    return dict(c=np.round(c, 3).tolist(), moved_m=round(float(np.linalg.norm(c - p["c"])), 3), tilt=dict(toward=np.round(tw / (np.linalg.norm(tw) + 1e-9), 2).tolist(), deg=round(tl, 1)), strike_point_from_shoulder_m=round(target, 3), overlaps=hit,
                note="slide along shoulder -> strike point" + ("; overlaps " + ", ".join(hit) + ": raise it, or move it around the shoulder at the same distance" if hit else ""))


def feet(K):
    pf = K.BODY; out = {}
    for pid, q in K.PEDALS.items():
        s = q["side"]; H = pf["hip"][s]; a = q["ankle"]; L1, L2 = pf["thigh"], pf["shin"]; d = float(np.linalg.norm(a - H)); ok = abs(L1 - L2) < d < 0.97 * (L1 + L2)
        knee = math.degrees(math.acos(np.clip((L1 * L1 + L2 * L2 - d * d) / (2 * L1 * L2), -1, 1))) if d < L1 + L2 else 180.0; splay = math.degrees(math.atan2(abs(a[0] - H[0]), -(a[1] - H[1])))
        out[pid] = dict(foot=s + "F", ankle=np.round(a, 3).tolist(), derived_from_the_leg=bool(q["derived"]), hip_to_ankle_m=round(d, 3), knee_angle_deg=round(knee, 1), thigh_splay_deg=round(splay, 1), wide_of_the_hip_m=round(abs(a[0]) - abs(H[0]), 3),
                        verdict="relaxed" if ok and 85 <= knee <= 125 and splay <= 32 else "stretch" if ok else "out", why=[] if (85 <= knee <= 125 and splay <= 32) else [f"knee angle {knee:.0f} deg (90-110 taught), thigh splayed {splay:.0f} deg"])
    return out


def table(R):
    print(f"\n== reach check: {R['preset']} (lead {R['lead_hand']}, grip {R['grip']}; comfortable band {R['band_m']} m, arm limit {R['arm_limit_m']})")
    for pid, v in R["pieces"].items():
        print(f"  {pid:7s} {v['verdict']:8s} hands {'+'.join(v['dealing_hands'])}  {v['dist_neutral_m']}" + ("" if not v["why"] else "\n           why: " + "; ".join(v["why"])) + ("" if "proposal" not in v else f"\n           propose c = {v['proposal']['c']} ({v['proposal']['moved_m']} m), {v['proposal']['note']}"))
    for pid, v in R["feet"].items(): print(f"  pedal {pid:5s} {v['verdict']:8s} {v['foot']} ankle {v['ankle']} knee {v['knee_angle_deg']} deg, splay {v['thigh_splay_deg']} deg, {v['wide_of_the_hip_m']} m wide of the hip")

# midi2motion: the lab's command line (reach probe) was dropped
