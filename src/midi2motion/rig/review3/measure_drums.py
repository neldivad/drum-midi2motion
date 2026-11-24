#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/review3/measure_drums.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""review3/measure_drums.py: what the solved DRUM motion actually struck (R-446), measured on the 120 Hz stick tips, stick shafts, beater and hi-hat, never read from the plan.

        reads   inspector/data/drums2/body_<clip>.json   (the solved motion: arms.<h>.stick.{tip,butt} at 120 Hz, pedals.{beater,hat}, feet.<s>.heel_mm, the kit block)
        writes  out/review3/contacts_drums_<clip>.json   (the common contact file judge.py reads: rows, limbs, the source MIDI notes, the measured contacts)

A CONTACT is found on EVERY piece for EVERY limb, planned or not:
  tip      a stick tip inside a piece's disc (radius + 4 mm) and within 3 mm of its playing surface, or below it (inside the piece). The surface is the head's plane for a drum,
           the bow + the bell's dome for a cymbal, the TOP cymbal's upper face for the hi-hat (12 mm + the gap the pedal holds at that instant). Time = the frame the tip
           stops descending (120 Hz: 8.3 ms steps); zone = where on the radius it landed (and, on the hi-hat, whether the pedal held it open or shut); speed = the fastest
           approach along the piece's normal in the 60 ms before. A tip that stays down and travels is one contact of kind `drag` (a sweep) with its end time.
           A tip that crosses a cymbal from one face to the other (found touching, or above on one frame and below on the next) is a `pass-through`.
  shaft    the stick's shaft (34 %..97 % of its length, radius 7 mm) inside a piece by more than 1 mm while the same stick's tip is NOT striking that piece (+-60 ms):
           a stick laid on a cymbal's edge or a rim on the way past. Deeper than 3 mm (the lab's own penetration tolerance) it counts as SOUNDING (a shaft strike);
           1..3 mm is a brush (silent by this file's count).
  beater   the kick's beater reaching the head (angle <= 0.5 deg after >= 3 deg back); speed = its fastest closing rate (deg/s).
  pedal    the hi-hat shutting under the foot (openness <= 0.02 after >= 0.3); speed = closing rate (1/s). `under_stick` marks a shut that a stick stroke on the hat follows
           within 80 ms (the foot closing the hat FOR a closed stroke: an articulation, not a note of its own).
  heel     the hat foot's heel landing on its board (keep-time, silent): listed as `silent`, never judged.
The SOURCE notes are the dataset's fate_rows: every MIDI note of the section with its MIDI id, and beside it (kept apart, as `plan`) what R-417's log says happened to it.
"""
import json, pathlib, sys
sys.dont_write_bytecode = True
import numpy as np
LAB = pathlib.Path(__file__).resolve().parents[2]; HZ = 120
TOUCH, RIM, SHAFT_MIN, SHAFT_SOUND, STICK_R = 0.003, 0.004, 0.001, 0.003, 0.007
ORDER = ["crash", "crash2", "china", "splash", "ride", "hat", "tom1", "tom2", "tom3", "snare", "floor", "floor2", "kick", "kick2"]
LABEL = dict(crash=("CRASH", "CR"), ride=("RIDE", "RD"), hat=("HI-HAT", "HH"), tom1=("TOM 1", "T1"), tom2=("TOM 2", "T2"), tom3=("TOM 3", "T3"), snare=("SNARE", "SN"), floor=("FLOOR TOM", "FT"), floor2=("FLOOR TOM 2", "FT2"), kick=("KICK", "K"), hatped=("HAT PEDAL", "PED"), layer=("LAYER (not on the kit)", "LYR"))
LIMBS = [dict(id="R", label="RIGHT HAND", short="RH", color=[92, 200, 255]), dict(id="L", label="LEFT HAND", short="LH", color=[255, 122, 196]), dict(id="RF", label="RIGHT FOOT", short="RF", color=[255, 150, 70]), dict(id="LF", label="LEFT FOOT", short="LF", color=[170, 140, 255])]


def runs(mask, gap=2):
    """[(f0, f1)] of True runs, runs closer than `gap` frames joined"""
    f = np.nonzero(mask)[0]
    if not len(f): return []
    cut = np.nonzero(np.diff(f) > gap)[0]; return [(int(a[0]), int(a[-1])) for a in np.split(f, cut + 1)]


def zone_of(kind, pid, q, bell_q, is_hat, open_):
    if is_hat: return ("open" if open_ > 0.5 else "closed") + (" edge" if q > 0.8 else "")
    if kind == "cymbal": return "bell" if q <= bell_q + 0.03 else "bow" if q < 0.75 else "edge"
    return "centre" if q < 0.2 else "head" if q < 0.6 else "outer head"


def measure(clip, OUT):
    D = json.load(open(LAB / f"inspector/data/drums2/body_{clip}.json")); N = D["N"]; kit = D["kit"]; P = {p["id"]: p for p in kit["pieces"]}; bell = kit["bell"]; g0, g1 = kit["hat_gap"]; ped = D["pedals"]
    ho = np.array(ped["hat"]); be = np.array(ped["beater"]); hat_id = next((p for p in P if p == "hat"), None); kf, hf = ped["kick_foot"], ped["hat_foot"]; C = []
    tipc = {}
    for h in "LR":
        st = D["arms"][h]["stick"]; tip = np.array(st["tip"]); butt = np.array(st["butt"]); tipc[h] = {}
        for pid, p in P.items():
            c = np.array(p["c"]); n = np.array(p["n"]); r = p["r"]; x = tip - c; ax = x @ n; rr = np.linalg.norm(x - np.outer(ax, n), axis=1)
            surf = np.zeros(N)
            if p["kind"] == "cymbal": surf = bell["h"] * np.clip(1 - rr / bell["r"], 0, None) if pid != hat_id else 0.012 + g0 + (g1 - g0) * ho
            hgt = ax - surf; floor_ = -(p["depth"] + TOUCH) - (surf if pid == hat_id else 0)
            touch = (rr <= r + RIM) & (hgt <= TOUCH) & (hgt >= floor_) if p["kind"] != "kick" else (rr <= r + RIM) & (ax <= TOUCH) & (ax >= -(p["depth"] + TOUCH))
            tipc[h][pid] = []
            for f0, f1 in runs(touch):
                seg = hgt[f0:f1 + 1]; fi = f0 + int(np.argmax(seg <= seg.min() + 0.0005)); a = max(1, fi - 7); v = -np.diff(hgt[a - 1:fi + 1]) * HZ; q = float(rr[fi] / r); dwell = (f1 - f0) / HZ; path = float(np.linalg.norm(np.diff(tip[f0:f1 + 1], axis=0), axis=1).sum()) if f1 > f0 else 0.0
                drag = dwell > 0.10 and path > 0.04; below = f0 > 0 and hgt[f0 - 1] < floor_[f0 - 1] if isinstance(floor_, np.ndarray) else f0 > 0 and hgt[f0 - 1] < floor_; through = (below and f1 + 1 < N and hgt[f1 + 1] > TOUCH) or (not below and f1 + 1 < N and f0 > 0 and hgt[f0 - 1] > TOUCH and hgt[f1 + 1] < (floor_[f1 + 1] if isinstance(floor_, np.ndarray) else floor_) and rr[f1 + 1] <= r)
                c_ = dict(t=round(fi / HZ, 4), t_off=round(f1 / HZ, 4), row=pid, limb=h, part="tip", kind="drag" if drag else "stroke", zone=zone_of(p["kind"], pid, q, bell["r"] / r, pid == hat_id, float(ho[fi])), radius_frac=round(q, 2),
                          speed=round(float(v.max()) if len(v) else 0.0, 3), unit="m/s", depth_mm=round(float(-seg.min() * 1000), 1), dwell_s=round(dwell, 3), path_m=round(path, 3), sounding=True, frame=fi)
                if pid == hat_id: c_["hat_open"] = round(float(ho[fi]), 2)
                if through and p["kind"] == "cymbal": c_.update(kind="pass-through", speed=round(float(np.abs(np.diff(hgt[max(0, f0 - 1):f1 + 2])).max() * HZ), 3), ctx=dict(direction="from below" if below else "from above", inside_rim_mm=round(float((r - rr[fi]) * 1000), 1)))
                C.append(c_); tipc[h][pid].append((f0, f1))
            sgn = np.where(hgt > TOUCH, 1, np.where(hgt < floor_, -1, 0)); inr = rr <= r
            if p["kind"] == "cymbal":
                for f in np.nonzero((sgn[1:] * sgn[:-1] == -1) & inr[1:] & inr[:-1])[0] + 1:      # above on one frame, below on the next (a thin cymbal crossed inside one 120 Hz step)
                    C.append(dict(t=round((f - 0.5) / HZ, 4), t_off=round(f / HZ, 4), row=pid, limb=h, part="tip", kind="pass-through", zone=zone_of(p["kind"], pid, float(rr[f] / r), bell["r"] / r, pid == hat_id, float(ho[f])), radius_frac=round(float(rr[f] / r), 2), speed=round(float(abs(hgt[f] - hgt[f - 1]) * HZ), 3), unit="m/s",
                                  depth_mm=round(p["depth"] * 1000, 1), dwell_s=0.0, path_m=0.0, sounding=True, frame=int(f), ctx=dict(direction="from below" if sgn[f] > 0 else "from above", inside_rim_mm=round(float((r - rr[f]) * 1000), 1))))
        # the shaft, where its own tip is not striking
        u = np.linspace(0.34, 0.97, 22)[None, :, None]; pts = butt[:, None, :] + (tip - butt)[:, None, :] * u
        for pid, p in P.items():
            c = np.array(p["c"]); n = np.array(p["n"]); x = pts - c; ax = -(x @ n); radial = np.linalg.norm(x + n * ax[..., None], axis=-1); inside = (ax > -STICK_R) & (ax < p["depth"] + STICK_R) & (radial < p["r"] + STICK_R)
            pen = np.where(inside, np.minimum(np.minimum(ax + STICK_R, p["r"] + STICK_R - radial), p["depth"] + STICK_R - ax), 0.0); pm = pen.max(1); where = u[0, pen.argmax(1), 0]; own = np.zeros(N, bool)
            for f0, f1 in tipc[h][pid]: own[max(0, f0 - 7):f1 + 8] = True
            for f0, f1 in runs((pm > SHAFT_MIN) & ~own):
                fi = f0 + int(np.argmax(pm[f0:f1 + 1]))
                sp = float((np.diff(pm[max(0, f0 - 2):fi + 1]) * HZ).max()) if fi > max(0, f0 - 2) else 0.0; loud = bool(pm[fi] > SHAFT_SOUND)
                C.append(dict(t=round(f0 / HZ, 4), t_off=round(f1 / HZ, 4), row=pid, limb=h, part="shaft", kind="shaft strike" if loud else "brush", zone=f"shaft at {int(round(100 * where[fi]))} % of the stick", speed=round(sp, 3), unit="m/s into the piece", depth_mm=round(float(pm[fi] * 1000), 1), dwell_s=round((f1 - f0) / HZ, 3), sounding=loud, frame=f0))
    # the beater on the kick's head
    down = be <= 0.5
    for f in np.nonzero(down[1:] & ~down[:-1])[0] + 1:
        a = max(0, f - 24)
        if be[a:f].max() < 3.0: continue
        v = -np.diff(be[a:f + 1]) * HZ; C.append(dict(t=round(f / HZ, 4), t_off=round(f / HZ, 4), row="kick", limb=kf, part="beater", kind="stroke", zone="beater", speed=round(float(v.max()), 1), unit="deg/s", lift_deg=round(float(be[a:f].max()), 1), depth_mm=0.0, sounding=True, frame=int(f)))
    # the hi-hat shutting under the foot
    shut = ho <= 0.02; hat_tips = sorted(c["frame"] for c in C if c["row"] == hat_id and c["part"] == "tip")
    for f in np.nonzero(shut[1:] & ~shut[:-1])[0] + 1:
        a = max(0, f - 36)
        if ho[a:f].max() < 0.3: continue
        v = -np.diff(ho[a:f + 1]) * HZ; under = any(0 <= ft - f <= 0.08 * HZ + 1 for ft in hat_tips)
        C.append(dict(t=round(f / HZ, 4), t_off=round(f / HZ, 4), row="hatped", limb=hf, part="pedal", kind="stroke", zone="pedal", speed=round(float(v.max()), 2), unit="1/s", from_open=round(float(ho[a:f].max()), 2), depth_mm=0.0, sounding=True, under_stick=bool(under), frame=int(f)))
    silent = []
    hm = np.array(D["feet"][hf[0]]["heel_mm"]); dn = hm <= 0.5
    for f in np.nonzero(dn[1:] & ~dn[:-1])[0] + 1:
        if hm[max(0, f - 30):f].max() >= 5.0: silent.append(dict(t=round(f / HZ, 4), row="hatped", limb=hf, label="heel tap"))
    C.sort(key=lambda c: (c["t"], c["row"]))
    # ---- the source MIDI notes (the ground truth) and, beside them, the plan's account
    nm = D["layout"]["note_map"]; log = {}
    for e in D.get("loop_log", []):
        for i in e.get("ids") or [e["id"]]: log.setdefault(i, []).append(e)
    src = []
    for r in D["fate_rows"]:
        m = nm.get(str(r["note"])); row = "layer" if r["piece"] is None else "hatped" if (m and m[1] == "pedal") else r["piece"]; e = (log.get(r["midi"]) or [{}])[-1]
        src.append(dict(id=r["midi"], t=r["t"], dur=0.0, row=row, vel=r["vel"], note=r["note"], name=r["name"], zone=m[1] if m else None, bar=r.get("bar"), judged=r["piece"] is not None,
                        plan=dict(fate=r["fate"], limb=r.get("limb"), limit=r.get("limit"), how=r.get("how"), why=e.get("why") or r.get("why"), stage=e.get("stage") or r.get("stage"), check=e.get("check"))))
    used = {s["row"] for s in src} | {c["row"] for c in C} | set(P) | {"hatped"}; rows = [x for x in ORDER if x in used and x not in ("kick", "kick2")] + [x for x in sorted(used) if x not in ORDER and x not in ("hatped", "layer")] + [x for x in ("kick", "kick2", "hatped", "layer") if x in used]
    ch = D["chart"]; lay = D.get("layout") or {}; W = LAB / "work/drums2"
    out = dict(schema="review3.contacts/1", clip=f"drums_{clip}", instrument="drums", title=f"DRUMS  {lay.get('preset', '')}  closure bars {ch['bars'][0]}-{ch['bars'][1]}", fps=30, hz=HZ, frames=D["N"] // 4 + 1, duration=round((N - 1) / HZ, 4),
               audio=str((LAB / "inspector" / D["audio"]).resolve().relative_to(LAB.parent.resolve())), videos=dict(full=f"work/drums2/{clip}_perf_v001.mp4", close=f"work/drums2/{clip}_close_v001.mp4", inset=f"work/drums2/{clip}_feet_v001.mp4", inset_label="FEET"),
               grid=dict(lead=ch["lead"], beat_s=ch["bar_s"] / 4, bar0=ch["bars"][0], bpb=4), limbs=LIMBS, rows=[dict(id=x, label=LABEL.get(x, (x.upper(), x[:3].upper()))[0], short=LABEL.get(x, (x.upper(), x[:3].upper()))[1]) for x in rows],
               near={a: [b for b in P if b != a and np.linalg.norm(np.array(P[a]["c"]) - np.array(P[b]["c"])) < P[a]["r"] + P[b]["r"] + 0.20] for a in P}, zone_same=dict(head=["head", "centre", "outer head"], rimshot=["outer head", "head"], cross=["centre"], closed=["closed", "closed edge"], open=["open", "open edge"], edge=["edge"], bow=["bow", "edge"], bell=["bell"], beater=["beater"], pedal=["pedal"]),
               source=src, contacts=C, silent=silent, source_file=f"inspector/data/drums2/body_{clip}.json",
               measure=dict(resolution_ms=round(1000 / HZ, 1), tip_touch_mm=TOUCH * 1000, rim_margin_mm=RIM * 1000, shaft_min_mm=SHAFT_MIN * 1000, shaft_sounding_mm=SHAFT_SOUND * 1000, note="tip, shaft, beater and hi-hat contacts found on every piece from the solved 120 Hz motion; speed = approach along the piece's normal"))
    OUT.mkdir(parents=True, exist_ok=True); f = OUT / f"contacts_drums_{clip}.json"; assert not f.exists(), f"{f} exists: versions only go up"; json.dump(out, open(f, "w"), indent=0); return out

# midi2motion: the lab's command line was dropped
