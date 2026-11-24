#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/drums2/run2.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""run2.py: drum round 2. One layout of drumkit.yaml x one section of his drum MIDI through the full-body solver (tools/fullbody.plan_drums: both arms on a moving
trunk, both feet, head, layers), under R-417 with the end-point caps of R-441.

        -> out/drums2/run_<preset>_b<bars>.json           every number: reach verdicts, both passes' check tables, end points raw -> played, the loop, every MIDI note's fate
           inspector/data/drums2/body_<preset>_b<bars>.json (+ _raw)   the inspector datasets (body.html?ds=drums2_<preset>_b<bars>)
           out/drums2/drive_<preset>_b<bars>.json          the driving skeleton
           work/drums2/render_<preset>_b<bars>.json        the render perf (the sibling's drum_scene.py draws the kit from its `kit` block)
                                                                         bit for bit and measured with C-END-1 (nothing of that round is rewritten)

Order of work: kitdata (the layout, derived tables) -> chart2 (the deal) -> THE SHIFT TABLE (R-441, before any solve: a hand shift that cannot fit its window as a
minimum-jerk reach costs a note) -> solve -> the whole 120 Hz check table + C-END-1 -> THE LOOP (R-417): every run of frames over a hard limit, and every dealt
note not struck on its frame, takes that limb's nearest note one step down:  f softer (60 % of its velocity: a lower lift, a slower downstroke)  ->  g a simpler
gesture (a sweep or a roll becomes single strokes; a plain stroke has none)  ->  h cut.  Never late. Every step is logged against the note's MIDI id with the
limit that forced it. RAW = pass 0 of the loop after the chart's deal and before any table or step: the control.
Reopened 2026-11-20 (R-448, the Groove benchmark): before softer the loop now DECIDES instead of hovering:  a  the free hand takes the note (re-dealt to the other
hand, when it has no note within 100 ms and both its shifts fit)  ->  b  the blocked hand plays the nearest reachable piece of the same family (drum for drum,
cymbal for cymbal; both shifts fit)  ->  f softer  ->  g simpler  ->  h cut. The shift table takes a and b too, then cuts (softer only lengthens a downstroke).
Every step is logged against the MIDI id. Two notes of one hand snapped onto ONE frame are one stroke (same piece) or go to the free hand / are cut (two pieces).
"""
import copy, importlib.util, json, math, pathlib, sys, time
sys.dont_write_bytecode = True
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent; DRUMS = HERE.parent / "sibling"      # midi2motion: the sibling modules (kit, rig, drum_perf, drum_chart) are packaged beside the rig
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE)); sys.path.insert(0, str(DRUMS))
import arm_rig as AR, bake, checks, body_rig as BR, body_checks as BK, body_bake as BB, fullbody as FB, kitdata, chart2, endpoints as EPT, reach
from arm_rig import CFG, HZ
EV = CFG["render_every"]; MAX_IT = 16; REDEAL = True          # REDEAL False = the pre-2026-11-20 ladder (softer -> simpler -> cut), for A/B
ARM_PHYS = {"C-JT-1": "joint range", "C-TW-1": "joint range", "C-IK-2": "reach", "C-CONT-1": "speed ceiling", "C-CONT-2": "continuity", "C-CONT-3": "continuity", "C-CONT-4": "continuity", "C-COL-1": "collision", "C-END-1": "end-point speed"}
BODY_PHYS = {"C-JT-1 body": "joint range", "C-CONT-1 body": "speed ceiling", "C-CONT-2 body": "continuity", "C-CONT-3 body": "continuity", "C-CONT-4 body": "continuity", "C-FOOT-1 body": "foot slide", "C-COL-1 body": "collision", "C-END-1 body": "end-point speed"}
rl = FB.rl


def drum_perf(K):
    """the sibling's drum_perf.py, a private copy in memory with ITS kit swapped for this layout's (stroke list, sweeps, envelopes: all reused, nothing edited)"""
    spec = importlib.util.spec_from_file_location(f"drum_perf_{K.PRESET}", DRUMS / "drum_perf.py"); DP = importlib.util.module_from_spec(spec); spec.loader.exec_module(DP); DP.kit = K; return DP


# ---------------------------------------------------------------- the chart's notes under R-417's ladder
def applied(C, state):
    """the chart's notes with every step taken so far applied -> notes (copies)"""
    notes = copy.deepcopy(C["notes"]); by = {n["id"]: n for n in notes}; runs = {}
    for n in notes:
        if n.get("art", {}).get("kind") == "sweep": runs.setdefault(n["art"]["id"], []).append(n)
    for nid, st in state.items():
        n = by[nid]; n["step"] = st["step"]; n["vel_midi"] = n["vel"]
        if st["step"] == 0 and st.get("pre") == 1: n["limb_was"] = n["limb"]; n["limb"] = st["limb_to"]; n["redealt"] = True          # R-448 a: the free hand takes it
        if st["step"] == 0 and st.get("pre") == 2:                                                                                        # R-448 b: the nearest reachable piece
            n.update(piece_was=n["piece"], zone_was=n["zone"], note_was=n["note"], piece=st["piece_to"], zone=st["zone_to"], note=st["note_to"], subst=True)
        if st["step"] >= 1: n["vel"] = max(22, int(round(0.6 * n["vel"])))
        if st["step"] >= 2:
            a = n.pop("art", None); n["simple"] = True
            if a and a["kind"] == "sweep":
                for m in runs[a["id"]]:
                    if m is not n: m.pop("art", None); m["limb_was"] = m["limb"]; m["limb"] = None; m["folded"] = nid
        if st["step"] >= 3:
            n["limb_was"] = n["limb"]; n["limb"] = None; n["cut"] = True
            a = n.get("art")
            if a and a["kind"] == "sweep":
                for m in runs[a["id"]]:
                    if m is not n: m["limb_was"] = m["limb"]; m["limb"] = None; m["folded"] = nid
    return notes


def targets(K, C, state, DP=None, do_restick=True):
    """the full-body planner's inputs for this kit and chart (as body_targets.drums gives them for the sibling's)"""
    DP = DP or drum_perf(K); fps = C["fps"]; notes = applied(C, state)
    for n in notes: n["tc_raw"] = n["tc"]; n["tc"] = n["frame"] / fps if abs(n["tc"] * fps - n["frame"]) < 0.51 else n["tc"]
    same_frame(notes)
    hatf = DP.hat_track([n for n in notes if n["note"] in (42, 44, 46) and (n["limb"] or n.get("limb_was"))], C["frames"] / fps); gap = lambda t: K.HAT_GAP_CLOSED + (K.HAT_GAP_OPEN - K.HAT_GAP_CLOSED) * hatf(t)
    S = {}; hn = {}
    for h in "LR":
        mine = [n for n in notes if n["limb"] == h and not n.get("merged")]; S[h] = DP.Hand(h, mine, gap).S; hn[h] = [n for n in mine if 0 <= n["frame"] < C["frames"]]
        if not S[h]:                                                                     # 2026-11-20: a hand with NO stroke in the whole window (a one-handed fill) crashed the tip planner. It waits
            home = getattr(K, "HOME", {}).get(h) or ((K.HAT, "closed") if h == K.LEAD else ("snare", "head"))               # at its home piece (lead hand over the hi-hat, weak hand over the snare): one silent rest stroke 3 s before the clip
            S[h] = DP.Hand(h, [dict(tc=-3.0, tc_raw=-3.0, piece=home[0], zone=home[1], vel=40, id=None)], gap).S
            for s_ in S[h]: s_["rest"] = True
        for s in S[h]:
            src = [n for n in mine if abs(n["tc"] - s["t"]) < 1e-6 and n["piece"] == s["piece"]] if s["kind"] != "sweep" else [n for n in mine if n.get("art", {}).get("id") == s["art"]]
            s["ids"] = [n["id"] for n in src]; s["vel_midi"] = max([n.get("vel_midi", n["vel"]) for n in src] or [s["vel"]])
            scatter(K, DP, h, s, src)
            if s["kind"] == "cross" or any(n.get("simple") for n in src): s["lift"] = 0.45
    d = dict(S=S, notes=hn, all_notes=[n for n in notes if n["limb"]], N=4 * (C["frames"] - 1) + 1, hz=120, lead=C["lead"], bar_s=C["bar_s"], bars=C["bars"], DP=DP, kit=K, gap=gap, chart=C, frames=C["frames"], notes_all=notes)
    d["resticked"] = FB.restick(S, K, gap) if do_restick else []
    return d


def scatter(K, DP, h, s, src=()):
    """2026-11-20 (benchmark round 3, drumkit.yaml impact_scatter): the stroke's strike point A moves in the surface plane by a draw seeded by its first MIDI id
    (deterministic), sigma = sigma0 + k x velocity / 127 (signal-dependent noise), the radial position kept inside its zone's band; the wrist's home is re-derived. Sweeps, rest strokes and strokes with no MIDI id stay."""
    sc = getattr(K, "SCATTER", None)
    if not sc or s["kind"] == "sweep" or s.get("rest") or not s.get("ids"): return
    p = K.P[s["piece"]]; kind = "hat" if s["piece"] == K.HAT else p["kind"]
    if kind not in sc["sigma0_m"]: return
    sig = sc["sigma0_m"][kind] + sc["k_m"][kind] * min(1.0, s.get("vel_midi", s["vel"]) / 127.0)          # signal-dependent noise: louder strokes scatter more (Harris & Wolpert 1998)
    rng = np.random.default_rng([sc["seed"], int(str(s["ids"][0]).split(":")[-1])]); dxy = rng.normal(0.0, sig, 2); m = float(np.linalg.norm(dxy)); lim = sc["clip_sigma"] * sig
    if m > lim: dxy = dxy * (lim / m)
    n = p["n"]; e1 = np.cross(n, [0.0, 0.0, 1.0]); e1 = e1 / np.linalg.norm(e1) if np.linalg.norm(e1) > 1e-6 else np.array([1.0, 0.0, 0.0]); e2 = np.cross(n, e1)
    A = s["A"] + e1 * dxy[0] + e2 * dxy[1]; rv = (A - p["c"]) - n * float((A - p["c"]) @ n); q = float(np.linalg.norm(rv)) / p["r"]; q0 = K.Q.get(s["zone"], q); band = sc["zone_band"]
    lo, hi = max(0.0, q0 - band), min(0.92, q0 + band)
    if q > 1e-9 and not (lo <= q <= hi): A = A - rv + rv * (min(max(q, lo), hi) / q)
    s["A_aim"] = s["A"]; s["A"] = A; s["W"], s["d0"] = DP.wrist_home(h, A, s["zone"]); s["scatter_mm"] = round(1000 * float(np.linalg.norm(A - s["A_aim"])), 1); s["scatter_sigma_mm"] = round(1000 * sig, 1)
    for n in src: n["A_strike"] = A                                                          # the sync check judges the stroke against where it was AIMED (body_checks.drum_sync)


def same_frame(notes):
    """2026-11-20: real drummers' flams and drags put two notes of one hand 5-15 ms apart; snapped to 30 fps they land on ONE frame, and two strokes at one instant
    (a zero gap) crashed the stroke planner. Same piece: one stroke (the louder leads, the other rides on it). Two pieces: the free hand takes the later one, else it is cut
    (two hands)."""
    plain = [n for n in notes if n["limb"] in ("L", "R") and not n.get("merged") and not (n.get("art", {}).get("kind") == "sweep" and n["art"]["i"] > 0)]
    by = {}
    for n in plain: by.setdefault((n["limb"], n["frame"]), []).append(n)
    for (h, f), L in by.items():
        if len(L) < 2: continue
        L.sort(key=lambda n: (-n["vel"], n["tc_raw"])); lead = L[0]
        for n in L[1:]:
            if n["piece"] == lead["piece"] and not n.get("art"): n["merged"] = True; n["merge_how"] = "one stroke: two notes of one piece on one frame (a flam on one hand)"; continue
            o = "L" if h == "R" else "R"
            if not any(m["limb"] == o and abs(m["tc"] - n["tc"]) < 0.1 for m in plain if m is not n): n["limb_was"] = h; n["limb"] = o; n["redealt"] = True; n["redeal_why"] = "same frame as another stroke of its hand"
            else: n["limb_was"] = h; n["limb"] = None; n["limit"] = "two hands"; n["why"] = "two notes of one hand on one frame, the other hand busy"


class Ladder:
    """R-448's first two steps for one pass's dealt notes: is the other hand free for a note, and which piece is the nearest one the blocked hand can reach"""
    FAMILY = dict(drum=("drum",), cymbal=("cymbal",))

    def __init__(self, K, d):
        self.K = K; self.notes = [n for n in d["notes_all"] if n["limb"] in ("L", "R") and not n.get("merged")]
        self.sub_note = {}
        for note, m in sorted(K.NOTE_MAP.items()):
            if m and m[2] == "hand" and m[1] in ("head", "closed", "bow", "edge") and m[0] not in self.sub_note: self.sub_note[m[0]] = (int(note), m[1])

    def eligible(self, n):
        return n.get("limb") in ("L", "R") and not n.get("art") and n.get("zone") != "cross" and not n.get("merged")

    def fits(self, h, n, piece, zone):
        """both of hand h's shifts (from its previous note, to its next) fit as minimum-jerk reaches (chart2's rule), with n played on piece/zone"""
        mine = sorted([m for m in self.notes if m["limb"] == h and m is not n], key=lambda m: m["tc"]); sp = self.K.strike_point(piece, zone, h)
        prev = [m for m in mine if m["tc"] <= n["tc"]]; nxt = [m for m in mine if m["tc"] > n["tc"]]
        for m, dt in ((prev[-1] if prev else None, None), (nxt[0] if nxt else None, None)):
            if m is None: continue
            dt = abs(n["tc"] - m["tc"])
            if dt < 0.1 - 1e-6: return False
            dist = float(np.linalg.norm(self.K.strike_point(m["piece"], m["zone"], h) - sp))
            if dist > 0.05 and EPT.shift_time(dist) > dt - 0.05: return False
        return True

    def free(self, n, h):
        return self.fits(h, n, n["piece"], n["zone"])

    def neighbour(self, a, b):
        """2026-11-20 (round 3): b may stand in for a: same kind, neither is a never-swap piece (the hi-hat), rims within max_edge_gap_m (3D)"""
        P, sub = self.K.P, getattr(self.K, "SUBST", {"max_edge_gap_m": 9.0, "never": []})
        if a in sub.get("never", []) or b in sub.get("never", []) or P[a]["kind"] != P[b]["kind"]: return False
        return float(np.linalg.norm(P[a]["c"] - P[b]["c"])) - P[a]["r"] - P[b]["r"] <= sub["max_edge_gap_m"]

    def nearest(self, n, h, piece0, zone0):
        kind = self.K.P[piece0]["kind"]; best = None; sp0 = self.K.strike_point(piece0, zone0, h)
        for p in self.K.PIECES:
            pid = p["id"]
            if pid == piece0 or p["kind"] != kind or pid not in self.sub_note or not self.neighbour(piece0, pid): continue
            note, zone = self.sub_note[pid]
            if any(m["limb"] != h and m["piece"] == pid and abs(m["tc"] - n["tc"]) < 0.05 for m in self.notes): continue
            if not self.fits(h, n, pid, zone): continue
            dd = float(np.linalg.norm(self.K.strike_point(pid, zone, h) - sp0)) + (0.0 if p["role"] == self.K.P[piece0]["role"] else 1.0)      # the same role first (tom <-> tom)
            if best is None or dd < best[0]: best = (dd, pid, zone, note)
        return best


def pre_step(n, st, lad, limit, log, n_frames, check, stage):
    """R-448 a / b for a note a limit is charging -> True if a step was taken (logged)"""
    if lad is None or st.get("step", 0) != 0 or st.get("pre", 0) >= 3 or not lad.eligible(n): return False
    h0 = st.setdefault("hand0", n.get("limb_was") if st.get("pre") == 1 else n["limb"]); piece0 = n.get("piece_was", n["piece"]); zone0 = n.get("zone_was", n["zone"])
    if st.get("pre", 0) == 0:
        o = "L" if h0 == "R" else "R"; st["pre"] = 1
        if lad.free(dict(n, piece=piece0, zone=zone0), o):
            st["limb_to"] = o; log.append(dict(id=n["id"], t=round(n["tc"], 4), bar=n.get("bar"), limb=h0, piece=piece0, note=n.get("note_was", n["note"]), vel=n.get("vel_midi", n["vel"]), limit=limit, check=check, frames=n_frames, rule=f"a another limb: {o} takes it (R-448)", stage=stage)); return True
    if st.get("pre", 0) == 1:
        st["pre"] = 2; st.pop("limb_to", None); b = lad.nearest(n, h0, piece0, zone0)
        if b:
            st.update(piece_to=b[1], zone_to=b[2], note_to=b[3]); log.append(dict(id=n["id"], t=round(n["tc"], 4), bar=n.get("bar"), limb=h0, piece=piece0, note=n.get("note_was", n["note"]), vel=n.get("vel_midi", n["vel"]), limit=limit, check=check, frames=n_frames, rule=f"b nearest reachable piece: {b[1]} (R-448)", stage=stage, sub_piece=b[1])); return True
    st["pre"] = 3; [st.pop(k, None) for k in ("limb_to", "piece_to", "zone_to", "note_to")]; return False


def shift_rows(d):
    """R-441, before any solve: every hand shift as the planner will time it (stroke_plan.tip_plan's window) against the minimum-jerk time it needs under the wrist's caps"""
    DP = d["DP"]; rows = []
    for h in "LR":
        S = d["S"][h]
        for a, b in zip(S[:-1], S[1:]):
            Aa = a.get("A_end", a["A"]); dist = float(np.linalg.norm(b["A"] - Aa)); g = b["t"] - a["t_end"]; Td = DP.down_t(b["vel"])
            if g > 0.34: Tm = min(0.45, max(0.16, dist / 1.3)); ts = max(a["t_end"] + 0.02, b["t"] - Td - 0.03 - Tm); te = b["t"] - Td
            else: ts = a["t_end"]; te = b["t"] - 0.6 * min(Td, 0.5 * g)
            Wa = a["W"] + (a["A_end"] - a["A"]) if "A_end" in a else a["W"]; dw = float(np.linalg.norm(b["W"] - Wa))          # the wrist travels less than the tip: each against its own caps
            have = te - ts; need = max(EPT.shift_time(dw), EPT.shift_time(dist, CFG["endpoints"]["tip"])); rows.append(dict(hand=h, t=round(b["t"], 4), frm=a["piece"], to=b["piece"], dist_m=round(dist, 3), wrist_dist_m=round(dw, 3), have_s=round(have, 3), need_s=round(need, 3), fits=bool(dist < 0.05 or have >= need - 1e-6), a=a, b=b,
                                                                           peak_speed_m_s=round(EPT.MJ_V * dw / max(have, 1e-3), 2), peak_accel_m_s2=round(EPT.MJ_A * dw / max(have, 1e-3) ** 2, 1)))
    return rows


def shift_table(K, C, state, log, DP, redeal=True):
    """before any animation, the note of every shift that cannot fit pays: the quieter of the two strokes (a ghost before an accent goes first). R-448 (2026-11-20):
    the free hand takes it, else the nearest piece this hand can reach in time, else it is cut (softer would only lengthen the downstroke)"""
    for _ in range(200):
        d = targets(K, C, state, DP); bad = [r for r in shift_rows(d) if not r["fits"] and 0 <= r["b"]["t"] < C["dur"]]
        if not bad: return d
        r = max(bad, key=lambda r: r["need_s"] - r["have_s"]); s = r["a"] if (r["a"]["vel_midi"] < r["b"]["vel_midi"] and r["a"]["kind"] == "hit" and r["a"]["t"] >= 0) else r["b"]
        if not s["ids"]: return d
        nid = s["ids"][0]; byid = {n["id"]: n for n in d["notes_all"]}; st = state.setdefault(nid, dict(step=0))
        if redeal and nid in byid and pre_step(byid[nid], st, Ladder(K, d), "hand shift time", log, 0, "shift table", "shift table"): log[-1]["why"] = f"{r['frm']} -> {r['to']}: the tip {r['dist_m']} m in {r['have_s']} s, needs {r['need_s']} s"; continue
        st.clear(); st.update(step=3)
        log.append(dict(id=nid, ids=s["ids"], t=round(s["t"], 4), hand=r["hand"], piece=s["piece"], vel=s["vel_midi"], limit="hand shift time", rule="h cut", stage="shift table",
                        why=f"{r['frm']} -> {r['to']}: the tip {r['dist_m']} m, the wrist {r['wrist_dist_m']} m in {r['have_s']} s; a minimum-jerk shift under the end-point caps needs {r['need_s']} s (the wrist would peak at {r['peak_speed_m_s']} m/s, {r['peak_accel_m_s2']} m/s2)"))
    return targets(K, C, state, DP)


# ---------------------------------------------------------------- one solve + every check
def kit_state(K, d, M, fps=30):
    """the kit's own reactions (the sibling drum_perf.main's damped oscillators, restated: cymbals swing, drums dip), per render frame, for every piece of this layout"""
    DP = d["DP"]; kh = {p["id"]: [] for p in K.PIECES}
    for n in d["all_notes"]:
        if n["piece"] in kh: kh[n["piece"]].append((n["tc"], n["vel"] / 127.0 * (0.35 if n.get("art", {}).get("kind") == "sweep" and 0 < n["art"]["i"] < n["art"]["n"] - 1 else 1.0)))
    out = []
    for f in range(M):
        t = f / fps; ks = {}
        for p in K.PIECES:
            hits = kh[p["id"]]; pid = p["id"]
            if p["kind"] == "cymbal":
                amp, fr, dc = (0.045, 4.5, 0.12) if pid == K.HAT else (0.07, 1.3, 0.9) if p["role"] == "time" else (0.26 * 0.203 / p["r"], 1.7 * 0.203 / p["r"], 0.75)
                u = K.toward(p, K.SHOULDER[K.LEAD]); axis = np.cross(p["n"], u); ang = -DP.osc(hits, t, amp, fr, dc); wob = DP.osc(hits, t, amp * 0.3, fr * 2.3, dc * 0.6); rv = axis * ang + u * wob; ks[pid] = [round(float(v), 4) for v in rv] + [0.0]
            elif p["kind"] == "drum": ks[pid] = [0, 0, 0, round(-DP.osc(hits, t, 0.004 if p["r"] > 0.19 else 0.007, 9.0, 0.06, "cos"), 5)]
            else: ks[pid] = [0, 0, 0, round(-DP.osc(hits, t, 0.006, 7.0, 0.07, "cos"), 5)]
        out.append(ks)
    return out


def end_points(P, perfs, foot_events):
    """C-END-1 per arm (tip, wrist, knuckles) and for the feet (ankle, toe tip)"""
    N = P["N"]; out = {}
    for h in "LR":
        pf = perfs[h]; pts = {f"shoulder.{h}": pf["pts"]["S"], f"elbow.{h}": pf["pts"]["E"], f"wrist.{h}": pf["pts"]["W"], f"hand.{h}": pf["knuckle"]}; con = {}
        if "stick" in pf: pts[f"tip.{h}"] = pf["stick"]["tip"]; con[f"tip.{h}"] = [int(c) for c in pf["contacts"]]
        out[h] = EPT.check(pts, con)
    pts = {}; con = {}
    for s in "LR": pts[f"ankle.{s}"] = P["legs"][s]["ankle"]; pts[f"toe.{s}"] = P["legs"][s]["toe_tip"]; con[f"ankle.{s}"] = con[f"toe.{s}"] = foot_events.get(s, [])
    out["feet"] = EPT.check(pts, con); return out


def solve(K, d, grips, ident, title, audio, paths=None, write_render=None, verbose=False):
    """-> dict(R, P, perfs, EP, rows, ...). paths None = nothing is written (a loop pass)"""
    t0 = time.time(); rs = d["resticked"]; P = FB.plan_drums(grips, tool_max=K.BAND[1], d=d, verbose=verbose, do_restick=False); d["resticked"] = rs; N = P["N"]; P["bpm"] = 60.0 / P["beat_s"]; DP = d["DP"]; perfs = {}; R_arm = {}
    for h in "LR":
        a = P["arms"][h]; pl, out, rig, S = a["pl"], a["out"], a["rig"], a["S"]
        ev = [dict(f=int(round(s["t"] * HZ)), f_end=int(round(s["t_end"] * HZ)) if s["kind"] == "sweep" else None, t=round(s["t"], 4), vel=s["vel"], piece=s["piece"], zone=s["zone"], type=s["kind"], ids=s.get("ids")) for s in S if 0 <= s["t"] * HZ < N]
        cont = [e["f"] for e in ev] + [int(round(n["tc"] * HZ)) for n in d["notes"][h] if 0 <= n["tc"] * HZ < N]
        perf = bake.assemble(rig, out, pl["W"], pl["Hm"], pl["curls"], 0.0, None, "drums", f"{ident}_{h}", W_raw=pl["W_raw"], stick=dict(grip=pl["grip"], alpha=pl["alpha"], beta=pl["beta"]), thumb_abd=pl["grip"].thumb_abd, events=ev, contacts=cont,
                             mode=pl["T"]["mode"].copy(), extra=dict(env={}, bpm=P["bpm"], lam=pl["lam"]))
        R = checks.run(perf); perf["env"] = dict(kit=K, DP=DP); R = checks.grip_checks(perf, pl, R); perfs[h] = perf; R_arm[h] = R
    R_sync, rows = BK.drum_sync(P, perfs); ped = P["ped"]; ks, hs = P["feet"]["kick_side"], P["feet"]["hat_side"]
    fe = {ks: [int(round(n["tc"] * HZ)) for n in ped["kicks"] if 0 <= n["tc"] * HZ < N] + [int(round(t * HZ)) for t in P["feet"]["kick_idle_beats"] if 0 <= t * HZ < N],
          hs: [int(round(t * HZ)) for t in P["feet"]["taps"]] + [int(round(n["tc"] * HZ)) for n in d["all_notes"] if n["note"] in (42, 44, 46) and 0 <= n["tc"] * HZ < N]}
    EP = end_points(P, perfs, fe); over = {k: v.pop("over") for k, v in EP.items()}
    for h in "LR": R_arm[h]["C-END-1"] = EP[h]
    orig = BK.run
    def run_with_feet(*a, **k): Rb, aux = orig(*a, **k); Rb["C-END-1"] = EP["feet"]; return Rb, aux
    C = d["chart"]; M = len(range(0, N, EV)); kst = kit_state(K, d, M)
    extra = dict(title=title, kit=K.export(), chart=dict(bars=d["bars"], lead=d["lead"], bar_s=d["bar_s"]), audio=audio, hits=[],
                 pedals=dict(beater=rl(ped["beater"], 2), hat=rl(ped["hat"], 3), kick_plate=rl(P["feet"]["plate_deg"][ks], 2), hat_plate=rl(P["feet"]["plate_deg"][hs], 2), taps=P["feet"]["taps"], kick_idle=P["feet"]["kick_idle_beats"], kick_foot=ks + "F", hat_foot=hs + "F"),
                 kit_state=kst, hat30=rl(ped["hat"][::EV], 4), resticked=d["resticked"], grip={h: P["arms"][h]["grip"].report for h in "LR"}, layout=kitdata.describe(K))
    BK.run = run_with_feet
    try: R, delta, aux = FB.finish(P, "drums", ident, perfs, R_arm, R_sync, rows, fe, extra, ds="drums2", paths=paths or dict(drive="/dev/null", inspector="/dev/null"))
    finally: BK.run = orig
    if write_render:
        Rr = dict(fps=30, bone_names=AR.NAMES, kit=K.export(), chart=dict(bars=d["bars"], lead=d["lead"], bar_s=d["bar_s"]), hat=rl(ped["hat"][::EV], 4), beater=rl(ped["beater"][::EV], 3), kick_plate=rl(P["feet"]["plate_deg"][ks][::EV], 3),
                  hat_plate=rl(P["feet"]["plate_deg"][hs][::EV], 3), kit_state=kst, frames=len(delta), delta=delta, sticks=BB.sticks_30(perfs))
        json.dump(Rr, open(write_render, "w"), separators=(",", ":"))
    return dict(R=R, P=P, perfs=perfs, EP=EP, over=over, rows=rows, fe=fe, seconds=round(time.time() - t0))


def violations(S):
    """-> [dict(limit, check, limb (L, R, feet side or None), frames)] for every hard limit broken (the ladder's line, + C-END-1)"""
    R, perfs, out = S["R"], S["perfs"], []
    for h in "LR":
        for k, name in ARM_PHYS.items():
            r = R[f"{k} arm {h}"]
            if k == "C-IK-2": fr = np.nonzero(perfs[h]["flags"]["unattained_m"] > 0.002)[0].tolist()
            else: fr = [] if r["ok"] else list(r.get("frames", []))
            if fr: out.append(dict(limit=name, check=f"{k} arm {h}", limb=h, frames=[int(f) for f in fr]))
    for k, name in BODY_PHYS.items():
        r = R.get(k)
        if r is None or r["ok"] or not r.get("frames"): continue
        if k == "C-END-1 body":
            for s in "LR":
                fr = np.nonzero(S["over"]["feet"][f"ankle.{s}"] | S["over"]["feet"][f"toe.{s}"])[0]
                if len(fr): out.append(dict(limit=name, check=k, limb=s + "F", frames=[int(f) for f in fr]))
        else: out.append(dict(limit=name, check=k, limb=None, frames=[int(f) for f in r["frames"]], pairs=list((r.get("pairs") or {}).keys())))
    return out


def phys(V):
    ph = {}
    for v in V: ph[v["limit"]] = ph.get(v["limit"], 0) + len(v["frames"])
    return ph


def metrics(S, d):
    R = S["R"]; V = violations(S); m = dict(frames=S["P"]["N"], phys_frames=phys(V), phys_frames_total=sum(phys(V).values()), phys_by_check={v["check"]: len(v["frames"]) for v in V}, solve_s=S["seconds"])
    m["sync"] = dict(notes=R["sync"]["notes"], ok_by_limb=R["sync"]["ok_by_limb"], tip_miss_mm_max=R["sync"]["tip_miss_mm_max"]); m["end_points"] = {**S["EP"]["L"]["by"], **S["EP"]["R"]["by"], **S["EP"]["feet"]["by"]}
    worst = {}
    for part in ("arm L", "arm R", "body"):
        for k, v in R[f"C-CONT-1 {part}"]["peak_vs_ceiling"].items(): worst[f"{part} {k}"] = round(v[0] / v[1], 2)
    wk = max(worst, key=worst.get); m["speed_worst_vs_hard_cap"] = dict(channel=wk, ratio=worst[wk]); m["reach_max"] = {h: R[f"C-IK-2 arm {h}"]["reach_ratio_max"] for h in "LR"}
    m["trunk_range"] = {k: [round(float(S["P"]["ch"][k].min()), 1), round(float(S["P"]["ch"][k].max()), 1)] for k in ("lean", "side", "turn")}
    col = {}
    for part in ("arm L", "arm R", "body"):
        for k, v in (R[f"C-COL-1 {part}"].get("pairs") or {}).items(): col[f"{k} ({part})" if part != "body" else k] = dict(frames=v["frames"], max_mm=v["max_mm"])
    m["collisions"] = col; m["comfort_pct_outside"] = {**{f"arm {h}": R[f"C-JT-2 arm {h}"]["pct_outside_comfort"] for h in "LR"}, "body": R["C-JT-2 body"]["pct_outside_comfort"]}
    m["clamp_frames"] = {h: R[f"C-IK-3 arm {h}"]["clamp_frames"] + R[f"C-IK-3 arm {h}"]["shoulder_elbow_limit_clamps"] for h in "LR"}
    m["grip"] = {h: dict(d_alpha_median=R[f"C-GRIP-4 arm {h}"].get("d_alpha_median_deg"), share=R[f"C-GRIP-4 arm {h}"].get("share_mean"), lift_vs_velocity_r=R[f"C-GRIP-5 arm {h}"].get("r"), tip_speed_max=R[f"C-GRIP-5 arm {h}"].get("tip_speed_max_m_s")) for h in "LR"}
    m["checks_failing"] = sorted(k for k, v in R.items() if not v["ok"] and not k.startswith("C-JT-2")); m["checks_total"] = len(R)
    m["feet"] = dict(slide_mm=R["C-FOOT-1 body"]["slide_max_mm"], ranges=R["C-FOOT-2 body"]["ranges_deg"], taps=len(S["P"]["feet"]["taps"]), kick_idle=len(S["P"]["feet"]["kick_idle_beats"]), dead_limb_min=R["C-IDLE-2 body"]["rms_deg_s_min_per_limb"])
    return m


def step_down(n, limit, log, n_frames, check, stage="loop", lad=None):
    st = n["_state"]
    if pre_step(n, st, lad, limit, log, n_frames, check, stage): return                # R-448 a / b first (2026-11-20)
    st["step"] = st.get("step", 0) + 1
    if st["step"] == 2 and not n.get("art"): st["step"] = 3          # a plain stroke has no simpler gesture than the soft one it already is: softer -> cut. Sweeps and rolls keep the middle step (single strokes)
    rule = {1: "f played softer", 2: "g simpler gesture" + (f": {n['art']['kind']} -> single strokes" if n.get("art") else ": a low wrist tap"), 3: "h cut"}[st["step"]]
    log.append(dict(id=n["id"], t=round(n["tc"], 4), bar=n["bar"], limb=n["limb"], piece=n["piece"], note=n["note"], vel=n.get("vel_midi", n["vel"]), limit=limit, check=check, frames=n_frames, rule=rule, stage=stage))


def loop(K, C, grips, ident, title, audio, state, log, DP, verbose=True):
    """solve, check, step down, until no frame breaks a hard limit -> (the last solve, its targets, the history, the first solve's metrics)"""
    hist = []; first = None
    for it in range(MAX_IT + 1):
        d = shift_table(K, C, state, log, DP, redeal=REDEAL)
        S = solve(K, d, grips, ident, title, audio); V = violations(S); miss = [r for r in S["rows"] if not r["ok"]]
        if first is None: first = S
        hist.append(dict(pass_=it, phys_frames=phys(V), not_struck=len(miss), changes=0, solve_s=S["seconds"]))
        if verbose: print(f"    pass {it}: over a hard limit {phys(V)}, not struck {len(miss)}, {S['seconds']} s", flush=True)
        if (not V and not miss) or it == MAX_IT: return S, d, hist
        notes = {n["id"]: n for n in d["notes_all"] if n["limb"] and 0 <= n["tc"] < C["dur"] + 0.5 and not n.get("merged")}; done = set(); ch = 0; unresolved = []
        hist[-1]["where"] = [dict(check=v["check"], limb=v["limb"], pairs=v.get("pairs"), runs=[[int(r[0]), int(r[-1])] for r in np.split(np.array(sorted(v["frames"])), np.nonzero(np.diff(np.array(sorted(v["frames"]))) > 12)[0] + 1)][:6]) for v in V]
        for n in notes.values(): n["_state"] = state.setdefault(n["id"], dict(step=0))
        lad = Ladder(K, d) if REDEAL else None
        def pay(limbs, f0, f1, limit, check, nfr):
            nonlocal ch
            tm = 0.5 * (f0 + f1) / HZ; cand = [n for n in notes.values() if n["limb"] in limbs and not (n.get("art", {}).get("kind") == "sweep" and n["art"]["i"] > 0) and n["id"] not in done and n["_state"]["step"] < 3]
            if not cand: unresolved.append(dict(limit=limit, check=check, frames=[f0, f1], n=nfr)); return
            n = min(cand, key=lambda n: (abs(n["tc"] - tm) if not (f0 / HZ - 0.02 <= n["tc"] <= f1 / HZ + 0.02) else 0.0, n["vel"]))
            if not (f0 / HZ - 0.4 <= n["tc"] <= f1 / HZ + 0.4): unresolved.append(dict(limit=limit, check=check, frames=[f0, f1], n=nfr)); return      # no note of that limb within 0.4 s: not a note's doing (a waiting posture, the layout): reported, never paid for by a bystander
            done.add(n["id"]); step_down(n, limit, log, nfr, check, lad=lad); ch += 1
        for v in V:
            fr = np.array(sorted(v["frames"])); limbs = (v["limb"],) if v["limb"] else ("L", "R")
            if v["limb"] is None and v.get("pairs") and all(("thigh" in p or "shin" in p) and "stick" not in p for p in v["pairs"]): limbs = ("LF", "RF")
            for run in np.split(fr, np.nonzero(np.diff(fr) > 12)[0] + 1): pay(limbs, int(run[0]), int(run[-1]), v["limit"], v["check"], int(len(run)))
        for r in miss: pay((r["limb"],), 4 * r["frame"], 4 * r["frame"], "not struck on its frame", "sync", 1)
        for nid in [k for k, v in state.items() if isinstance(v, dict) and v.get("step", 0) == 0 and not v.get("pre")]: state.pop(nid)
        for n in notes.values(): n.pop("_state", None)
        hist[-1]["changes"] = ch; hist[-1]["unresolved"] = unresolved
        if ch == 0: return S, d, hist
    return S, d, hist


def fates(C, d, log):
    """every MIDI note of the window -> played / misplayed / cut (+ the limit), or a layer"""
    rows = []; by = {}
    for e in log: by.setdefault(e["id"], []).append(e)
    rs = {(x["t"], x["piece"], x["hand"]): x["change"] for x in d["resticked"]}; cnt = dict(midi_notes=0, layers=0, played=0, misplayed=0, cut=0, misplayed_by={}, cut_by={}, misplayed_how={})
    for n in d["notes_all"]:
        if not (0 <= n["tc"] < C["dur"]): continue
        cnt["midi_notes"] += 1; nt = n.get("note_was", n["note"]); r = dict(midi=n["id"], tick=n["tick"], note=nt, name=C["names"].get(str(nt), str(nt)), t=round(n["tc"], 4), bar=n["bar"], vel=n.get("vel_midi", n["vel"]), piece=n.get("piece_was", n["piece"]))
        ev = by.get(n["id"], []); fold = n.get("folded")
        if n["piece"] is None: r.update(fate="layer", why=n.get("why")); cnt["layers"] += 1
        elif n.get("cut") or (fold and by.get(fold, [{}])[-1].get("rule") == "h cut"):
            e = (ev or by.get(fold))[-1]; r.update(fate="cut", limit=e["limit"], limb=n.get("limb_was")); cnt["cut"] += 1; cnt["cut_by"][e["limit"]] = cnt["cut_by"].get(e["limit"], 0) + 1
        elif n["limb"] is None and not fold: r.update(fate="cut", limit=n.get("limit", "two hands"), why=n.get("why"), stage="the deal"); cnt["cut"] += 1; cnt["cut_by"][r["limit"]] = cnt["cut_by"].get(r["limit"], 0) + 1
        elif n.get("subst"):
            e = ev[-1] if ev else {}; r.update(fate="misplayed", how=f"nearest piece: {n['piece']} (R-448)", played_piece=n["piece"], limit=e.get("limit"), limb=n["limb"]); cnt["misplayed"] += 1; cnt["substituted"] = cnt.get("substituted", 0) + 1
            cnt["misplayed_by"][e.get("limit")] = cnt["misplayed_by"].get(e.get("limit"), 0) + 1; cnt["misplayed_how"]["nearest piece"] = cnt["misplayed_how"].get("nearest piece", 0) + 1
        elif n.get("redealt") and (not ev or ev[-1]["rule"].startswith("a")):
            e = ev[-1] if ev else {}; r.update(fate="played", how="re-dealt: the other hand plays it (R-448)", limit=e.get("limit") or n.get("redeal_why"), limb=n["limb"], limb_was=n.get("limb_was")); cnt["played"] += 1; cnt["redealt"] = cnt.get("redealt", 0) + 1
        elif ev or fold:
            e = (ev or by.get(fold))[-1]; how = "softer" if e["rule"].startswith("f") else "simpler gesture"; r.update(fate="misplayed", how=how, limit=e["limit"], limb=n["limb"] or n.get("limb_was")); cnt["misplayed"] += 1
            cnt["misplayed_by"][e["limit"]] = cnt["misplayed_by"].get(e["limit"], 0) + 1; cnt["misplayed_how"][how] = cnt["misplayed_how"].get(how, 0) + 1
        else:
            c_ = rs.get((round(n["tc"], 3), n["piece"], n["limb"])); r.update(fate="played", limb=n["limb"]); cnt["played"] += 1
            if n.get("merged"): r["how"] = n.get("merge_how", "one stroke for two zones of one piece")
            if c_: r["how"] = "the other hand plays it" if c_.startswith("moved") else "one stroke for a unison on one piece"; r["limb"] = ("L" if n["limb"] == "R" else "R") if c_.startswith("moved") else n["limb"]
        rows.append(r)
    den = cnt["midi_notes"] - cnt["layers"]
    for k in ("played", "misplayed", "cut"): cnt["pct_" + k] = round(100.0 * cnt[k] / max(1, den), 1)
    return cnt, rows


def hits_of(rows):
    return [dict(t=r["t"], limb=r.get("limb"), piece=r["piece"], note=r["note"], vel=r["vel"], id=r["midi"], fate=r["fate"], how=r.get("how"), limit=r.get("limit")) for r in rows if r["fate"] != "layer" and r.get("limb")]

# midi2motion: audio_for / run / solve_write / old_clip (the lab's closure-clip runner, audio cut and command line) were dropped
