"""Test hardware/cad/IPadMount/IPadMount.py without Fusion.

    uv run --with manifold3d --with numpy --with matplotlib hardware/cad/check/check.py
    ... check.py drop_tops="150 mm" screen_angle="35 deg"   # try other parameter values
    ... check.py --script=path/to/other/IPadMount.py        # check another version

1. Runs the script against a mock of Fusion's API (adsk/): every expression
   must evaluate and every sketch dimension must match the geometry it was
   drawn at, and the auto-fillet / chamfer / STL code paths run.
2. Rebuilds every extrusion as a real solid (manifold3d) and checks: each
   printable part is one solid; nothing overlaps the iPad, handle, wire,
   middle bars, mesh wires or each other; the L (with its brace bolted on)
   hangs on without hitting anything (held 2 cm high, slid toward the cart,
   set down); the cap goes up under the wire past everything; the cap
   bolts can be reached from outside; the bolts reach through the nuts;
   with the cap on, every nudge or turn hits the cart (nothing can move);
   the iPad slides in from above.
3. Hand calcs: loads on one bracket, the reactions at the handle and the
   wire, and a factor of safety for every member, bolt and bearing face.
   Fails below 2.
4. Writes hardware/cad/stl/preview_*.stl (no fillets or chamfers: fine for
   the fit tests; Fusion's own export is the real print file),
   hardware/cad/stl/preview.png (3D) and hardware/cad/stl/profile.png (the
   side profile with the cart and the clearances).

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

SIDES = [('Bracket_L', 'Brace_L', 'Cap_L', -1), ('Bracket_R', 'Brace_R', 'Cap_R', 1)]
PRINTABLE = ['Bracket_L', 'Bracket_R', 'Brace_L', 'Brace_R', 'Cap_L', 'Cap_R',
             'TEST_Corner', 'TEST_Profile']

# PLA as printed, conservative. Every part prints lying on its side, so the
# side view is the layer plane, and every load path below stays in it: the
# in-plane values apply. (Across layers PLA is nearer 12 MPa; nothing here
# pulls layers apart.)
PLA_STRENGTH = 30.0     # MPa, tension / bending
PLA_BEARING = 30.0      # MPa, bolt bearing on a hole
PLA_E = 3000.0          # MPa
PLA_DENSITY = 1.24e-6   # kg/mm3, solid (conservative: real parts are ~half infill)
BOLT_SHEAR = 300.0      # MPa, 10-32 steel bolt (18-8 stainless, conservative)
BOLT_ROOT_D = 3.86      # mm, 10-32 minor diameter
BOLT_D = 4.83           # mm, 10-32 major diameter (bearing)
HEAD_D = 9.5            # mm, pan head (socket heads are 7.9)
DRIVER_D = 6.0          # mm, hex key or screwdriver shaft + clearance
G = 9.81
FOS_MIN = 2.0


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
    for m in adsk.core.LOG['messages']:
        if 'Warnings:' in m:
            print('  popup warnings:\n    ' + m.split('Warnings:', 1)[1].strip().replace('\n', '\n    '))
    ok = not (failed or L['dim_errors'] or L['eval_errors'])
    # params in mm (lengths) / rad (angles) / plain numbers, keyed by name
    units = dict((n, u) for n, _, u, _ in mod.PARAMS)
    P = dict((k, v * 10 if units.get(k) == 'mm' else v) for k, v in L['params'].items())
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

    solids, empty_cuts = {}, []
    for i, p in enumerate(fusion.LOG['prisms']):
        m = prism(section(p['shapes']), p['x0'] * 10, p['x1'] * 10)
        if p['op'] == 'CUT':
            before = solids[p['comp']].volume()
            solids[p['comp']] = solids[p['comp']] - m
            if before - solids[p['comp']].volume() < 1e-3:   # Fusion rejects these
                empty_cuts.append('%s cut #%d' % (p['comp'], i))
        else:
            solids[p['comp']] = solids.get(p['comp'], Manifold()) + m
    solids['_empty_cuts'] = empty_cuts
    return solids, prism


def centroid(np, m):
    mesh_ = m.to_mesh()
    v = np.asarray(mesh_.vert_properties)[:, :3]
    tri = v[np.asarray(mesh_.tri_verts)]
    w = np.einsum('ij,ij->i', tri[:, 0], np.cross(tri[:, 1], tri[:, 2])) / 6.0
    return (w[:, None] * tri.sum(axis=1) / 4.0).sum(axis=0) / w.sum()


def solid_checks(P, results):
    import numpy as np
    from manifold3d import CrossSection, FillRule, Manifold
    solids, prism = solids_from_log(np, CrossSection, FillRule, Manifold)
    ok = True

    def report(label, v, tol=1e-3):
        nonlocal ok
        good = v <= tol
        ok &= good
        print('  %-58s %s' % (label, 'ok' if good else 'FAIL (%.1f mm3)' % v))

    def vol(a, b):
        return (a ^ b).volume()

    empty_cuts = solids.pop('_empty_cuts')
    printable = [n for n in PRINTABLE if n in solids]
    print('\nparts:')
    for n in printable:
        m = solids[n]
        bodies = len([q for q in m.decompose() if abs(q.volume()) > 1.0])
        good = (not m.is_empty()) and bodies == 1
        ok &= good
        print('  %-13s %6.1f cm3  %s' % (n, m.volume() / 1000,
                                         'one solid, ok' if good else 'FAIL (%d pieces)' % bodies))

    good = not empty_cuts
    ok &= good
    print('  %-58s %s' % ('every cut removes material (Fusion rejects empty cuts)',
                          'ok' if good else 'FAIL: ' + ', '.join(empty_cuts)))

    ipad, handle, wire = solids['REF_iPad'], solids['REF_Handle'], solids['REF_Wire']
    bars, mesh = solids.get('REF_Bars'), solids.get('REF_Mesh')
    refs = [('iPad', ipad), ('handle', handle), ('wire', wire)]
    if bars is not None:
        refs.append(('middle bars', bars))
    if mesh is not None:
        refs.append(('mesh wires', mesh))
    cart = Manifold()
    for _, m in refs[1:]:
        cart = cart + m
    print('\noverlaps:')
    for side in SIDES:
        for n in side[:3]:
            for ref, m in refs:
                report('%s vs %s' % (n, ref), vol(solids[n], m))
        b, br, cp, _ = side
        for x, y in ((b, br), (b, cp), (br, cp)):
            report('%s vs %s' % (x, y), vol(solids[x], solids[y]))

    # The cart in the side view, as convex pieces (so sweeping one is just a
    # hull) with the X ranges they occupy.
    bx, hr, wr = P['bx_o'], P['handle_d'] / 2, P['rim_d'] / 2
    wc = (P['rim_dy'], -P['rim_drop'])
    rc = P['rim_c']
    full = [(-400.0, 400.0)]
    feats = [('handle', [CrossSection.circle(hr, 96)], full),
             ('wire', [CrossSection.circle(wr, 48).translate(wc)], full)]
    if bars is not None:
        feats.append(('middle bars',
                      [CrossSection.square((P['bar1_w'], P['bar1_h']), True)
                       .translate((P['bar1_y'], P['bar1_z'])),
                       CrossSection.circle(P['bar2_d'] / 2, 48).translate((P['bar2_y'], P['bar2_z']))],
                      full))
    mesh_x = []
    if mesh is not None:
        md, L = P['mesh_d'], rc + 20
        ux, uz = P['rim_dy'] / rc, -P['rim_drop'] / rc        # along the line
        px, pz = P['rim_drop'] / rc, P['rim_dy'] / rc         # across it
        band = CrossSection([np.array([(a * ux + w * px, a * uz + w * pz)
                                       for a, w in [(0, -md / 2), (L, -md / 2),
                                                    (L, md / 2), (0, md / 2)]])],
                            FillRule.NonZero)
        xr = []
        for k in range(int(round(P['mesh_n']))):
            xk = P['mesh_x0'] + k * P['mesh_pitch']
            mesh_x.append(xk)
            xr += [(-xk - md / 2, -xk + md / 2), (xk - md / 2, xk + md / 2)]
        feats.append(('mesh wires', [band], xr))

    # (1) Hang the L, brace already bolted on: held `lift` high on your side,
    # slid toward the cart, set straight down. In the bracket's frame the
    # cart comes in from the basket side `lift` low, then rises into place.
    lift, slide = 20.0, 300.0

    def dogleg(piece):
        low = piece.translate((0, -lift))
        return (low + low.translate((slide, 0))).hull() + (low + piece).hull()

    paths = []
    for name, pieces, xr in feats:
        sec = CrossSection()
        for piece in pieces:
            sec = sec + dogleg(piece)
        solid = Manifold()
        for x0, x1 in xr:
            solid = solid + prism(sec, x0, x1)
        paths.append((name, solid))
    t = P['tilt']
    s, c = math.sin(t), math.cos(t)

    def pvn(v, n):
        return (P['ipad_y0'] + v * s + n * c, P['ipad_z0'] + v * c - n * s)

    H, D, W = P['ipad_h'], P['ipad_d'], P['ipad_w']
    ipad_path = prism(CrossSection([np.array([pvn(0, 0), pvn(H + 300, 0), pvn(H + 300, D),
                                              pvn(0, D)])], FillRule.NonZero), -W / 2, W / 2)
    label = {'handle': 'arch goes onto the handle', 'wire': 'foot goes onto the wire',
             'middle bars': 'clears the middle bars on the way',
             'mesh wires': 'clears the mesh wires on the way'}
    print('\nassembly (L + brace: %g mm high, slide toward the cart, set down; '
          'then the cap from below):' % lift)
    for b, br, cp, _ in SIDES:
        Lb = solids[b] + solids[br]
        for name, path in paths:
            report('%s + brace: %s' % (b, label[name]), vol(Lb, path))
    # (2) The cap goes straight up under the wire, past the L and the brace.
    for b, br, cp, _ in SIDES:
        fixed = cart + solids[b] + solids[br]
        worst = max(vol(solids[cp].translate((0, 0, -k)), fixed) for k in range(1, 41))
        report('%s: goes up under the wire past everything' % cp, worst)
    for b, br, cp, _ in SIDES:
        report('%s: iPad slides in and out from above' % b,
               vol(solids[b] + solids[br] + solids[cp], ipad_path))
    # (3) Bolt heads clear the cart; a driver along X from outside reaches
    # the cap bolts (the brace is bolted on at the bench).
    print('\nbolts:')
    for plate in ('brace_t', 'cap_t'):
        spare = P['bolt_len'] - (P[plate] + P['nut_s'] + P['nut_t'])
        good = spare >= 0.8
        ok &= good
        print('  %-58s %s' % ('1/2" bolt through %s reaches %.1f mm past the nut (need 0.8)'
                              % (plate, spare), 'ok' if good else 'FAIL'))
    # every nut slot keeps at least 1 mm of plastic on each side but its open one
    slot_c = math.hypot(P['nut_c'], P['nut_w'] / 2)
    for where, wall in [('under the foot nut slots', P['cb_dz'] - P['nut_c']),
                        ('foot nut slot to wire, shopper side',
                         P['rim_dy'] - P['r_wb'] - P['cb1_y'] - P['nut_w'] / 2),
                        ('foot nut slot to wire, basket side',
                         P['cb2_y'] - P['nut_w'] / 2 - P['rim_dy'] - P['r_wb']),
                        ('round the brace nut slots', P['boss_d'] / 2 - slot_c)]:
        good = wall >= 1.0
        ok &= good
        print('  %-58s %s' % ('plastic %s: %.1f mm (need 1)' % (where, wall), 'ok' if good else 'FAIL'))
    for b, br, cp, sd in SIDES:
        others = cart + solids[b] + solids[br] + solids[cp]
        for part, plate, pts in ((br, 'brace_t', [(P['j1y'], P['j1z']), (P['j2y'], P['j2z'])]),
                                 (cp, 'cap_t', [(P['cb1_y'], P['cb_z']), (P['cb2_y'], P['cb_z'])])):
            x0 = bx + P[plate]
            for k, (y, z) in enumerate(pts):
                head = prism(CrossSection.circle(HEAD_D / 2, 48).translate((y, z)),
                             *sorted((sd * x0, sd * (x0 + P['head_h']))))
                report('%s bolt %d: head clears the cart' % (part, k + 1), vol(head, cart))
                if part == cp:
                    drv = prism(CrossSection.circle(DRIVER_D / 2, 48).translate((y, z)),
                                *sorted((sd * (x0 + P['head_h']), sd * 400.0)))
                    report('%s bolt %d: driver reaches it from outside' % (part, k + 1),
                           vol(drv, others))

    # (4) Captured: with the cap on, nudge the bracket 3 mm every 45 degrees
    # round the side view and turn it 3 degrees each way about the handle
    # and about the wire. Every move must hit the cart.
    print('\ncaptured (cap on: every nudge or turn must hit the cart):')
    for b, br, cp, _ in SIDES:
        body = solids[b] + solids[br] + solids[cp]
        moves = []
        for deg in range(0, 360, 45):
            dy, dz = 3 * math.cos(math.radians(deg)), 3 * math.sin(math.radians(deg))
            moves.append(('move %d deg' % deg, body.translate((0, dy, dz))))
        for name, (cy, cz) in [('handle', (0, 0)), ('wire', wc)]:
            for a in (3, -3):
                moves.append(('turn %+d deg about the %s' % (a, name),
                              body.translate((0, -cy, -cz)).rotate((a, 0, 0)).translate((0, cy, cz))))
        free = [name for name, m in moves if vol(m, cart) <= 1e-3]
        ok &= not free
        print('  %s: %s' % (b, 'nothing moves, ok' if not free
                            else 'FAIL, free: ' + ', '.join(free)))

    # Along the handle, nothing but friction holds a bracket: the foot and
    # the cap sit between two mesh wires, which limit the slide.
    if mesh_x:
        md = P['mesh_d']
        lo, hi = bx - P['hook_w'], bx + P['cap_t'] + P['head_h']
        inner = max([x + md / 2 for x in mesh_x if x + md / 2 <= lo] or [float('nan')])
        outer = min([x - md / 2 for x in mesh_x if x - md / 2 >= hi] or [float('nan')])
        lap = P['lip_w'] - P['clr']
        print('\nalong the handle (no overlap check here, just the numbers):')
        print('  each foot can slide %.1f mm in and %.1f mm out before a mesh wire stops it'
              % (lo - inner, outer - hi))
        print('  side lips cover %.1f mm of bezel; one bracket slid all the way out leaves %.1f mm,'
              % (lap, lap - (outer - hi)))
        print('  both out with the iPad against one side leaves %.1f mm: the zip tie between the'
              % (lap - 2 * (outer - hi)))
        print('  upper struts stops that')

    results['solids'] = solids
    results['cart'] = cart
    return ok


# ------------------------------------------------------------ 3. hand calcs
def hand_calcs(P, solids):
    """First-principles statics for one bracket in the side view.

    Supports: the handle (the arch: it can push the bracket any way between
    the basket side and arch_a1, never down) and the wire (the foot and the
    cap: any way). One bracket is indeterminate by one: the load along the
    handle-to-wire line can go to either support. Both limits are taken and
    each member is checked at its worse one. Members are checked with simple
    conservative models (each named below), and every FoS must be >= 2."""
    import numpy as np

    def cross(a, b):
        return float(a[0] * b[1] - a[1] * b[0])

    def V(y, z):
        return np.array([float(y), float(z)])

    t = P['tilt']
    s_, c_ = math.sin(t), math.cos(t)
    y0, z0 = P['ipad_y0'], P['ipad_z0']

    def pvn(v, n):
        return V(y0 + v * s_ + n * c_, z0 + v * c_ - n * s_)

    up_scr, into = V(s_, c_), V(c_, -s_)   # up the screen; into it (toward the cart)
    rc = P['rim_c']
    u = V(P['rim_dy'], -P['rim_drop']) / rc   # handle -> wire
    w = V(P['rim_drop'], P['rim_dy']) / rc    # across it, toward the basket
    Wp = V(P['rim_dy'], -P['rim_drop'])
    phi = math.atan2(P['rim_dy'], P['rim_drop'])
    a1 = P['arch_a1']

    # masses and centres, one bracket
    m_ipad = P['ipad_g'] / 2 / 1000.0
    body = solids['Bracket_L'] + solids['Brace_L'] + solids['Cap_L']
    m_br = body.volume() * PLA_DENSITY
    cg_br = V(*centroid(np, body)[1:])
    cg_ipad = pvn(P['ipad_h'] / 2, P['ipad_d'] / 2)
    Wi, Wb = m_ipad * G, m_br * G
    top = pvn(P['ipad_h'], 0)
    ch_top = pvn(P['v_t'], P['n_b'])
    F_t = 10.0 * 0.75                       # 10 N finger, 75 % on the nearer bracket
    down, fwd = V(0, -1), V(1, 0)

    def grav(k=1.0):
        return [(k * Wi * down, cg_ipad, 'ipad'), (k * Wb * down, cg_br, 'bracket')]

    cases = [
        ('gravity', grav()),
        ('bump, 3 g', grav(3)),
        ('finger push 10 N on the top edge', grav() + [(F_t * into, top, 'push')]),
        ('pull 10 N on the top edge', grav() + [(-F_t * into, top, 'pull')]),
        ('hand resting on the top edge, 20 N', grav() + [(20 * down, top, 'push')]),
        ('hard stop: 1 g toward the basket', grav() + [(Wi * fwd, cg_ipad, 'ipad'),
                                                       (Wb * fwd, cg_br, 'bracket')]),
        ('jerked: 1 g toward you', grav() + [(-Wi * fwd, cg_ipad, 'ipad'),
                                             (-Wb * fwd, cg_br, 'bracket')]),
        ('lifted by the channel top, 30 N', grav() + [(30 * V(0, 1), ch_top, 'lift')]),
    ]

    # points and sections
    C = V(P['lr_y'], P['lr_z'])               # corner of the L (leg root)
    J1, J2 = V(P['j1y'], P['j1z']), V(P['j2y'], P['j2z'])
    e_leg = V(P['leg_uy'], P['leg_uz'])
    e_br = (J1 - J2) / np.linalg.norm(J1 - J2)  # brace, bottom joint toward the top one
    lever_br = cross(J2 - C, e_br)
    # the leg narrows from strut_w at the root to its cut end on the foot
    w_end = (P['ft_z1'] + P['rim_drop'] - 2) * abs(P['leg_uy'])
    w_j2 = P['strut_w'] + P['leg_f'] * (w_end - P['strut_w'])
    r_mid = P['r_sad'] - P['sad_t'] / 2
    Z_arch, A_arch = P['arm_w'] * P['sad_t'] ** 2 / 6, P['arm_w'] * P['sad_t']
    t_ch = P['n_b'] - P['n_r']                # back plate + back rest
    Z_ch = (P['wall_t'] + P['grip']) * t_ch ** 2 / 6
    A_bolt = math.pi / 4 * BOLT_ROOT_D ** 2
    # upper strut: from the channel at top_v to the middle of its arch landing
    am = (P['top_a0'] + P['top_a1']) / 2
    S = V(r_mid * math.cos(am), r_mid * math.sin(am))
    T = pvn(P['top_v'] - P['strut_w'] / 2, P['n_b'])
    e_st = (S - T) / np.linalg.norm(S - T)
    L_st = float(np.linalg.norm(S - T))
    vA = P['v_c1']                            # arch top on the back plate: the channel is cantilevered above it
    A = pvn(vA, P['n_b'])
    # arch end on the back plate, for the back plate between the brace and the arch
    ae = V(P['r_sad'] * math.cos(a1), P['r_sad'] * math.sin(a1))
    v_ae = float(np.dot(ae - V(y0, z0), up_scr))
    # web from the brace top joint to the end of the arch: its outer edge, in screen coords
    rw = P['bore_r'] + P['web_gap']
    Wa = V(rw * math.cos(a1), rw * math.sin(a1))

    def scr(p):
        d = p - V(y0, z0)
        return float(np.dot(d, up_scr)), float(np.dot(d, into))

    (vj, nj), (vw, nw) = scr(J1), scr(Wa)

    def web_stress(f):
        """Back plate + back rest + web as one rectangle (strut_t wide, from
        the back rest face to the web's outer edge), at stations from the
        brace joint up to where the arch takes over."""
        worst_s = 0.0
        for v in np.linspace(vj, vw, 25):
            n_out = max(P['n_b'], nj + (nw - nj) * (v - vj) / (vw - vj))
            d = n_out - P['n_r']
            pc = pvn(v, (n_out + P['n_r']) / 2)
            m = abs(cross(J1 - pc, f))
            nax = abs(float(np.dot(f, up_scr)))
            worst_s = max(worst_s, m / (P['strut_t'] * d ** 2 / 6) + nax / (P['strut_t'] * d))
        return worst_s

    v_lip = P['lip_h'] / 2
    v_tl = (P['ipad_h'] - P['win_hi'] + P['v_t']) / 2   # top side lip, middle

    def channel_loads(loads):
        """The forces the channel above the arch carries, (force, point)."""
        out = []
        for f, p, tag in loads:
            fn = float(np.dot(f, into))      # into the screen
            if tag == 'ipad':                 # spread over the back rest band
                lo, hi = P['rest_lo'], P['rest_hi']
                if hi > vA:
                    frac = (hi - max(vA, lo)) / (hi - lo)
                    out.append((fn * frac * into, pvn((max(vA, lo) + hi) / 2, P['n_r'])))
            elif tag == 'push':               # the iPad tips on the top of the back rest
                k = (P['ipad_h'] - v_lip) / (P['rest_hi'] - v_lip)
                out.append((k * fn * into, pvn(P['rest_hi'], P['n_r'])))
            elif tag == 'pull':               # held by the top side lips
                k = (P['ipad_h'] - v_lip) / (v_tl - v_lip)
                out.append((k * fn * into, pvn(v_tl, -P['clr'])))
            elif tag == 'lift':
                out.append((f, p))
        return out

    worst = {}

    def note(key, value, limit, case, unit, kind='strength'):
        fos = limit / value if value > 1e-9 else float('inf')
        if key not in worst or fos < worst[key][0]:
            worst[key] = (fos, value, limit, case, unit, kind)

    print('\nhand calcs (one bracket; iPad %.0f g per bracket, bracket + brace + cap %.0f g solid;'
          % (m_ipad * 1000, m_br * 1000))
    print('  PLA %g MPa in the print plane, bolts %g MPa in shear):' % (PLA_STRENGTH, BOLT_SHEAR))
    print('  %-38s %9s %10s %10s %9s' % ('load case', 'handle N', 'wire N', 'cap pull N', 'brace N'))
    for case, loads in cases:
        F = sum((f for f, _, _ in loads), V(0, 0))
        M = sum(cross(p, f) for f, p, _ in loads)          # about the handle centre
        Wperp = -M / rc
        Fpar, Fperp = float(np.dot(F, u)), float(np.dot(F, w))
        cc = -(Fperp + Wperp)                              # handle's push along w
        if cc >= 0:
            lam_min = -cc * math.tan(phi)
        elif a1 - phi > math.pi / 2:
            lam_min = cc * math.tan(a1 - phi)
        else:
            lam_min = float('inf')
        splits = [lam_min, max(lam_min, Fpar)]             # wire takes the most / handle does
        hmax = wmax = cap = brace = 0.0
        for lam in splits:
            Hv = -lam * u + cc * w
            Wv = Wperp * w - (Fpar - lam) * u
            hmax, wmax = max(hmax, float(np.linalg.norm(Hv))), max(wmax, float(np.linalg.norm(Wv)))
            pull = max(0.0, float(np.dot(Wv, u)))          # wire pulling the foot down: the cap
            cap = max(cap, pull)
            # arch: the whole reaction at the far end of a cantilevered band
            Hn = float(np.linalg.norm(Hv))
            note('arch (bending + axial)', Hn * r_mid / Z_arch + Hn / A_arch, PLA_STRENGTH, case, 'MPa')
            # leg pinned at the corner, held by the brace at J2 (conservative for the brace)
            Mc = cross(Wp - C, Wv)
            Nbr = -Mc / lever_br                           # + = tension
            brace = max(brace, abs(Nbr))
            note('brace (axial)', abs(Nbr) / (P['brace_t'] * P['brace_w']), PLA_STRENGTH, case, 'MPa')
            if Nbr < 0:
                Pcr = math.pi ** 2 * PLA_E * (P['brace_w'] * P['brace_t'] ** 3 / 12) / P['br_len'] ** 2
                note('brace buckling (pinned ends, thin way)', -Nbr, Pcr, case, 'N', 'buckling')
            note('brace bolts: steel shear', abs(Nbr) / A_bolt, BOLT_SHEAR, case, 'MPa')
            note('brace bolts: bearing in the brace', abs(Nbr) / (BOLT_D * P['brace_t']),
                 PLA_BEARING, case, 'MPa')
            note('brace bolts: bearing in the L (skin by the nut only)',
                 abs(Nbr) / (BOLT_D * P['nut_s']), PLA_BEARING, case, 'MPa')
            Fj1 = Nbr * (J2 - J1) / np.linalg.norm(J2 - J1)   # brace force on the L at J1
            note('back plate + web, brace top up to the arch (bending + axial)',
                 web_stress(Fj1), PLA_STRENGTH, case, 'MPa')
            # leg from the brace joint to the foot: a cantilever off J2
            Mj = abs(cross(Wp - J2, Wv))
            Nl = abs(float(np.dot(Wv, e_leg)))
            note('leg, brace joint to foot (bending + axial)',
                 Mj / (P['strut_t'] * w_j2 ** 2 / 6) + Nl / (P['strut_t'] * w_j2),
                 PLA_STRENGTH, case, 'MPa')
            note('foot on the wire (bearing)', float(np.linalg.norm(Wv)) / (P['rim_d'] * P['hook_w']),
                 PLA_BEARING, case, 'MPa')
            # info: the corner with the brace left off
            note('(info) leg at the corner if the brace is left off',
                 abs(Mc) / (P['strut_t'] * P['strut_w'] ** 2 / 6), PLA_STRENGTH, case, 'MPa', 'info')
        # cap: two bolts share the pull; the base spans between them
        if cap > 0:
            sp = P['cb2_y'] - P['cb1_y']
            note('cap under the wire (bending between its bolts)',
                 cap * sp / 4 / (P['cap_t'] * P['cap_wall'] ** 2 / 6), PLA_STRENGTH, case, 'MPa')
            note('cap bolts: steel shear', cap / 2 / A_bolt, BOLT_SHEAR, case, 'MPa')
            note('cap bolts: bearing in the cap', cap / 2 / (BOLT_D * P['cap_t']), PLA_BEARING, case, 'MPa')
            note('cap bolts: bearing in the foot (skin by the nut only)',
                 cap / 2 / (BOLT_D * P['nut_s']), PLA_BEARING, case, 'MPa')
        # channel above the arch: held by the upper strut at T (pinned at A),
        # and as a bare cantilever (strut ignored)
        MA = sum(cross(p - A, f) for f, p in channel_loads(loads))
        Nst = -MA / cross(T - A, e_st) if abs(cross(T - A, e_st)) > 1e-6 else 0.0
        note('upper strut (axial)', abs(Nst) / (P['strut_t'] * P['strut_w']), PLA_STRENGTH, case, 'MPa')
        if Nst < 0:
            Pcr = math.pi ** 2 * PLA_E * (P['strut_t'] * P['strut_w'] ** 3 / 12) / L_st ** 2
            note('upper strut buckling (pinned ends)', -Nst, Pcr, case, 'N', 'buckling')
        # bending along the channel above the arch, strut acting (pinned at A)
        vT = float(np.dot(T - V(y0, z0), up_scr))
        cl = channel_loads(loads)
        mmax = 0.0
        for v in np.linspace(vA, P['v_t'], 40):
            pv = pvn(v, (P['n_r'] + P['n_b']) / 2)
            m = sum(cross(p - pv, f) for f, p in cl if float(np.dot(p - V(y0, z0), up_scr)) > v)
            if v < vT:
                m += cross(T - pv, Nst * e_st)
            mmax = max(mmax, abs(m))
        note('channel above the handle (bending, strut acting)', mmax / Z_ch, PLA_STRENGTH, case, 'MPa')
        note('(info) channel above the handle if the strut were missing', abs(MA) / Z_ch,
             PLA_STRENGTH, case, 'MPa', 'info')
        print('  %-38s %9.1f %10.1f %10.1f %9.1f' % (case, hmax, wmax, cap, brace))

    print('\n  %-58s %-36s %15s %6s' % ('member / check (worst case)', '', 'value / limit', 'FoS'))
    ok = True
    for key, (fos, value, limit, case, unit, kind) in worst.items():
        info = kind == 'info'
        good = info or fos >= FOS_MIN
        ok &= good
        val = '%.1f / %.0f %s' % (value, limit, unit)
        fs = 'inf' if fos >= 1e4 else ('%.1f' % fos if fos < 10 else '%.0f' % fos)
        print('  %-58s %-36s %15s %6s %s' % (key, case, val, fs,
                                             '' if info else ('ok' if good else 'FAIL')))
    # play from the clearances (the parts are rigid; this is what wobbles)
    d_top_h = float(np.linalg.norm(top))
    d_top_w = float(np.linalg.norm(top - Wp))
    print('\n  play from the clearances: about the handle %.2f deg (foot fit %.1f mm), about the wire '
          '%.2f deg (arch fit %.1f mm)' % (math.degrees(P['rim_fit'] / rc), P['rim_fit'],
                                            math.degrees(P['handle_fit'] / rc), P['handle_fit']))
    print('  -> the screen top can shift about %.1f mm before it is held'
          % (P['rim_fit'] / rc * d_top_h + P['handle_fit'] / rc * d_top_w))
    print('  hand calcs: %s (every FoS >= %g)' % ('ok' if ok else 'FAIL', FOS_MIN))
    return ok


# --------------------------------------------------------------- 4. outputs
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
            ('Brace_L', '#e8962e', 1), ('Brace_R', '#e8962e', 1),
            ('Cap_L', '#3a9d5d', 1), ('Cap_R', '#3a9d5d', 1),
            ('REF_Handle', '#444444', 0.5), ('REF_Wire', '#444444', 0.5),
            ('REF_Bars', '#444444', 0.5), ('REF_Mesh', '#888888', 0.4)]
    light = np.array([-0.4, -0.7, 0.6])
    light /= np.linalg.norm(light)
    fig = plt.figure(figsize=(14, 7))
    for k, (elev, azim, title) in enumerate([(22, -125, 'from the shopper side'),
                                             (5, 0, 'side view (shopper on the left)')]):
        ax = fig.add_subplot(1, 2, k + 1, projection='3d')
        for n, col, a in show:
            if n not in solids:
                continue
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


def profile_png(solids, P, path):
    """Side profile of the left bracket, brace and cap (shopper on the left),
    sliced from the real solids, with the cart and the iPad, part names and
    key numbers."""
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, PathPatch, Polygon, Rectangle
    from matplotlib.path import Path
    from manifold3d import CrossSection
    # (X, Y, Z) -> (Y, Z, X) so a slice at constant X is the side view
    back = np.array([[0, 1, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0]], dtype=float)
    bx = P['bx_o']
    sil = CrossSection()
    br = solids['Bracket_L'].transform(back)
    for x in np.arange(-bx + 0.5, -bx + 34, 1.0):
        sil = sil + br.slice(float(x))
    brace = solids['Brace_L'].transform(back).slice(float(-bx - P['brace_t'] / 2))
    cap = solids['Cap_L'].transform(back).slice(float(-bx - P['cap_t'] / 2))
    fig, ax = plt.subplots(figsize=(8, 10))
    t = P['tilt']
    s, c = math.sin(t), math.cos(t)

    def pvn(v, n):
        return (P['ipad_y0'] + v * s + n * c, P['ipad_z0'] + v * c - n * s)

    def draw(sec, fc, ec, lab, z=2):
        verts, codes = [], []
        for poly in sec.to_polygons():          # outlines + holes, one compound path
            poly = np.asarray(poly)
            verts += list(poly) + [poly[0]]
            codes += [Path.MOVETO] + [Path.LINETO] * (len(poly) - 1) + [Path.CLOSEPOLY]
        ax.add_patch(PathPatch(Path(verts, codes), fc=fc, ec=ec, lw=1.2, alpha=0.9, label=lab,
                               zorder=z))

    H, D = P['ipad_h'], P['ipad_d']
    ax.add_patch(Polygon([pvn(0, 0), pvn(H, 0), pvn(H, D), pvn(0, D)], closed=True,
                         fc='#e9edf1', ec='#8a96a3', lw=1, label='iPad'))
    draw(sil, '#2f7fd8', '#0b3d7a', 'the L (one print per side)')
    draw(brace, '#e8962e', '#8a4b00', 'brace (separate print, bolted)', 3)
    draw(cap, '#3a9d5d', '#1d5631', 'cap (separate print, bolted under the wire)', 3)
    for y, z in [(P['j1y'], P['j1z']), (P['j2y'], P['j2z']), (P['cb1_y'], P['cb_z']),
                 (P['cb2_y'], P['cb_z'])]:
        ax.add_patch(Circle((y, z), P['bolt_hole'] / 2, fc='k', ec='k', zorder=4))
    ax.plot([], [], 'o', color='k', ms=4, label='10-32 x 1/2" bolts (4 per side)')
    # cart: handle, wire, middle bars, and the mesh plane they sit in
    wc = (P['rim_dy'], -P['rim_drop'])
    rc = P['rim_c']
    ux, uz = P['rim_dy'] / rc, -P['rim_drop'] / rc
    ax.plot([0, (rc + 25) * ux], [0, (rc + 25) * uz], color='#999999', lw=1, ls='--',
            label='mesh plane (slanted wires at 60, 103, 146 mm ...)')
    ax.add_patch(Circle((0, 0), P['handle_d'] / 2, fc='#555555', ec='k', lw=0.8, label='handle'))
    ax.add_patch(Circle(wc, P['rim_d'] / 2, fc='#555555', ec='k', lw=0.8, label='wire', zorder=5))
    ax.add_patch(Rectangle((P['bar1_y'] - P['bar1_w'] / 2, P['bar1_z'] - P['bar1_h'] / 2),
                           P['bar1_w'], P['bar1_h'], fc='#d62728', ec='k', lw=0.6,
                           label='middle bars'))
    ax.add_patch(Circle((P['bar2_y'], P['bar2_z']), P['bar2_d'] / 2, fc='#d62728', ec='k', lw=0.6))

    def note(xy, text, dxy):
        ax.annotate(text, xy=xy, xytext=(xy[0] + dxy[0], xy[1] + dxy[1]), fontsize=10,
                    arrowprops=dict(arrowstyle='-', color='#333333', lw=0.7))

    rs = P['r_sad']
    top_y, top_z = pvn(P['top_v'], P['n_b'])
    a0, a1 = P['top_a0'], P['top_a1']
    am = ((rs * math.cos(a0) + rs * math.cos(a1)) / 2, (rs * math.sin(a0) + rs * math.sin(a1)) / 2)
    note(pvn(H * 0.75, -3), 'channel (holds one short edge)', (-95, 10))
    note((18 * math.cos(math.radians(125)), 18 * math.sin(math.radians(125))),
         'arch on the handle', (-95, -2))
    note(((top_y + am[0]) / 2, (top_z + am[1]) / 2), 'upper strut', (25, 5))
    note(((P['lr_y'] + P['j2y']) / 2 - 3, (P['lr_z'] + P['j2z']) / 2 - 3), 'leg', (-45, -20))
    note(((P['j1y'] + P['j2y']) / 2 - 6, (P['j1z'] + P['j2z']) / 2), 'brace', (-55, 0))
    note((P['ft_y0'] + 3, P['ft_z1']), 'foot on the wire', (-80, 15))
    note((P['cb1_y'], -P['rim_drop'] - P['r_wb'] - P['cap_wall'] / 2), 'cap', (-40, -20))
    (y0, z0), (y1, z1) = pvn(0, 0), pvn(H, 0)
    ax.annotate('screen %.0f° to the ground' % (90 - math.degrees(t)), xy=pvn(H * 0.4, 0),
                xytext=(y0 - 45, z0 + 75), fontsize=10, arrowprops=dict(arrowstyle='-', lw=0.7))
    ax.annotate('wire: %.0f mm toward the basket,\n%.0f mm below the handle centre'
                % (P['rim_dy'], P['rim_drop']), xy=wc, xytext=(wc[0] + 20, wc[1] + 40), fontsize=9,
                arrowprops=dict(arrowstyle='-', lw=0.7))

    # Side-view clearances from each part's outline to the cart
    def segs_of(sec):
        out = []
        for poly in sec.to_polygons():
            poly = np.asarray(poly)
            out.append(np.stack([poly, np.roll(poly, -1, axis=0)], axis=1))
        return np.concatenate(out)

    def gap(segs, points):
        a, b = segs[:, 0], segs[:, 1]
        ab = b - a
        tt = np.clip(np.einsum('ijk,jk->ij', points[:, None, :] - a[None], ab)
                     / np.maximum((ab * ab).sum(1), 1e-12)[None], 0, 1)
        d = np.linalg.norm(points[:, None, :] - (a[None] + tt[..., None] * ab[None]), axis=2)
        return d.min()

    def ring(cy, cz, r):
        th = np.linspace(0, 2 * np.pi, 180, endpoint=False)
        return np.c_[cy + r * np.cos(th), cz + r * np.sin(th)]

    def box_pts(cy, cz, w, h):
        e = np.linspace(-0.5, 0.5, 40)
        return np.r_[np.c_[cy + e * w, np.full(40, cz - h / 2)], np.c_[cy + e * w, np.full(40, cz + h / 2)],
                     np.c_[np.full(40, cy - w / 2), cz + e * h], np.c_[np.full(40, cy + w / 2), cz + e * h]]

    sL, sB, sC = segs_of(sil), segs_of(brace), segs_of(cap)
    bar1 = box_pts(P['bar1_y'], P['bar1_z'], P['bar1_w'], P['bar1_h'])
    bar2 = ring(P['bar2_y'], P['bar2_z'], P['bar2_d'] / 2)
    gaps = [('L to upper middle bar', gap(sL, bar1)),
            ('L to lower middle bar', gap(sL, bar2)),
            ('arch to handle (bore clearance)', gap(sL, ring(0, 0, P['handle_d'] / 2))),
            ('foot to wire (seat clearance)', gap(sL, ring(wc[0], wc[1], P['rim_d'] / 2))),
            ('brace to handle', gap(sB, ring(0, 0, P['handle_d'] / 2))),
            ('cap to wire (seat clearance)', gap(sC, ring(wc[0], wc[1], P['rim_d'] / 2)))]
    ax.text(0.02, 0.02, 'side-view clearances:\n' + '\n'.join('  %s: %.1f mm' % g for g in gaps),
            transform=ax.transAxes, fontsize=9, va='bottom', family='monospace')
    print('\nside-view clearances:')
    for name, g in gaps:
        print('  %-58s %.1f mm' % (name, g))
    ax.set_aspect('equal')
    ax.autoscale_view()
    xl, yl = ax.get_xlim(), ax.get_ylim()
    ax.set_xlim(xl[0] - 60, xl[1] + 70)
    ax.set_ylim(yl[0] - 35, yl[1] + 20)
    ax.grid(lw=0.3, color='#dddddd')
    ax.set_xlabel('mm  (shopper ←   → basket)')
    ax.set_ylabel('mm  (handle centre = 0)')
    ax.set_title('KART iPad mount: side profile (L + brace + cap)', fontsize=12)
    ax.legend(loc='upper left', fontsize=8, frameon=False)
    plt.tight_layout()
    plt.savefig(path, dpi=110)


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
    ok &= hand_calcs(P, solids)
    for n in PRINTABLE:
        if n in solids:
            write_stl(solids[n], os.path.join(OUT, 'preview_%s.stl' % n.lower()))
    preview_png(solids, os.path.join(OUT, 'preview.png'))
    profile_png(solids, P, os.path.join(OUT, 'profile.png'))
    print('\npreview STLs, preview.png, profile.png -> %s' % OUT)
    print('RESULT: %s' % ('ALL CHECKS PASS' if ok else 'CHECKS FAILED'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
