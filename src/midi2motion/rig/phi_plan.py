#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/phi_plan.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""phi_plan.py: the elbow's swivel phi(t), planned for the WHOLE clip at once (STANDARD.md S-IK-3), never searched per frame (S-IK-8).

    minimise   sum_t  w_p (phi - phi_prior)^2  +  C(t, phi)  +  mu_t (phi[t+1] - phi[t])^2   +   lambda sum_t (phi[t+1] - 2 phi[t] + phi[t-1])^2

- phi_prior: the natural-elbow prior (arm_rig.ArmRig.prior: the CMU-fitted table, Kim/Rosen's rule where it has no sample);
- C(t, phi): joint comfort and hard limits as a function of the swivel (shoulder swing and twist, pronation, the wrist ellipse) and a
  barrier on torso penetration: a per-frame table over a phi grid, built by arm_rig.ArmRig.phi_cost and interpolated here;
- mu_t: large where the wrist is still, so the elbow only moves fast when the hand does (C-CONT-3);
- lambda: the second-difference smoothness. The solve is non-causal (offline): smooth without lag.

Solved by damped Newton steps on the whole vector (a banded linear system per step), started from the prior: there is no per-frame arg-min,
so the result is continuous by construction. Units: the solve runs in degrees.
"""
import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import spsolve
import yaml, pathlib

CFG = yaml.safe_load(open(pathlib.Path(__file__).resolve().parent / "data" / "rig.yaml")); SW = CFG["swivel"]


def _interp(C, g, x):
    """C (N,G) on grid g (deg), sampled at x (N,) linearly (clamped)"""
    u = np.clip((x - g[0]) / (g[1] - g[0]), 0, len(g) - 1 - 1e-9); i = u.astype(int); f = u - i; r = np.arange(len(x)); return C[r, i] * (1 - f) + C[r, i + 1] * f


def plan(prior, C, grid, vw, iters=60):
    """prior (N,) rad, C (N,G), grid (G,) rad, vw (N,) wrist speed m/s -> phi (N,) rad, info"""
    g = np.degrees(grid); p = np.clip(np.degrees(prior), g[0] + 1, g[-1] - 1); N = len(p); h = g[1] - g[0]
    D2 = diags([1.0, -2.0, 1.0], [0, 1, 2], shape=(N - 2, N)); D1 = diags([-1.0, 1.0], [0, 1], shape=(N - 1, N))
    mu = SW["still"] / (1 + (0.5 * (vw[1:] + vw[:-1]) / 0.15) ** 2); Q = 2 * SW["smooth"] * (D2.T @ D2) + 2 * (D1.T @ diags(mu) @ D1); wp = SW["w_prior"]
    phi = spsolve((Q + 2 * wp * diags(np.ones(N))).tocsc(), 2 * wp * p)                      # start: the smoothed prior
    for it in range(iters):
        c0, cp, cm = _interp(C, g, phi), _interp(C, g, phi + h), _interp(C, g, phi - h); gr = (cp - cm) / (2 * h); hs = np.maximum((cp - 2 * c0 + cm) / h ** 2, 0.0)
        step = spsolve((Q + diags(2 * wp + hs + 1e-6)).tocsc(), -(Q @ phi + 2 * wp * (phi - p) + gr)); phi = np.clip(phi + 0.6 * step, g[0], g[-1])
        if np.abs(step).max() < 0.02: break
    c0 = _interp(C, g, phi)
    return np.radians(phi), dict(iters=it + 1, cost_prior=float(wp * ((phi - p) ** 2).sum()), cost_comfort=float(c0.sum()), cost_smooth=float(SW["smooth"] * ((D2 @ phi) ** 2).sum()),
                                 prior_offset_deg=[float(np.abs(phi - p).mean()), float(np.abs(phi - p).max())], comfort_cost_max=float(c0.max()))
