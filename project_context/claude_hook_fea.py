"""Plane-stress FEA of the J-hook + barbed-latch cart clip (2D cross-section,
thickness = clip_w). Mesh via gmsh (true geometry incl. root fillets),
linear triangles; solver verified against beam theory in clip_fea.py (-3%).

Local frame: u = outward from boss face (toward cart), v = up. Top of clip at v=0.
  spine   u in [0, spine_t],                      v in [-clip_h, 0]
  top arm u in [0, spine_t+hook_w+leg_t],         v in [-arm_t, 0]
  latch   u in [spine_t+hook_w, ...+leg_t],       v in [-(arm_t+leg_l), 0]
  barb    circle d=barb_d on latch inner face at the latch tip (rounded lead-in)
Wire seats under the top arm; the box's weight goes into the rigid hook, and only
the latch flexes during snap-in.
"""
import sys
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
import gmsh

E, NU = 3000.0, 0.35       # MPa: printed PLA, XY orientation (conservative)
YIELD = 45.0               # MPa: printed PLA tensile, XY (datasheets ~50-60)
EPS_REPEAT, EPS_ONCE = 1.5, 2.5   # % allowable strain: repeated / one-time snap


def geom(p):
    q = dict(p)
    q['hook_w'] = p['wire_d'] + p['hook_extra']
    q['leg_l'] = p['wire_d'] + p['seat_play'] + p['barb_d']
    q['interf'] = p['barb_d'] / 2 - p['hook_extra']
    q['clip_h'] = max(p['clip_h'], p['arm_t'] + q['leg_l'])
    return q


def mesh(q, h=0.25, h_fine=0.06):
    gmsh.initialize()
    gmsh.option.setNumber('General.Terminal', 0)
    gmsh.model.add('clip')
    o = gmsh.model.occ
    st, at, lt, hw = q['spine_t'], q['arm_t'], q['leg_t'], q['hook_w']
    r = q['root_r']
    parts = [
        o.addRectangle(0, -q['clip_h'], 0, st, q['clip_h']),
        o.addRectangle(0, -at, 0, st + hw + lt, at),
        o.addRectangle(st + hw, -(at + q['leg_l']), 0, lt, q['leg_l']),
        o.addDisk(st + hw, -(at + q['leg_l']) + q['barb_d'] / 2, 0, q['barb_d'] / 2, q['barb_d'] / 2),
    ]
    # root fillets = square minus quarter disk, at both inner corners
    for (cu, cv, du) in [(st + hw, -at, -1), (st, -at, +1)]:
        sq = o.addRectangle(min(cu, cu + du * r), cv - r, 0, r, r)
        dk = o.addDisk(cu + du * r, cv - r, 0, r, r)
        f, _ = o.cut([(2, sq)], [(2, dk)])
        parts += [t for _, t in f]
    out, _ = o.fuse([(2, parts[0])], [(2, t) for t in parts[1:]])
    o.synchronize()
    # refine near the latch root
    pt = o.addPoint(st + hw + lt / 2, -at - r, 0)
    o.synchronize()
    gmsh.model.mesh.field.add('Distance', 1)
    gmsh.model.mesh.field.setNumbers(1, 'PointsList', [pt])
    gmsh.model.mesh.field.add('Threshold', 2)
    gmsh.model.mesh.field.setNumber(2, 'InField', 1)
    gmsh.model.mesh.field.setNumber(2, 'SizeMin', h_fine)
    gmsh.model.mesh.field.setNumber(2, 'SizeMax', h)
    gmsh.model.mesh.field.setNumber(2, 'DistMin', 1.5)
    gmsh.model.mesh.field.setNumber(2, 'DistMax', 4.0)
    gmsh.model.mesh.field.setAsBackgroundMesh(2)
    gmsh.option.setNumber('Mesh.MeshSizeExtendFromBoundary', 0)
    gmsh.model.mesh.generate(2)
    tags, xyz, _ = gmsh.model.mesh.getNodes()
    nodes = xyz.reshape(-1, 3)[:, :2]
    tmap = {t: i for i, t in enumerate(tags)}
    et, etags, enodes = gmsh.model.mesh.getElements(2)
    tris = np.array([tmap[n] for n in enodes[list(et).index(2)]]).reshape(-1, 3)
    gmsh.finalize()
    # drop orphan nodes (e.g. the refinement point)
    used = np.unique(tris)
    remap = -np.ones(len(nodes), int); remap[used] = np.arange(len(used))
    return nodes[used], remap[tris]


def D():
    c = E / (1 - NU ** 2)
    return c * np.array([[1, NU, 0], [NU, 1, 0], [0, 0, (1 - NU) / 2]])


def solve(nodes, tris, thick, fixed, presc=None, forces=None):
    n = len(nodes); Dm = D()
    x, y = nodes[tris, 0], nodes[tris, 1]
    A = 0.5 * ((x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0]))
    b = np.stack([y[:, 1] - y[:, 2], y[:, 2] - y[:, 0], y[:, 0] - y[:, 1]], 1)
    c = np.stack([x[:, 2] - x[:, 1], x[:, 0] - x[:, 2], x[:, 1] - x[:, 0]], 1)
    B = np.zeros((len(tris), 3, 6))
    B[:, 0, 0::2] = b; B[:, 1, 1::2] = c; B[:, 2, 0::2] = c; B[:, 2, 1::2] = b
    B /= (2 * A)[:, None, None]
    ke = thick * np.abs(A)[:, None, None] * np.einsum('eki,kl,elj->eij', B, Dm, B)
    dofs = np.stack([2 * tris, 2 * tris + 1], 2).reshape(-1, 6)
    K = sp.csr_matrix((ke.ravel(), (np.repeat(dofs, 6, 1).ravel(), np.tile(dofs, (1, 6)).ravel())),
                      shape=(2 * n, 2 * n))
    u = np.zeros(2 * n); f = np.zeros(2 * n)
    presc = presc or {}
    for d, v in presc.items(): u[d] = v
    if forces is not None: f += forces
    known = np.array(sorted(set(fixed) | set(presc)))
    free = np.setdiff1d(np.arange(2 * n), known)
    u[free] = spla.spsolve(K[free][:, free].tocsc(), f[free] - K[free][:, known] @ u[known])
    eps = np.einsum('eij,ej->ei', B, u[dofs])
    return u, K @ u, eps


def post(eps):
    ex, ey, g = eps.T
    cc, rr = (ex + ey) / 2, np.sqrt(((ex - ey) / 2) ** 2 + (g / 2) ** 2)
    s = eps @ D().T
    vm = np.sqrt(s[:, 0] ** 2 - s[:, 0] * s[:, 1] + s[:, 1] ** 2 + 3 * s[:, 2] ** 2)
    return (cc + rr) * 100, vm


def run(p, F_hang=10.0, want_fields=False, h=0.25, hf=0.06):
    q = geom(p)
    nodes, tris = mesh(q, h, hf)
    cent = nodes[tris].mean(1)
    fixed = [d for k in np.where(nodes[:, 0] < 1e-6)[0] for d in (2 * k, 2 * k + 1)]
    # --- Case 1: snap-in. Wire pushes the barb's innermost point outward by `interf`.
    bu, bv = q['spine_t'] + q['hook_w'] - q['barb_d'] / 2, -(q['arm_t'] + q['leg_l']) + q['barb_d'] / 2
    dist_b = np.hypot(nodes[:, 0] - bu, nodes[:, 1] - bv)
    patch = np.where(dist_b < 0.3)[0]
    presc = {2 * k: q['interf'] for k in patch}
    u1, f1, e1 = solve(nodes, tris, p['clip_w'], fixed, presc)
    ep1, vm1 = post(e1)
    far = np.hypot(cent[:, 0] - bu, cent[:, 1] - bv) > 0.8      # ignore local contact zone
    k1 = np.argmax(np.where(far, ep1, -1))
    snap_force = sum(f1[2 * k] for k in patch)                   # N
    # --- Case 2: hanging load on the top-arm underside (wire seat).
    mid = q['spine_t'] + q['hook_w'] / 2
    seat = np.where((np.abs(nodes[:, 1] + q['arm_t']) < 1e-6) & (np.abs(nodes[:, 0] - mid) < 1.0))[0]
    fv = np.zeros(2 * len(nodes)); fv[2 * seat + 1] = F_hang / len(seat)
    u2, _, e2 = solve(nodes, tris, p['clip_w'], fixed, forces=fv)
    ep2, vm2 = post(e2)
    seatzone = np.hypot(cent[:, 0] - mid, cent[:, 1] + q['arm_t']) > 1.5
    res = dict(q=q, strain=ep1[k1], strain_at=cent[k1], snap_force=snap_force,
               hang_vm=vm2[seatzone].max(), hang_sf=YIELD / vm2[seatzone].max(),
               n_el=len(tris))
    if want_fields:
        res.update(nodes=nodes, tris=tris, u1=u1, ep1=ep1, vm2=vm2, u2=u2)
    return res


BASE = dict(wire_d=6.0, hook_extra=0.5, barb_d=2.4, seat_play=3.0, spine_t=2.4,
            arm_t=2.4, leg_t=1.2, root_r=1.0, clip_h=16.0, clip_w=10.0)

if __name__ == '__main__':
    print('Mesh convergence (BASE design):')
    for h, hf in [(0.4, 0.12), (0.25, 0.06), (0.15, 0.03)]:
        r = run(BASE, h=h, hf=hf)
        print('  h=%.2f/%.2f  elements=%d  strain=%.2f%%' % (h, hf, r['n_el'], r['strain']))
    print()
    print('SWEEP (wire 6 mm, clip_w 10 mm, hang load 10 N/clip):')
    print(' leg_t  interf  play   peak_strain  where(u,v)     snap_force  hang_SF  verdict')
    rows = []
    for lt in [1.0, 1.2, 1.5, 2.0]:
        for barb in [2.0, 2.4, 3.0]:
            for play in [1.0, 3.0, 5.0]:
                p = dict(BASE, leg_t=lt, barb_d=barb, seat_play=play)
                r = run(p)
                v = 'OK' if r['strain'] <= EPS_REPEAT else ('one-time' if r['strain'] <= EPS_ONCE else 'SNAPS')
                rows.append((p, r, v))
                print('  %.1f    %.1f    %.0f      %5.2f%%     (%4.1f,%5.1f)     %5.1f N    %5.1f    %s'
                      % (lt, r['q']['interf'], play, r['strain'], *r['strain_at'], r['snap_force'], r['hang_sf'], v))
    np.save('sweep.npy', np.array([(p['leg_t'], r['q']['interf'], p['seat_play'], r['strain'], r['snap_force'], r['hang_sf']) for p, r, v in rows]))
