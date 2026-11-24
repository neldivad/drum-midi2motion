#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/body_rig.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""body_rig.py: the rest of the performer as a driving skeleton (numpy, 120 Hz): pelvis, spine, chest, neck, head, both legs with feet and toes.
The arms stay arm_rig.ArmRig (one per side), hung from the chest this file computes per frame.

    B = Body(seated=True, root=kit.ROOT)
    K = B.trunk(ch)                 # ch: lean/side/turn totals (deg), shift (N,3) m, nod/tilt/look (deg), breath (deg) -> T {bone: (N,4,4)}, per-bone channels
    L = B.leg("R", K["T"]["hips"], ankle, foot_dir, toe_dir)        # analytic two-bone IK with the knee's swivel as an input, the foot and toes placed by the planner

Conventions (the android's rest space = character space): x = the character's left, y = back, z = up; it faces -y.
- A trunk bone's rotation is a SWING (flexion about x, lateral bend about y) followed by a TWIST about its own long axis z: never Euler (S-JT-1).
  lean + = forward, side + = toward its left, turn + = to its left.
- A T here is the bone's DELTA: posed = T @ rest (what the android's bones and the inspector take).
- Legs: thigh and shin share the hinge axis n (the knee is a 1-DoF hinge by construction); the hip is swing (flexion, abduction) + twist; the ankle is the
  foot's rotation relative to the shin split into hinge (dorsiflexion +), roll (inversion +) and a residual yaw; the toes bend at the MTP (extension +).
"""
import math
import numpy as np
from scipy.spatial.transform import Rotation as Rot
import arm_rig as AR
from arm_rig import CFG, HZ, rx, ry, rz, rv, unit, dot, cols

BC = CFG["body"]; X, Y, Z = np.eye(3); FWD = np.array([0, -1.0, 0]); DOWN = np.array([0, 0, -1.0]); rad, deg = np.radians, np.degrees
TRUNK = ("hips", "spine", "chest"); HEADB = ("neck", "head")
BODY_CAPS = [("pelvis", "hips", (-0.06, 0, 0.90), (0.06, 0, 0.90), 0.115), ("waist", "spine", (0, 0, 1.00), (0, 0, 1.14), 0.105), ("chest", "chest", (-0.07, 0, 1.27), (0.07, 0, 1.27), 0.105),
             ("neck", "neck", (0, 0, 1.41), (0, 0, 1.47), 0.05), ("head", "head", (0, -0.008, 1.56), (0, -0.008, 1.63), 0.102)]      # the sibling rig.py's body capsules (same numbers)


def m4(R, t):
    R = np.asarray(R, float); M = np.zeros(R.shape[:-2] + (4, 4)); M[..., :3, :3] = R; M[..., :3, 3] = t; M[..., 3, 3] = 1.0; return M
def about(p, R): p = np.asarray(p, float); return m4(R, p - np.einsum("...ij,j->...i", R, p))
def swing_twist(fx, sd, tw): return rv(np.stack([fx, sd, np.zeros_like(fx)], -1)) @ rz(tw)
def pt(T, p): return np.einsum("...ij,j->...i", T[..., :3, :3], np.asarray(p, float)) + T[..., :3, 3]
def rotvec(R): return Rot.from_matrix(R.reshape(-1, 3, 3)).as_rotvec().reshape(R.shape[:-2] + (3,))


class Body:
    def __init__(self, seated, root=(0, 0, 0)):
        self.seated = seated; self.root = np.asarray(root, float); self.H = AR.HEAD; self.TL = AR.TAIL
        self.L1 = float(np.linalg.norm(self.TL["thigh.L"] - self.H["thigh.L"])); self.L2 = float(np.linalg.norm(self.TL["shin.L"] - self.H["shin.L"])); self.Lf = float(np.linalg.norm(self.TL["foot.L"] - self.H["foot.L"]))
        self.neutral = BC["seated_neutral" if seated else "standing_neutral"]
        self.pivot = (np.array(BC["seat_pivot"]) - self.root) if seated else self.H["hips"]            # in rest space, before the root offset
        self.foot_pitch = math.atan2(self.H["foot.L"][2] - self.TL["foot.L"][2], self.H["foot.L"][1] - self.TL["foot.L"][1])     # the foot bone dips this far under the sole's line (26 deg)

    # ---- pelvis, spine, chest, neck, head
    def trunk(self, ch):
        """ch (arrays, deg / m): lean, side, turn, shift (N,3), nod, tilt, look, breath -> T per bone (N,4,4), the per-bone channels (deg)"""
        N = len(ch["lean"]); sh = BC["trunk_share"]; T = {}; out = {}; z = np.zeros(N)
        Tm = m4(np.broadcast_to(np.eye(3), (N, 3, 3)), self.root + ch.get("shift", np.zeros((N, 3))))
        for b in TRUNK:
            fx, sd, tw = (ch[k] * sh[b][i] for i, k in enumerate(("lean", "side", "turn")))
            if b == "chest": fx = fx - ch.get("breath", z)                                               # L2: an inhale opens the chest (extension)
            Tm = Tm @ about(self.pivot if b == "hips" else self.H[b], swing_twist(rad(fx), rad(sd), rad(tw))); T[b] = Tm
            pre = "pelvis" if b == "hips" else b; out[f"{pre}_{'tilt' if b == 'hips' else 'flex'}"] = fx; out[f"{pre}_side"] = sd; out[f"{pre}_{'turn' if b == 'hips' else 'twist'}"] = tw
        hs = BC["head_share"]
        for b in HEADB:
            Tm = Tm @ about(self.H[b], swing_twist(rad(ch["nod"] * hs[b]), rad(ch["tilt"] * hs[b]), rad(ch["look"] * hs[b]))); T[b] = Tm
        out.update(head_flex=ch["nod"], head_side=ch["tilt"], head_twist=ch["look"])
        return dict(T=T, ch=out)

    def caps(self, T, legs=None):
        """body capsules in character space per frame: [(name, a (N,3), b (N,3), r)]"""
        c = [(n, pt(T[bone], a), pt(T[bone], b), r) for n, bone, a, b, r in BODY_CAPS]
        for s, L in (legs or {}).items(): c += [(f"thigh.{s}", L["hip"], L["knee"], 0.075), (f"shin.{s}", L["knee"], L["ankle"], 0.055)]
        return c

    # ---- one leg: analytic two-bone IK, the knee's swivel an explicit input (S-FOOT-5)
    def leg(self, s, T_hips, ankle, foot_dir, toe_dir, swivel_deg=None, foot_x=None):
        """ankle (N,3), foot_dir (ankle -> ball, unit), toe_dir (unit), all character space -> bone rotations, points, channels (deg), reach flags"""
        sg = 1.0 if s == "L" else -1.0; N = len(ankle); Hp = pt(T_hips, self.H[f"thigh.{s}"]); Rp = T_hips[..., :3, :3]; LR = BC["leg_reach"]; Lmax = self.L1 + self.L2
        d = ankle - Hp; L = np.linalg.norm(d, axis=-1); u = d / L[:, None]; lf, lm = LR["flag"] * Lmax, LR["max_ext"] * Lmax; k = lm - lf
        Lc = np.where(L > lf, lf + k * (1 - np.exp(-(L - lf) / k)), L); a = (self.L1 ** 2 - self.L2 ** 2 + Lc ** 2) / (2 * Lc); rho = np.sqrt(np.maximum(self.L1 ** 2 - a ** 2, 0.0))
        pole = np.einsum("nij,j->ni", Rp, np.array([0, -0.3, 1.0]) if self.seated else np.array([0, -1.0, 0.0])); ref = unit(pole - u * dot(pole, u)[:, None]); ow = np.cross(u, ref)
        if float(np.mean(ow @ np.array([sg, 0, 0]))) < 0: ow = -ow                                       # + swivel splays the knee outward
        psi = rad(np.full(N, BC["knee_swivel"]["seated" if self.seated else "standing"]) if swivel_deg is None else np.asarray(swivel_deg, float))
        kd = np.cos(psi)[:, None] * ref + np.sin(psi)[:, None] * ow; knee = Hp + u * a[:, None] + rho[:, None] * kd; An = Hp + u * Lc[:, None]
        n = unit(np.cross(kd, u)); n = n * np.sign(dot(n, Rp[..., :, 0]) + 1e-9)[:, None]               # the hinge axis, on the pelvis's left side as at rest
        yt, ys = unit(knee - Hp), unit(An - knee); fr = lambda y: cols(X, y, np.cross(X, y)); yr = lambda b: unit(self.TL[b] - self.H[b])
        Rt = cols(n, yt, np.cross(n, yt)) @ fr(yr(f"thigh.{s}")).T; Rs = cols(n, ys, np.cross(n, ys)) @ fr(yr(f"shin.{s}")).T
        fx = np.broadcast_to(X, (N, 3)) if foot_x is None else foot_x; fd = unit(foot_dir); fx = unit(fx - fd * dot(fx, fd)[:, None]); td = unit(toe_dir); tx = unit(fx - td * dot(fx, td)[:, None])
        Rf = cols(fx, fd, np.cross(fx, fd)) @ fr(yr(f"foot.{s}")).T; Rto = cols(tx, td, np.cross(tx, td)) @ fr(yr(f"toe.{s}")).T; ball = An + self.Lf * fd
        # channels
        dl = np.einsum("nji,nj->ni", Rp, yt); ch = dict(hip_flex=deg(np.arctan2(dl @ FWD, dl @ DOWN)), hip_abd=deg(np.arcsin(np.clip(dl @ np.array([sg, 0, 0]), -1, 1))))
        M = AR.minrot(DOWN, dl); xr = np.einsum("nij,j->ni", M, X); nl = np.einsum("nji,nj->ni", Rp, n); ch["hip_twist"] = sg * deg(np.arctan2(dot(np.cross(xr, nl), dl), dot(xr, nl)))
        ch["knee"] = deg(np.arctan2(np.linalg.norm(np.cross(yt, ys), axis=-1), dot(yt, ys)))
        ra = rotvec(np.swapaxes(Rs, -1, -2) @ Rf); ch["ankle"] = -deg(ra[:, 0]); ch["ankle_roll"] = sg * deg(ra[:, 1]); ch["foot_yaw"] = deg(ra[:, 2])
        ch["toes"] = -deg(rotvec(np.swapaxes(Rf, -1, -2) @ Rto)[:, 0]); ch["knee_swivel"] = deg(psi)
        P = {f"thigh.{s}": (Rt, Hp), f"shin.{s}": (Rs, knee), f"foot.{s}": (Rf, An), f"toe.{s}": (Rto, ball)}
        return dict(R=dict(thigh=Rt, shin=Rs, foot=Rf, toe=Rto), hip=Hp, knee=knee, ankle=An, ball=ball, toe_tip=ball + 0.08 * td, ch=ch, P=P, reach_ratio=L / Lmax, reach_over=L > lf, unattained_m=np.linalg.norm(An - ankle, axis=1), n=n)

    @staticmethod
    def leg_delta(L, f):
        """{bone: 4x4 delta} of one leg on frame f"""
        out = {}
        for b, (R, p) in L["P"].items(): M = np.eye(4); M[:3, :3] = R[f]; M[:3, 3] = p[f] - R[f] @ AR.HEAD[b]; out[b] = M
        return out

    # ---- a foot on a pedal board or the floor: the ball (MTP joint) planted, the heel lifting about it (S-FOOT-1/2/3)
    def foot_on_board(self, s, hinge, plate_deg, heel_deg, turnout_deg=0.0):
        """hinge (3,): the board's hinge (heel end) on the floor, the board running toward -y; plate_deg (N,): the board's angle (toe end up); heel_deg (N,): the heel's lift
        about the ball = MTP extension; turnout_deg: the foot's angle on the board, toes outward, about the ball (the heel swings in).
        -> ankle (N,3), foot_dir, toe_dir, the ball's contact point (fixed ON THE BOARD: it rides the board, it never slides on it), the heel"""
        F = BC["foot"]; sg = 1.0 if s == "L" else -1.0; b_ = rad(np.asarray(plate_deg, float)); N = len(b_); hd = rad(np.asarray(heel_deg, float))
        bd = np.cos(b_)[:, None] * FWD + np.sin(b_)[:, None] * Z; nb = -np.sin(b_)[:, None] * FWD + np.cos(b_)[:, None] * Z; ball = np.asarray(hinge, float) + F["ball_on_board"] * bd + (F["board_top"] + F["sole"]) * nb
        ty = sg * math.radians(turnout_deg); fl = math.cos(ty) * bd + math.sin(ty) * np.cross(nb, bd); fx = np.cross(nb, fl); g = self.foot_pitch + hd       # the foot's own line on the board, and its lateral axis (x = y x z)
        fd = np.cos(g)[:, None] * fl - np.sin(g)[:, None] * nb; ankle = ball - self.Lf * fd
        heel = ball + (-F["heel_lever"] * np.cos(hd))[:, None] * fl + (F["heel_lever"] * np.sin(hd) - F["sole"])[:, None] * nb
        return dict(ankle=ankle, foot_dir=fd, toe_dir=fl, foot_x=fx, ball=ball, heel=heel, board_dir=bd, board_n=nb, hinge=np.asarray(hinge, float), heel_h=F["heel_lever"] * np.sin(hd))

    def foot_on_floor(self, s, N):
        """a planted standing foot (the rest stance): it never moves (foot locking)"""
        a = np.broadcast_to(self.H[f"foot.{s}"], (N, 3)).copy(); fd = np.broadcast_to(unit(self.TL[f"foot.{s}"] - self.H[f"foot.{s}"]), (N, 3)); td = np.broadcast_to(FWD, (N, 3))
        return dict(ankle=a, foot_dir=fd, toe_dir=td, foot_x=np.broadcast_to(X, (N, 3)), ball=a + self.Lf * fd, heel=a + np.array([0, 0.05, -0.09]))
