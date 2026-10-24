"""Test hardware/cad/IPadMount/IPadMount.py without Fusion.

    uv run --with manifold3d --with numpy --with matplotlib hardware/cad/check/check.py
    ... check.py rim_drop="150 mm" tilt="35 deg"      # try other parameter values

1. Runs the script against a mock of Fusion's API (adsk/): every expression
   must evaluate and every sketch dimension must match the geometry it was
   drawn at, and the auto-fillet / chamfer / STL code paths run.
2. Rebuilds every extrusion as a real solid (manifold3d) and checks: each
   printable part is one solid; nothing overlaps the iPad, handle, wire or
   each other; the handle and wire slide in through their mouths (bracket
   pushed toward the cart); the iPad slides in from above; both zip-tie
   loops have room.
3. Writes hardware/cad/stl/preview_*.stl (no fillets or chamfers: fine for
   the fit tests; Fusion's own export is the real print file) and
   hardware/cad/stl/preview.png.

Exit code 0 = all checks pass.
"""
import importlib.util
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CAD = os.path.dirname(HERE)
SCRIPT = os.path.join(CAD, 'IPadMount', 'IPadMount.py')
OUT = os.path.join(CAD, 'stl')
sys.path.insert(0, HERE)

import adsk  # noqa: E402  (the mock)
from adsk import fusion  # noqa: E402


# ------------------------------------------------------------ 1. mock run
def mock_run(overrides):
    spec = importlib.util.spec_from_file_location('IPadMount', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.STL_DIR = OUT
    if overrides:
        unknown = set(overrides) - set(n for n, _, _, _ in mod.PARAMS)
        if unknown:
            sys.exit('unknown parameter(s): %s' % ', '.join(sorted(unknown)))
        mod.PARAMS = [(n, overrides.get(n, e), u, c) for n, e, u, c in mod.PARAMS]
    mod.run(None)
    L = fusion.LOG
    failed = any('failed at step' in m for m in adsk.core.LOG['messages'])
    print('mock: %d sketches, %d dimensions checked, %d extrusions, %d fillet/chamfer features'
          % (L['sketches'], L['dims'], len(L['prisms']), len(L['finishing'])))
    for e in L['dim_errors'][:20] + L['eval_errors'][:20]:
        print('  ' + e)
    ok = not (failed or L['dim_errors'] or L['eval_errors'])
    # params in mm (lengths) / rad (angles), keyed by name
    units = dict((n, u) for n, _, u, _ in mod.PARAMS)
    P = dict((k, v if units.get(k) == 'deg' else v * 10) for k, v in L['params'].items())
    return ok, P


# ----------------------------------------------------------- 2. solids
def solids_from_log(np, CrossSection, FillRule, Manifold):
    # A YZ section extruded along its local z, then (x, y, z) -> (Y, Z, X)
    perm = np.array([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)

    def section(shapes):
        cs = CrossSection()
        for kind, g in shapes:
            if kind == 'poly':
                cs = cs + CrossSection([np.array(g) * 10], FillRule.NonZero)
            else:
                (cy, cz), r = g
                cs = cs + CrossSection.circle(r * 10, 96).translate((cy * 10, cz * 10))
        return cs

    def prism(cs, x0, x1):
        T = perm.copy()
        T[0, 3] = x0
        return cs.extrude(x1 - x0).transform(T)

    solids = {}
    for p in fusion.LOG['prisms']:
        m = prism(section(p['shapes']), p['x0'] * 10, p['x1'] * 10)
        if p['op'] == 'CUT':
            solids[p['comp']] = solids[p['comp']] - m
        else:
            solids[p['comp']] = solids.get(p['comp'], Manifold()) + m
    return solids, prism


def solid_checks(P, results):
    import numpy as np
    from manifold3d import CrossSection, FillRule, Manifold
    solids, prism = solids_from_log(np, CrossSection, FillRule, Manifold)
    ok = True

    def report(label, v, tol=1e-3):
        nonlocal ok
        good = v <= tol
        ok &= good
        print('  %-50s %s' % (label, 'ok' if good else 'FAIL (%.1f mm3)' % v))

    def box(y0, z0, y1, z1):
        return CrossSection([np.array([(y0, z0), (y1, z0), (y1, z1), (y0, z1)])], FillRule.NonZero)

    def vol(a, b):
        return (a ^ b).volume()

    printable = ['Bracket_L', 'Bracket_R', 'Spacer', 'TEST_Corner', 'TEST_Profile']
    print('\nparts:')
    for n in printable:
        m = solids[n]
        bodies = len([q for q in m.decompose() if abs(q.volume()) > 1.0])
        good = (not m.is_empty()) and bodies == 1
        ok &= good
        print('  %-13s %6.1f cm3  %s' % (n, m.volume() / 1000,
                                         'one solid, ok' if good else 'FAIL (%d pieces)' % bodies))

    ipad, handle, wire = solids['REF_iPad'], solids['REF_Handle'], solids['REF_Wire']
    print('\noverlaps:')
    for n in ['Bracket_L', 'Bracket_R', 'Spacer']:
        for ref, m in [('iPad', ipad), ('handle', handle), ('wire', wire)]:
            report('%s vs %s' % (n, ref), vol(solids[n], m))
    for n in ['Bracket_L', 'Bracket_R']:
        report('Spacer vs %s' % n, vol(solids['Spacer'], solids[n]))

    # Install: the bracket is pushed toward the cart (+Y), so relative to it
    # the handle and the wire come in from +Y.
    bx, hr, wr = P['bx_o'], P['handle_d'] / 2, P['rim_d'] / 2
    wc = (P['rim_dy'], -P['rim_drop'])
    handle_path = (CrossSection.circle(hr, 96)
                   + CrossSection.circle(hr, 96).translate((300, 0))).hull()
    wire_path = (CrossSection.circle(wr, 48).translate(wc)
                 + CrossSection.circle(wr, 48).translate((wc[0] + 300, wc[1]))).hull()
    t = P['tilt']
    s, c = math.sin(t), math.cos(t)

    def pvn(v, n):
        return (P['ipad_y0'] + v * s + n * c, P['ipad_z0'] + v * c - n * s)

    H, D, W = P['ipad_h'], P['ipad_d'], P['ipad_w']
    ipad_path = prism(CrossSection([np.array([pvn(0, 0), pvn(H + 300, 0), pvn(H + 300, D),
                                              pvn(0, D)])], FillRule.NonZero), -W / 2, W / 2)
    print('\nassembly paths:')
    for n, xs in [('Bracket_L', (-bx - 1, -bx + 40)), ('Bracket_R', (bx - 40, bx + 1)),
                  ('TEST_Profile', (-bx - 400, -bx))]:
        report('%s: handle slides into the C clamp' % n, vol(solids[n], prism(handle_path, *xs)))
        report('%s: wire slides into the pad notch' % n, vol(solids[n], prism(wire_path, *xs)))
    for n in ['Bracket_L', 'Bracket_R', 'Spacer']:
        report('%s: iPad slides in and out from above' % n, vol(solids[n], ipad_path))

    # Zip-tie loops, 2.5 mm bands at the tunnel X: handle tie over the top
    # jaw, down across the mouth, back under the bottom jaw; wire tie round
    # the front of the wire.
    rs, br, nm = P['r_sad'], P['bore_r'], P['n_b'] + P['hook_gap'] / 2

    def y_on(z, n):
        return pvn((z - P['ipad_z0'] + n * s) / c, n)[0]

    band = (box(y_on(rs, nm) + 2, rs + 0.05, br + 3, rs + 2.5)
            + box(br + 0.05, -rs - 2.5, br + 3, rs + 2.5)
            + box(y_on(-rs, nm) + 2, -rs - 2.5, br + 3, -rs - 0.05))
    wband = box(wc[0] + P['r_wb'] + 0.05, wc[1] - P['r_pad'] - 2.5,
                wc[0] + P['r_wb'] + 2.5, wc[1] + P['r_pad'] + 2.5)
    t0, t1 = P['tie_x'] - P['zt_w'] / 2, P['tie_x'] + P['zt_w'] / 2
    print('\nzip-tie loops:')
    for n, xs in [('Bracket_L', (-bx + t0, -bx + t1)), ('Bracket_R', (bx - t1, bx - t0))]:
        report('%s: handle tie has room' % n, vol(solids[n], prism(band, *xs)))
        report('%s: wire tie has room' % n, vol(solids[n], prism(wband, *xs)))

    results['solids'] = solids
    return ok


# --------------------------------------------------------------- 3. outputs
def write_stl(m, path):
    import numpy as np
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3]
    f = np.asarray(mesh.tri_verts)
    with open(path, 'wb') as fh:
        fh.write(b'KART iPad mount preview (check.py, no fillets)'.ljust(80, b' '))
        fh.write(struct.pack('<I', len(f)))
        for tri in f:
            a, b, cc = v[tri[0]], v[tri[1]], v[tri[2]]
            nrm = np.cross(b - a, cc - a)
            L = np.linalg.norm(nrm)
            fh.write(struct.pack('<12fH', *(nrm / L if L else nrm), *a, *b, *cc, 0))


def preview_png(solids, path):
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from manifold3d import Manifold
    clip = Manifold.cube((400, 400, 400)).translate((-200, -200, -200))
    show = [('REF_iPad', '#9aa4ad', 0.55), ('Bracket_L', '#2f7fd8', 1), ('Bracket_R', '#2f7fd8', 1),
            ('Spacer', '#e8962e', 1), ('REF_Handle', '#444444', 0.5), ('REF_Wire', '#444444', 0.5)]
    light = np.array([-0.4, -0.7, 0.6])
    light /= np.linalg.norm(light)
    fig = plt.figure(figsize=(14, 7))
    for k, (elev, azim, title) in enumerate([(22, -125, 'from the shopper side'),
                                             (5, 0, 'side view (shopper on the left)')]):
        ax = fig.add_subplot(1, 2, k + 1, projection='3d')
        for n, col, a in show:
            mesh = (solids[n] ^ clip).to_mesh()
            tris = np.asarray(mesh.vert_properties)[:, :3][np.asarray(mesh.tri_verts)]
            nrm = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
            nrm /= np.linalg.norm(nrm, axis=1)[:, None] + 1e-12
            shade = 0.45 + 0.55 * np.clip(nrm @ light, 0, 1)
            rgb = np.clip(np.array(matplotlib.colors.to_rgb(col))[None, :] * shade[:, None], 0, 1)
            ax.add_collection3d(Poly3DCollection(tris, facecolors=np.c_[rgb, np.full(len(rgb), a)],
                                                 linewidths=0))
        ax.set_xlim(-200, 200)
        ax.set_ylim(-200, 200)
        ax.set_zlim(-200, 200)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
        ax.set_xlabel('X (along handle)')
        ax.set_ylabel('Y (into cart)')
        ax.set_zlabel('Z')
        ax.set_title(title)
    plt.tight_layout()
    plt.savefig(path, dpi=85)


def main():
    overrides = dict(a.split('=', 1) for a in sys.argv[1:])
    os.makedirs(OUT, exist_ok=True)
    ok, P = mock_run(overrides)
    if not ok:
        print('\nRESULT: mock run FAILED (fix this before the solid checks mean anything)')
        sys.exit(1)
    results = {}
    ok = solid_checks(P, results)
    solids = results['solids']
    for n in ['Bracket_L', 'Bracket_R', 'Spacer', 'TEST_Corner', 'TEST_Profile']:
        write_stl(solids[n], os.path.join(OUT, 'preview_%s.stl' % n.lower()))
    preview_png(solids, os.path.join(OUT, 'preview.png'))
    print('\npreview STLs + preview.png -> %s' % OUT)
    print('RESULT: %s' % ('ALL CHECKS PASS' if ok else 'CHECKS FAILED'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
