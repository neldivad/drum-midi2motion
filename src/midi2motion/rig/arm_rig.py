#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/arm_rig.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""arm_rig.py: one right arm + hand + drumstick built to STANDARD.md, as a DRIVING SKELETON (numpy, 120 Hz). Not a patch of the
sibling rig.py: a new solver that reads rig.yaml (S-0.1) and the android's rest pose (by path, read-only).

The chain, solved in this order (S-IK-1): clavicle (S-IK-7) -> shoulder swing + twist -> elbow hinge -> forearm twist -> wrist swing.

    rig = ArmRig(T_chest, body_caps)            # the torso is frozen: its chest transform and its capsules
    out = rig.solve(W, Hm)                      # W (N,3) wrist targets, Hm (N,3,3) hand targets (columns x, y = forward, z = back of hand), character space
    out["ch"]                                   # every joint channel in degrees (the inspector's curves), out["pts"], out["mats"], out["flags"]

Rules built in:
- every joint is swing/twist, never Euler (S-JT-1): the shoulder is a swing direction + humeral twist, the elbow a 1-DoF hinge, the hand's
  rotation relative to the forearm is decomposed into TWIST about the forearm axis (= pronation, carried by the forearm and its twist bones,
  S-TW-1) and a 2-DoF SWING limited by an ellipse per quadrant; the wrist keeps at most +-10 deg of twist;
- the elbow's swivel phi is an explicit channel, planned for the WHOLE clip (phi_plan.py) from a natural-elbow prior, joint comfort and a
  collision barrier; never searched per frame (S-IK-3/8);
- targets are never moved by the solver. A target beyond 0.97 x reach is REPORTED; the arm saturates smoothly short of straight (S-IK-4),
  the miss is measured; an orientation the wrist cannot take is clamped on the ellipse and REPORTED (S-IK-5);
- forward kinematics from the stored channels is the single source of every position (so the checks audit what is stored).

Frames. Chest coordinates = the armature's rest space (x = the character's left, y = back, z = up): the chest transform maps them to
character space. Upper arm frame U: y along the bone, z = the direction the elbow bends toward, x = the hinge axis. Hand frame: y forward,
z = the back of the hand, x = y x z. Angles: degrees in channels, radians inside.
"""
import json, math, pathlib
import numpy as np, yaml
from scipy.spatial.transform import Rotation as Rot

LAB = pathlib.Path(__file__).resolve().parent / "data"          # midi2motion: rig.yaml, drumkit.yaml and the swivel prior table are package data (was the wrapped lab folder)
CFG = yaml.safe_load(open(LAB / "rig.yaml"))
REST_J = json.load(open((LAB / CFG["rest"]).resolve()))
NAMES = [b["name"] for b in REST_J["bones"]]
REST = {b["name"]: np.array(b["matrix"]) for b in REST_J["bones"]}; RINV = {n: np.linalg.inv(M) for n, M in REST.items()}
HEAD = {b["name"]: np.array(b["head"]) for b in REST_J["bones"]}; TAIL = {b["name"]: np.array(b["tail"]) for b in REST_J["bones"]}
L_UP, L_FO = REST_J["arm"]["L_UP"], REST_J["arm"]["L_FO"]; L_ARM = L_UP + L_FO
FINGERS = ("thumb", "index", "middle", "ring", "pinky"); HZ = CFG["solve_hz"]
DOWN, FWD = np.array([0, 0, -1.0]), np.array([0, -1.0, 0])
rad, deg = np.radians, np.degrees


def unit(v): return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-12)
def dot(a, b): return (a * b).sum(-1)
def rx(a): a = np.asarray(a, float); c, s, o, z = np.cos(a), np.sin(a), np.ones_like(a), np.zeros_like(a); return np.stack([np.stack([o, z, z], -1), np.stack([z, c, -s], -1), np.stack([z, s, c], -1)], -2)
def ry(a): a = np.asarray(a, float); c, s, o, z = np.cos(a), np.sin(a), np.ones_like(a), np.zeros_like(a); return np.stack([np.stack([c, z, s], -1), np.stack([z, o, z], -1), np.stack([-s, z, c], -1)], -2)
def rz(a): a = np.asarray(a, float); c, s, o, z = np.cos(a), np.sin(a), np.ones_like(a), np.zeros_like(a); return np.stack([np.stack([c, -s, z], -1), np.stack([s, c, z], -1), np.stack([z, z, o], -1)], -2)
def rv(v): v = np.asarray(v, float); return Rot.from_rotvec(v.reshape(-1, 3)).as_matrix().reshape(v.shape[:-1] + (3, 3))
def cols(x, y, z): return np.stack([x, y, z], -1)


def minrot(a, b):
    """the smallest rotation taking unit a to unit b (batch on b)"""
    ax = np.cross(np.broadcast_to(a, b.shape), b); s = np.linalg.norm(ax, axis=-1); c = dot(a, b)
    return rv(ax / (s[..., None] + 1e-12) * np.arctan2(s, c)[..., None])


def hand_matrix(d, up):
    y = unit(np.asarray(d, float)); z = np.asarray(up, float); z = unit(z - y * dot(z, y)[..., None]); return cols(np.cross(y, z), y, z)


def seg_seg(p1, q1, p2, q2):
    """closest distance between segments, batched (Ericson). -> d, c1, c2"""
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2; a, e, f = dot(d1, d1), dot(d2, d2), dot(d2, r); c, b = dot(d1, r), dot(d1, d2); den = a * e - b * b
    s = np.where(den > 1e-12, np.clip((b * f - c * e) / np.where(den > 1e-12, den, 1), 0, 1), 0.0); t = (b * s + f) / np.where(e > 1e-12, e, 1)
    s = np.where(t < 0, np.clip(-c / np.where(a > 1e-12, a, 1), 0, 1), np.where(t > 1, np.clip((b - c) / np.where(a > 1e-12, a, 1), 0, 1), s)); t = np.clip(t, 0, 1)
    c1, c2 = p1 + d1 * s[..., None], p2 + d2 * t[..., None]; return np.linalg.norm(c1 - c2, axis=-1), c1, c2


def band_pen(x, lim, wc, wh, guard=0.0):
    """comfort is free inside the band and quadratic outside it; past the hard limit (less a guard band, for the planner) it gets steep (x and limits in degrees)"""
    (cl, ch), (hl, hh) = lim["comfort"], lim["hard"]; hl, hh = hl + guard, hh - guard
    ec = np.maximum(0, cl - x) / max(cl - hl, 5.0) + np.maximum(0, x - ch) / max(hh - ch, 5.0); eh = (np.maximum(0, hl - x) + np.maximum(0, x - hh)) / 5.0
    return wc * ec ** 2 + wh * eh ** 2


def wrist_ellipse(flex, dev, which):
    """(f/F)^2 + (d/D)^2 per quadrant; flex + = palmar flexion, dev + = ulnar (degrees). <= 1 is inside"""
    L = CFG["limits"]["wrist"][which]; F = np.where(flex >= 0, L["flex"], L["ext"]); D = np.where(dev >= 0, L["ulnar"], L["radial"])
    return (flex / F) ** 2 + (dev / D) ** 2


class ArmRig:
    def __init__(self, T_chest=None, body_caps=(), side=CFG["side"]):
        self.s = side; self.sg = sg = 1.0 if side == "L" else -1.0; self.T = np.eye(4) if T_chest is None else np.asarray(T_chest, float); self.Ti = np.linalg.inv(self.T)
        self.Rc = self.T[..., :3, :3]; self.LAT = np.array([sg, 0, 0.0]); self.moving = self.T.ndim == 3      # full body: T (N,4,4), the chest per solved frame (the trunk moves; targets stay in character space)
        self.clav0 = HEAD[f"shoulder.{side}"]; self.sh0 = HEAD[f"upper_arm.{side}"]                    # chest coordinates = rest space
        self.U0 = cols(np.array([-1.0, 0, 0]), DOWN, FWD)                                              # the arm hanging, elbow bending forward: zero swing, zero twist
        self.NLOC = cols(np.array([0, 0, sg]), np.array([0, 1.0, 0]), np.array([-sg, 0, 0]))           # the neutral hand in the forearm's hinge frame: thumb toward the bend side
        self.body = [(n, self.to_chest(a), self.to_chest(b), r) for n, a, b, r in body_caps]           # frozen torso capsules, in chest coordinates
        self.lmax = CFG["reach"]["max_ext"] * L_ARM; self.lflag = CFG["reach"]["flag"] * L_ARM
        self.lmin = math.sqrt(L_UP ** 2 + L_FO ** 2 - 2 * L_UP * L_FO * math.cos(math.radians(180 - CFG["reach"]["min_elbow_fold_deg"])))
        hp = np.array(CFG["swivel"]["head_point"], float); self.head_pt = HEAD["chest"] + np.array([hp[0], hp[1], hp[2]])
        self.prior_table = None; p = LAB / CFG["swivel"]["prior_table"]
        if p.exists(): self.prior_table = json.load(open(p))
        # fingers: the sign that curls each bone toward the palm (as the android's own calibration)
        PN = np.array(REST_J["arm"]["PN"]); AD = np.array(REST_J["arm"]["AD"]); pn = np.array([PN[0] * sg, 0, PN[2]]); self.CURL = {}
        for fn in FINGERS:
            for k in (1, 2, 3):
                b = f"{fn}.{k:02d}.{side}"; R = REST[b][:3, :3]; ax, y = R[:, 0], R[:, 1]; tgt = pn if fn != "thumb" else unit(pn + np.array([AD[0] * sg * 0.6, 0.6, 0]))
                self.CURL[b] = 1.0 if (rv(ax * 0.3) @ y) @ tgt > (rv(-ax * 0.3) @ y) @ tgt else -1.0

    # ---- spaces
    def to_chest(self, p):
        p = np.asarray(p, float); return (np.einsum("nij,nj->ni", self.Ti[:, :3, :3], p) + self.Ti[:, :3, 3]) if self.moving else p @ self.Ti[:3, :3].T + self.Ti[:3, 3]
    def to_char(self, p):
        p = np.asarray(p, float); return (np.einsum("nij,nj->ni", self.Rc, p) + self.T[:, :3, 3]) if self.moving else p @ self.Rc.T + self.T[:3, 3]
    def rot_chest(self, M): return np.einsum("nji,njk->nik", self.Rc, M) if self.moving else np.einsum("ij,njk->nik", self.Rc.T, M)
    def rot_char(self, M): return np.einsum("nij,njk->nik", self.Rc, M) if self.moving else np.einsum("ij,njk->nik", self.Rc, M)

    # ---- S-IK-7: the shoulder girdle
    def shoulder(self, elev, prot):
        """clavicle elevation / protraction (rad) -> the shoulder joint in chest coordinates, and the clavicle's rotation"""
        R = rz(-self.sg * np.asarray(prot)) @ ry(-self.sg * np.asarray(elev)); return self.clav0 + np.einsum("...ij,j->...i", R, self.sh0 - self.clav0), R

    # ---- S-IK-1/2: analytic two-bone IK with the swivel as an explicit input
    def reach(self, S, W):
        d = W - S; L = np.linalg.norm(d, axis=-1); u = d / (L[..., None] + 1e-12); k = self.lmax - self.lflag
        Lc = np.where(L > self.lflag, self.lflag + k * (1 - np.exp(-(L - self.lflag) / k)), L); km = 0.004
        Lc = np.where(L < self.lmin + km, self.lmin + km * np.exp((np.minimum(L, self.lmin + km) - self.lmin - km) / km), Lc); return u, L, Lc

    def elbow(self, S, W, phi):
        u, L, Lc = self.reach(S, W); a = (L_UP ** 2 - L_FO ** 2 + Lc ** 2) / (2 * Lc); rho = np.sqrt(np.maximum(L_UP ** 2 - a ** 2, 0.0))
        dp = DOWN - u * dot(u, DOWN)[..., None]; nd = np.linalg.norm(dp, axis=-1); dp = dp / (nd[..., None] + 1e-12); ow = self.sg * np.cross(u, dp)   # + phi swings the elbow outward
        E = S + u * a[..., None] + rho[..., None] * (np.cos(phi)[..., None] * dp + np.sin(phi)[..., None] * ow)
        return E, S + u * Lc[..., None], dict(L=L, Lc=Lc, ref_ok=nd)

    def swivel_of(self, S, E, W):
        u = unit(W - S); dp = unit(DOWN - u * dot(u, DOWN)[..., None]); ow = self.sg * np.cross(u, dp); e = E - S; e = e - u * dot(e, u)[..., None]; return np.arctan2(dot(e, ow), dot(e, dp))

    # ---- joints from a solved S, E, W (+ the hand target): swing/twist everywhere
    def analyze(self, S, E, W, Hm=None):
        yu, yf = unit(E - S), unit(W - E); x = unit(np.cross(E - S, W - S)); zu = np.cross(x, yu); sg = self.sg
        ch = dict(elbow=np.arctan2(np.linalg.norm(np.cross(yu, yf), axis=-1), dot(yu, yf)), sh_flex=np.arctan2(dot(yu, FWD), dot(yu, DOWN)), sh_abd=np.arcsin(np.clip(dot(yu, self.LAT), -1, 1)))
        M = minrot(DOWN, yu); xr = np.einsum("...ij,j->...i", M, self.U0[:, 0]); zr = np.einsum("...ij,j->...i", M, self.U0[:, 2])
        ch["sh_twist"] = sg * np.arctan2(-dot(x, zr), dot(x, xr))                                      # + internal
        if Hm is not None:
            F0 = cols(x, yf, np.cross(x, yf)); Rrel = np.swapaxes(F0, -1, -2) @ Hm @ self.NLOC.T; sh = Rrel.shape[:-2]
            q = Rot.from_matrix(Rrel.reshape(-1, 3, 3)).as_quat().reshape(sh + (4,)); tau = 2 * np.arctan2(q[..., 1], q[..., 3]); tau = (tau + np.pi) % (2 * np.pi) - np.pi
            sw = Rot.from_matrix((ry(-tau) @ Rrel).reshape(-1, 3, 3)).as_rotvec().reshape(sh + (3,))
            ch["tau_raw"] = tau; ch["sw_raw"] = sw
        return ch

    def split_wrist(self, tau, sw):
        """the hand's rotation on the forearm -> pronation (the forearm takes it), a wrist swing inside the ellipse, the leftover twist (<= 10 deg) -> channels + clamp flags"""
        sg = self.sg; Lm = CFG["limits"]; p = sg * tau; lo, hi = rad(Lm["pron"]["hard"][0]), rad(Lm["pron"]["hard"][1]); pc = np.clip(p, lo, hi); dlt = sg * (p - pc)   # leftover about the forearm axis
        sw = np.einsum("...ij,...j->...i", ry(dlt), sw); wl = rad(Lm["wrist_twist"]["hard"][1]); wt = np.clip(dlt, -wl, wl)
        flex, devu = -sg * deg(sw[..., 2]), -deg(sw[..., 0]); e = wrist_ellipse(flex, devu, "hard"); k = np.where(e > 1, 1 / np.sqrt(np.maximum(e, 1e-9)), 1.0)
        return dict(pron=pc, wrist_twist=sg * wt, wrist_flex=rad(flex * k), wrist_dev=rad(devu * k)), dict(twist_clamp=np.abs(dlt) > wl + 1e-9, swing_clamp=e > 1 + 1e-9, twist_spill=np.abs(dlt) > 1e-9, ellipse=e)

    # ---- forward kinematics from the stored channels (radians): the one source of positions and matrices
    def fk(self, ch):
        sg = self.sg; S, Rcl = self.shoulder(ch["clav_elev"], ch["clav_prot"]); fl, ab = ch["sh_flex"], ch["sh_abd"]
        d = self.LAT * np.sin(ab)[..., None] + np.cos(ab)[..., None] * (DOWN * np.cos(fl)[..., None] + FWD * np.sin(fl)[..., None])
        U = minrot(DOWN, d) @ self.U0 @ ry(sg * ch["sh_twist"]); E = S + L_UP * U[..., :, 1]; F0 = U @ rx(ch["elbow"]); W = E + L_FO * F0[..., :, 1]
        tau = sg * ch["pron"]; F = F0 @ ry(tau); sw = np.stack([-ch["wrist_dev"], np.zeros_like(tau), -sg * ch["wrist_flex"]], -1)
        H = F @ rv(sw) @ ry(sg * ch["wrist_twist"]) @ self.NLOC
        return dict(S=S, E=E, W=W, U=U, F0=F0, F=F, H=H, Rcl=Rcl, tau=tau)

    # ---- S-IK-3: the natural-elbow prior (a lookup fitted on CMU arms where it has samples, Kim/Rosen's rule elsewhere)
    def prior_rule(self, S, W):
        u = unit(W - S); h = self.head_pt - S; e = -(h - u * dot(h, u)[..., None]); dp = unit(DOWN - u * dot(u, DOWN)[..., None]); ow = self.sg * np.cross(u, dp)
        return np.arctan2(dot(e, ow), dot(e, dp))                                                    # the elbow lies in the plane shoulder-wrist-head, on the far side from the head

    def prior(self, S, W):
        r = self.prior_rule(S, W); T = self.prior_table
        if not T: return r
        r = r + rad(T.get("rule_offset_deg", 0.0))                                                  # the rule, calibrated: its mean error against the CMU arms
        x = (W - S) * np.array([self.sg, 1, 1]) / L_ARM; c = np.array(T["centres"]); v = rad(np.array(T["phi_deg"])); n = np.array(T["n"]); h = T["kernel"]   # table is in the lateral-forward-up frame of a normalised arm
        d2 = ((x[..., None, :] - c) ** 2).sum(-1); k = np.exp(-0.5 * d2 / h ** 2) * n; ws = k.sum(-1); r0 = T.get("rule_weight", 8.0)
        return (np.einsum("...k,k->...", k, v) + r0 * r) / (ws + r0)

    # ---- the per-frame cost of a swivel value (comfort + limits + torso clearance): the table phi_plan.py solves on
    def phi_cost(self, S, W, Hm, grid):
        N = len(W); G = len(grid); Sg = np.broadcast_to(S[:, None, :], (N, G, 3)); Wg = np.broadcast_to(W[:, None, :], (N, G, 3)); ph = np.broadcast_to(grid[None, :], (N, G))
        E, We, _ = self.elbow(Sg, Wg, ph); ch = self.analyze(Sg, E, We, None if Hm is None else np.broadcast_to(Hm[:, None], (N, G, 3, 3)))
        Lm, SW = CFG["limits"], CFG["swivel"]; wc, wh = SW["w_comfort"], SW["w_hard"]; C = np.zeros((N, G))
        gd = SW["guard_deg"]
        for k in ("sh_flex", "sh_abd", "sh_twist"): C += band_pen(deg(ch[k]), Lm[k], wc, wh, gd)
        if Hm is not None:
            w, fl = self.split_wrist(ch["tau_raw"], ch["sw_raw"]); p = self.sg * deg(ch["tau_raw"]); C += band_pen(p, Lm["pron"], wc, wh, gd)
            sw = ch["sw_raw"]; ec = wrist_ellipse(-self.sg * deg(sw[..., 2]), -deg(sw[..., 0]), "comfort"); C += wc * np.maximum(0, np.sqrt(ec) - 1) ** 2 + wh * 25 * np.maximum(0, np.sqrt(fl["ellipse"]) - 0.9) ** 2
        cap = CFG["capsules"]
        for n, a, b, r in self.body:
            if a.ndim == 2: a, b = a[:, None, :], b[:, None, :]                                    # a body capsule that moves in the chest frame (pelvis, thighs, head; the other arm)
            if n not in ("chest", "neck"):
                d, _, _ = seg_seg(Sg + (E - Sg) * cap["upper_arm"]["from"], E, np.broadcast_to(a, E.shape), np.broadcast_to(b, E.shape)); C += SW["w_collision"] * np.maximum(0, cap["upper_arm"]["r"] + r + 0.01 - d) ** 2 * 1e2
            d, _, _ = seg_seg(E, We, np.broadcast_to(a, E.shape), np.broadcast_to(b, E.shape)); C += SW["w_collision"] * np.maximum(0, cap["forearm"]["r"] + r + 0.01 - d) ** 2 * 1e2
        return C

    # ---- the whole clip
    def solve(self, W, Hm, S_off=None, phi=None, passes=2):
        """W (N,3), Hm (N,3,3) in character space; S_off (N,3): the shoulder girdle carried by a moving torso (torture case 7). phi: a fixed swivel plan (deg), else planned"""
        import phi_plan
        N = len(W); Wc = self.to_chest(W) - (0 if S_off is None else S_off @ self.Rc); Hc = self.rot_chest(Hm); CL = CFG["clavicle"]; grid = rad(np.arange(*CFG["swivel"]["grid"], dtype=float)); el = np.zeros(N); pr = np.zeros(N)
        for it in range(passes + 1):
            S, _ = self.shoulder(el, pr); u, L, Lc = self.reach(S, Wc); vw = np.linalg.norm(np.gradient(Wc, axis=0), axis=1) * HZ
            if phi is not None: ph = rad(np.asarray(phi, float)); pri = ph; plan = None
            else:
                pri = self.prior(S, Wc); C = self.phi_cost(S, Wc, Hc, grid); ph, plan = phi_plan.plan(pri, C, grid, vw)
            E, We, info = self.elbow(S, Wc, ph)
            if it == passes: break
            a = self.analyze(S, E, We); hel = deg(np.arccos(np.clip(dot(unit(E - S), DOWN), -1, 1)))
            el = rad(np.clip(np.maximum(0, hel - 30) * CL["elev_per_deg_above_30"], *CFG["limits"]["clav_elev"]["hard"]))
            q = np.clip((L / L_ARM - CL["prot_start"]) / (CL["prot_full"] - CL["prot_start"]), 0, 1); pr = rad(CL["prot_max"] * q * q * (3 - 2 * q))
            if N > 8: el, pr = np.clip(minjerk_fit(el, CL["smooth"]), *rad(CFG["limits"]["clav_elev"]["hard"])), np.clip(minjerk_fit(pr, CL["smooth"]), *rad(CFG["limits"]["clav_prot"]["hard"]))                # the girdle is a planned, whole-clip channel too: smooth, no lag
        ch = self.analyze(S, E, We, Hc); w, wf = self.split_wrist(np.unwrap(ch.pop("tau_raw")), ch.pop("sw_raw")); ch.update(w); ch.update(clav_elev=el, clav_prot=pr)
        Lm = CFG["limits"]; lim = {}
        for k in ("sh_flex", "sh_abd", "sh_twist", "elbow"):
            lo, hi = rad(Lm[k]["hard"][0]), rad(Lm[k]["hard"][1]); c = np.clip(ch[k], lo, hi); lim[k] = np.abs(c - ch[k]) > 1e-9; ch[k] = c
        K = self.fk(ch); ch["swivel"] = np.unwrap(self.swivel_of(K["S"], K["E"], K["W"])) if phi is None else ph
        Wt = Wc; pts = {k: self.to_char(K[k]) + (0 if S_off is None else S_off) for k in ("S", "E", "W")}
        Hw = self.rot_char(K["H"]); ori_err = deg(np.arccos(np.clip((np.einsum("nij,nij->n", Hw, Hm) - 1) / 2, -1, 1)))
        flags = dict(reach_ratio=L / L_ARM, reach_over=L > self.lflag, unattained_m=np.linalg.norm(K["W"] - Wt, axis=1), ori_err_deg=ori_err, twist_clamp=wf["twist_clamp"], swing_clamp=wf["swing_clamp"],
                     twist_spill=wf["twist_spill"], wrist_ellipse=wf["ellipse"], limit_clamp=lim, ref_weak=info["ref_ok"] < 0.15)
        return dict(ch={k: deg(v) for k, v in ch.items()}, pts=pts, K=K, Hw=Hw, flags=flags, prior=deg(pri), plan=plan, S_off=S_off)

    def solve_one(self, W, Hm, phi=None):
        """one static pose at the prior's swivel (the planners' reach and comfort probe; nothing is planned over time)"""
        Wc = self.to_chest(np.atleast_2d(W)); Hc = self.Rc.T @ np.asarray(Hm)[None]; S, _ = self.shoulder(np.zeros(1), np.zeros(1)); ph = self.prior(S, Wc) if phi is None else np.array([phi])
        E, We, info = self.elbow(S, Wc, ph); ch = self.analyze(S, E, We, Hc); w, wf = self.split_wrist(ch["tau_raw"], ch["sw_raw"])
        return dict(ratio=float(info["L"][0] / L_ARM), pron=float(self.sg * deg(ch["tau_raw"][0])), flex=float(deg(w["wrist_flex"][0])), dev=float(deg(w["wrist_dev"][0])), ellipse=float(wf["ellipse"][0]),
                    sh_flex=float(deg(ch["sh_flex"][0])), sh_abd=float(deg(ch["sh_abd"][0])), sh_twist=float(deg(ch["sh_twist"][0])), elbow=float(deg(ch["elbow"][0])))

    # ---- the hand: finger FK in the android's own bone layout (curl c -> MCP 1.35 c, PIP 1.55 c, DIP 1.1 c rad: DIP/PIP = 0.71, S-JT-3)
    def hand_bones(self, Hw, W, curl, spread=0.0, thumb_abd=0.0):
        """Hw (3,3) + W (3,) character space, curl[5] (thumb..pinky) -> {bone: 4x4}, {finger: tip}"""
        s = self.s; P = {}; Ph = np.eye(4); Ph[:3, :3] = Hw; Ph[:3, 3] = W; P[f"hand.{s}"] = Ph; Th = Ph @ RINV[f"hand.{s}"]; tips = {}
        for i, fn in enumerate(FINGERS):
            Tf = Th
            for k in (1, 2, 3):
                b = f"{fn}.{k:02d}.{s}"; R3 = REST[b][:3, :3]; ang = curl[i] * (1.35 if k == 1 else 1.55 if k == 2 else 1.1) * (0.6 if fn == "thumb" else 1.0); Rm = rv(R3[:, 0] * ang * self.CURL[b])
                if k == 1 and fn != "thumb" and spread: Rm = rv(R3[:, 2] * spread * (i - 2.2) * 0.12 * self.sg) @ Rm
                if k == 1 and fn == "thumb" and thumb_abd: Rm = rv(R3[:, 2] * thumb_abd) @ Rm                 # the thumb's CMC has 2 DoF (STANDARD §2): opposition, used by the grip
                M = np.eye(4); M[:3, :3] = Rm; M[:3, 3] = HEAD[b] - Rm @ HEAD[b]; Tf = Tf @ M; P[b] = Tf @ REST[b]
            tips[fn] = (Tf @ np.append(TAIL[f"{fn}.03.{s}"], 1))[:3]
        return P, tips

    @staticmethod
    def finger_deg(curl):
        """curl[5] -> degrees per finger: (MCP, PIP, DIP)"""
        return [[math.degrees(c * m * (0.6 if i == 0 else 1.0)) for m in (1.35, 1.55, 1.1)] for i, c in enumerate(curl)]

    # ---- the android's bone matrices for one frame (render + inspector): the arm from the solved frames, everything else frozen
    def android_pose(self, K_i, Hw, pts_i, tau, curl, spread, static, thumb_abd=0.0, f=None):
        s = self.s; P = dict(static); T = self.T[f] if self.moving else self.T; Rc = T[:3, :3]; S, E, W = pts_i; tc = lambda p: Rc @ p + T[:3, 3]
        Mc = np.eye(4); Mc[:3, :3] = Rc @ K_i["Rcl"] @ Rc.T; pc = tc(self.clav0) + (S - tc(K_i["S"])); Mc[:3, 3] = pc - Mc[:3, :3] @ pc
        P[f"shoulder.{s}"] = Mc @ T @ REST[f"shoulder.{s}"]
        for b, R, p in ((f"upper_arm.{s}", Rc @ K_i["U"], S), (f"forearm.{s}", Rc @ K_i["F0"] @ ry(tau * CFG["android_forearm_twist_share"]), E)):
            M = np.eye(4); M[:3, :3] = R; M[:3, 3] = p; P[b] = M
        Pf, tips = self.hand_bones(Hw, W, curl, spread, thumb_abd); P.update(Pf); return P, tips


def delta_rows(P):
    """per android bone: pose x rest^-1, 12 floats (what Blender's apply_pose and the inspector take)"""
    return [[round(float(v), 5) for v in (P[n] @ RINV[n])[:3].reshape(-1)] for n in NAMES]


def minjerk_fit(x, lam, w=None):
    """the minimum-jerk curve nearest a sampled target: argmin sum w (y - x)^2 + lam sum (third difference)^2, solved for the whole clip at once
    (non-causal, so no lag; S-TGT-1). Rows with a large w are pinned (hit frames). x: (N,) or (N,k)"""
    from scipy.sparse import diags, identity
    from scipy.sparse.linalg import splu
    x = np.asarray(x, float); N = len(x); w = np.ones(N) if w is None else np.asarray(w, float)
    D = diags([-1.0, 3.0, -3.0, 1.0], [0, 1, 2, 3], shape=(N - 3, N)); A = (diags(w) + lam * (D.T @ D)).tocsc(); lu = splu(A)
    return lu.solve(w * x) if x.ndim == 1 else np.stack([lu.solve(w * x[:, k]) for k in range(x.shape[1])], 1)
