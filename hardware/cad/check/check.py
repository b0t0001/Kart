"""Test hardware/cad/IPadMount/IPadMount.py without Fusion.

    uv run --with manifold3d --with numpy --with matplotlib hardware/cad/check/check.py
    ... check.py rim_drop="150 mm" tilt="35 deg"      # try other parameter values
    ... check.py --script=path/to/other/IPadMount.py  # check another version

1. Runs the script against a mock of Fusion's API (adsk/): every expression
   must evaluate and every sketch dimension must match the geometry it was
   drawn at, and the auto-fillet / chamfer / STL code paths run.
2. Rebuilds every extrusion as a real solid (manifold3d) and checks: each
   printable part is one solid; nothing overlaps the iPad, handle, wire or
   each other; the mount slides over the handle and wire and sits down on
   them; nudged in any direction it hits the cart except upward (it's
   captured); the iPad slides in from above; both zip-tie loops have room.
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

    # Install: hold the mount a little high, slide it toward the cart (+Y)
    # until the arch is over the handle and the pad over the wire, then set
    # it down. Relative to the bracket, the handle and the wire come in from
    # +Y a tube-radius low, then rise into the arch and the notch.
    bx, hr, wr = P['bx_o'], P['handle_d'] / 2, P['rim_d'] / 2
    wc = (P['rim_dy'], -P['rim_drop'])
    lift = hr + 1.5          # handle top passes just under the arch's jaw

    def dogleg(cy, cz, r, seg):
        low = CrossSection.circle(r, seg).translate((cy, cz - lift))
        return ((low + CrossSection.circle(r, seg).translate((cy + 300, cz - lift))).hull()
                + (low + CrossSection.circle(r, seg).translate((cy, cz))).hull())

    handle_path = dogleg(0, 0, hr, 96)
    wire_path = dogleg(wc[0], wc[1], wr, 48)
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
        report('%s: arch slides over and sits on the handle' % n,
               vol(solids[n], prism(handle_path, *xs)))
        report('%s: pad slides over and sits on the wire' % n,
               vol(solids[n], prism(wire_path, *xs)))
    for n in ['Bracket_L', 'Bracket_R', 'Spacer']:
        report('%s: iPad slides in and out from above' % n, vol(solids[n], ipad_path))

    # Captured: nudge each bracket 3 mm every 45 degrees round the side view,
    # and turn it 3 degrees about the handle and about the wire. Everything
    # must hit the handle or the wire except moves with an upward component
    # (gravity holds those; the zip ties back it up).
    cart = handle + wire
    print('\ncaptured (only upward moves may be free):')
    for n in ['Bracket_L', 'Bracket_R']:
        free = []
        for deg in range(0, 360, 45):
            dy, dz = 3 * math.cos(math.radians(deg)), 3 * math.sin(math.radians(deg))
            if vol(solids[n].translate((0, dy, dz)), cart) <= 1e-3:
                free.append(deg)
        for label, (cy, cz) in [('handle', (0, 0)), ('wire', wc)]:
            for sign in (1, -1):
                m = solids[n].translate((0, -cy, -cz)).rotate((3 * sign, 0, 0)).translate((0, cy, cz))
                if vol(m, cart) <= 1e-3:
                    free.append('turn about the %s %+d deg' % (label, 3 * sign))
        upward = {45, 90, 135}
        bad = [f for f in free if f not in upward]
        ok &= not bad
        print('  %-50s %s' % ('%s: free moves %s' % (n, free or 'none'),
                              'ok' if not bad else 'FAIL (would come off)'))

    # Zip-tie loops, 2.5 mm bands at the tunnel X. Handle tie: up the tunnel
    # behind the back plate, over the arch, down its cart side, under the
    # tube. Wire tie: out of the pad tunnel at both sides and under the wire.
    rs, br, nm = P['r_sad'], P['bore_r'], P['n_b'] + P['hook_gap'] / 2

    def y_on(z, n):
        return pvn((z - P['ipad_z0'] + n * s) / c, n)[0]

    band = (box(y_on(rs, nm) + 2, rs + 0.05, rs + 2.5, rs + 2.5)
            + box(rs + 0.05, -br - 2.5, rs + 2.5, rs + 2.5)
            + box(y_on(-br, nm) + 2, -br - 2.5, rs + 2.5, -hr - 0.05))
    rp, rw = P['r_pad'], P['r_wb']
    z_top = wc[1] + rw + P['tun_floor']
    wband = (box(wc[0] - rp - 2.5, wc[1] - rw - 2.5, wc[0] + rp + 2.5, wc[1] - rw - 0.05)
             + box(wc[0] + rp + 0.05, wc[1] - rw - 2.5, wc[0] + rp + 2.5, z_top)
             + box(wc[0] - rp - 2.5, wc[1] - rw - 2.5, wc[0] - rp - 0.05, z_top))
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
    global SCRIPT
    args = [a for a in sys.argv[1:] if not a.startswith('--script=')]
    for a in sys.argv[1:]:
        if a.startswith('--script='):
            SCRIPT = a.split('=', 1)[1]
    overrides = dict(a.split('=', 1) for a in args)
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
