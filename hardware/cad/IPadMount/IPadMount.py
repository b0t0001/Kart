"""
KART iPad mount: parametric Fusion 360 script
=============================================

What it builds (in a NEW Fusion document, every run):
  * Bracket_L / Bracket_R: mirrored "bookends", one per side of the iPad.
    Each one hangs on the cart handle by a printed arch, and an arm from
    the bottom of the bracket reaches the top-basket wire, where a notched
    pad sits on top of it. Both open downward, so the mount simply hangs:
    hold it a couple of cm high, slide it toward the cart until the arches
    are over the handle and the pads over the wire, and set it down. Gravity
    seats it, the sides of the arch and the notch stop every push and twist,
    and the only way off is straight up, which the zip ties stop. Two
    attachment points on two different parts of the cart make a triangle,
    so the screen can't rotate around the handle.
    The upper part is a channel that holds one short edge of the iPad:
    ledge, side wall, front lips (on the bezel only) and a back plate.
  * Spacer: a bar behind the iPad that slides into a socket on each bracket
    and fixes their spacing, so the iPad can't drop between them. A zip tie
    through each socket pins it.
  * TEST_Profile / TEST_Corner: quick fit-test prints (README, "Fit test").
  * REF_ components: handle, wire and iPad envelopes. Don't print them.

The iPad (landscape, no case) hangs on the shopper's side of the handle. It
slides down into the two channels from above and rests on the ledges; lift it
straight up to take it out. Windows in the side walls leave the USB-C port,
speakers, mics and front camera clear, and the charging cable plugs in
through one of them. No screws anywhere: zip ties are the only hardware.

Two ways to change the model:
  1. Edit PARAMS below and re-run (fastest for big changes).
  2. In Fusion: Modify > Change Parameters. Every size and position in the
     timeline is driven by these named User Parameters.

Layout: X = along the handle (cart width), Y = forward (toward the basket),
Z = up. Origin = handle tube centre. The shopper stands at -Y; the screen
faces them and leans back by `tilt`. Each bracket is modelled in place and
prints lying on its outer side face (the big flat face).

Parameters whose comment starts with MEASURE are nominal or ruler numbers:
confirm them before the real print (README, "Measurements").

Helpers (Sk, extrude, new_component, ...) come from SmartCartEnclosure.py;
Sk gained poly() for the tilted shapes.
"""

import adsk.core
import adsk.fusion
import math
import os
import traceback

# STL export folder: hardware/cad/stl, next to this script's folder.
# Set to '' to skip the export.
try:
    STL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'stl')
except NameError:
    STL_DIR = ''
AUTO_FILLET = True      # CAD rule 3: fillet every corner by size, chamfer bed edges
BUILD_TESTS = True      # TEST_Profile and TEST_Corner fit-test prints
SHOW_REFERENCE = True   # grey REF_ envelopes (handle, wire, iPad); don't print

# ============================================================== PARAMETERS
# (name, expression, units, comment). Later entries may reference earlier ones.
PARAMS = [
    # iPad Pro 11-inch (2nd gen, 2020), bare, landscape. Apple's published
    # size; corner radius and camera bump are estimates.
    ('ipad_w',      '247.6 mm', 'mm', 'iPad long side = width in landscape (Apple: 247.6)'),
    ('ipad_h',      '178.5 mm', 'mm', 'iPad short side = height in landscape (Apple: 178.5)'),
    ('ipad_d',      '5.9 mm',   'mm', 'iPad thickness, not counting the camera bump (Apple: 5.9)'),
    ('ipad_r',      '10 mm',    'mm', 'MEASURE: iPad corner radius seen from the front (rough is fine)'),
    ('bump_zone',   '45 mm',    'mm', 'MEASURE: rear camera bump, far edge from the nearest long edge + 5 mm. The back rest stays out of this band at top and bottom'),
    ('bump_relief', '2 mm',     'mm', 'MEASURE: camera bump height + 0.5 mm (back plate gap outside the rest band)'),

    # Fit (no felt pads on this build)
    ('fit',         '0.4 mm',   'mm', 'Clearance per side around the iPad: raise if tight, lower if it rattles'),
    ('pad_t',       '0 mm',     'mm', 'Pad on the contact faces (0 = bare plastic; 0.2 for a layer of electrical tape)'),
    ('clr',         'fit + pad_t', 'mm', 'Total gap per side between iPad and plastic'),

    # Cart
    ('handle_d',    '29 mm',    'mm', 'MEASURE: handle tube diameter where the brackets sit (~29 by ruler; calipers please)'),
    ('handle_fit',  '0.5 mm',   'mm', 'Arch bore clearance per side (the zip tie pulls it snug)'),
    ('rim_d',       '5.5 mm',   'mm', 'MEASURE: top-basket wire diameter (~5.5 by ruler; calipers please)'),
    ('rim_fit',     '0.3 mm',   'mm', 'Wire notch clearance per side'),
    ('rim_c',       '155 mm',   'mm', 'MEASURE: handle centre to wire centre, straight line (~155 by ruler)'),
    ('rim_drop',    'rim_c',    'mm', 'MEASURE: wire centre BELOW handle centre (= rim_c: straight below). Plumb line from the handle centre: rim_drop = drop to the wire centre'),

    # Screen placement
    ('tilt',        '0 deg',    'deg', 'Screen lean-back from vertical (top edge toward the cart); 15-20 reads better from standing height'),
    ('v_h',         '70 mm',    'mm', 'Handle height behind the screen, measured up from the iPad bottom edge'),
    ('hook_gap',    '3 mm',     'mm', 'Gap between back plate and handle tube (a zip tie runs through it)'),

    # Channel (holds one short edge of the iPad)
    ('wall_t',      '4 mm',     'mm', 'Side wall thickness (the face that sits on the print bed)'),
    ('ledge_t',     '4 mm',     'mm', 'Ledge thickness under the iPad'),
    ('lip_t',       '2.4 mm',   'mm', 'Front lip thickness'),
    ('lip_w',       '6 mm',     'mm', 'Side front lip reach over the screen bezel (bezel ~9 mm: keep lip_w - clr below 8)'),
    ('lip_h',       '6 mm',     'mm', 'Bottom front lip height over the bottom bezel'),
    ('grip',        '30 mm',    'mm', 'How far the ledge and back plate reach in under the iPad'),
    ('back_t',      '3 mm',     'mm', 'Back plate thickness'),
    ('win_lo',      'ipad_r + 10 mm', 'mm', 'Side wall is solid up to here (bottom corner pocket); window above'),
    ('win_hi',      '22 mm',    'mm', 'Window ends this far below the iPad top edge'),
    ('top_drop',    '6 mm',     'mm', 'Channel stops this far below the iPad top edge (finger room to lift)'),
    ('btn_relief',  '1.5 mm',   'mm', 'Extra side clearance in the top segment, so it never presses the top button'),
    ('rest_lo',     'bump_zone', 'mm', 'Back rest band start (up from the iPad bottom edge)'),
    ('rest_hi',     'ipad_h - bump_zone', 'mm', 'Back rest band end'),

    # Hanger: arch over the handle, arm, pad on top of the wire
    ('sad_t',       '6 mm',     'mm', 'Arch wall thickness over the handle tube'),
    ('arm_w',       '24 mm',    'mm', 'Arch and wire pad width along the handle'),
    ('arm_t',       '10 mm',    'mm', 'Arm thickness along the handle'),
    ('arm_h',       '16 mm',    'mm', 'Arm width (in the side view)'),
    ('pad_wall',    '6 mm',     'mm', 'Wire pad wall around the notch'),
    ('zt_w',        '5.6 mm',   'mm', 'Zip-tie tunnel width (4.8 mm ties)'),
    ('zt_h',        '2.2 mm',   'mm', 'Zip-tie tunnel height'),
    ('tun_floor',   '1.4 mm',   'mm', 'Plastic between the wire tie tunnel and the notch'),

    # Spacer (behind the iPad, above the handle)
    ('sp_v',        '100 mm',   'mm', 'Spacer bottom, measured up the screen from the iPad bottom edge (keep it above the arch)'),
    ('sp_h',        '16 mm',    'mm', 'Spacer height (along the screen)'),
    ('sp_t',        '8 mm',     'mm', 'Spacer thickness (front to back)'),
    ('sfit',        '0.2 mm',   'mm', 'Slide fit per side, spacer in socket (fits table)'),
    ('sk_wall',     '2.5 mm',   'mm', 'Socket wall'),
    ('sk_l',        '26 mm',    'mm', 'Socket depth (spacer overlap into each bracket)'),
    ('sp_end',      '0.5 mm',   'mm', 'End gap, spacer to socket bottom'),
    ('pin_x',       '13 mm',    'mm', 'Socket tie slot position, in from the side wall inner face'),

    # Derived: don't edit, change the inputs above
    ('bx_o',        'ipad_w/2 + clr + wall_t', 'mm', 'derived: bracket outer face |X|'),
    ('v_b',         '-(clr + ledge_t)', 'mm', 'derived: ledge underside (screen coords)'),
    ('v_t',         'ipad_h - top_drop', 'mm', 'derived: channel top'),
    ('n_f',         '-(clr + lip_t)', 'mm', 'derived: front lip face'),
    ('n_r',         'ipad_d + clr', 'mm', 'derived: back rest face'),
    ('n_p',         'n_r + bump_relief', 'mm', 'derived: back plate front face'),
    ('n_b',         'n_p + back_t', 'mm', 'derived: back plate rear face'),
    ('bore_r',      'handle_d/2 + handle_fit', 'mm', 'derived: arch bore radius'),
    ('r_sad',       'bore_r + sad_t', 'mm', 'derived: arch outer radius'),
    ('n_h',         'n_b + bore_r + hook_gap', 'mm', 'derived: handle centre behind the screen face'),
    ('ipad_y0',     '-(v_h*sin(tilt) + n_h*cos(tilt))', 'mm', 'derived: iPad bottom front edge Y'),
    ('ipad_z0',     '-(v_h*cos(tilt) - n_h*sin(tilt))', 'mm', 'derived: iPad bottom front edge Z'),
    ('z_gus',       '-(2*bore_r + 2 mm)', 'mm', 'derived: gusset top (leaves room to slide the arch over the handle)'),
    ('v_a0',        '(n_p*sin(tilt) - ipad_z0)/cos(tilt)', 'mm', 'derived: back plate height at the arch bottom (handle centre level)'),
    ('v_c1',        '(n_p*sin(tilt) + r_sad - ipad_z0)/cos(tilt)', 'mm', 'derived: back plate height at the arch top'),
    ('v_g',         '(n_p*sin(tilt) + z_gus - ipad_z0)/cos(tilt)', 'mm', 'derived: back plate height at the gusset top'),
    ('rim_dy',      'sqrt((rim_c/(1 mm))^2 - (rim_drop/(1 mm))^2) * (1 mm)', 'mm', 'derived: wire centre forward of handle centre'),
    ('r_wb',        'rim_d/2 + rim_fit', 'mm', 'derived: wire notch radius'),
    ('r_pad',       'r_wb + pad_wall', 'mm', 'derived: wire pad half size'),
    ('arm_jy',      'ipad_y0 + v_b*sin(tilt) + n_b*cos(tilt)', 'mm', 'derived: arm start Y (bracket bottom back corner)'),
    ('arm_jz',      'ipad_z0 + v_b*cos(tilt) - n_b*sin(tilt)', 'mm', 'derived: arm start Z'),
    ('arm_dy',      'rim_dy - arm_jy', 'mm', 'derived: arm run to the wire pad centre, Y'),
    ('arm_dz',      '-(rim_drop) + r_pad/2 - arm_jz', 'mm', 'derived: arm run, Z'),
    ('arm_len',     'sqrt((arm_dy/(1 mm))^2 + (arm_dz/(1 mm))^2) * (1 mm)', 'mm', 'derived: arm length'),
    ('tie_x',       '(arm_t + arm_w)/2', 'mm', 'derived: tie tunnel centre, in from the outer face (clear of the arm)'),
    ('sk_v0',       'sp_v - sfit - sk_wall', 'mm', 'derived: socket bottom'),
    ('sk_v1',       'sp_v + sp_h + sfit + sk_wall', 'mm', 'derived: socket top'),
    ('sk_n1',       'n_b + sp_t + 2*sfit + sk_wall', 'mm', 'derived: socket rear'),

    # Finishing (CAD rule 3): corners get the biggest class that suits them
    # (r ~ 0.2 x the narrower face), concave one class smaller.
    ('fil_big',     '2 mm',     'mm', 'Fillet class: big corners'),
    ('fil_med',     '1 mm',     'mm', 'Fillet class: medium corners'),
    ('fil_small',   '0.4 mm',   'mm', 'Fillet class: small features'),
    ('bed_ch',      '0.4 mm',   'mm', 'Chamfer on every bed edge (elephant foot)'),

    # Fit-test prints
    ('test_t',      '4 mm',     'mm', 'TEST_Profile slice thickness'),
    ('test_h',      'rest_lo + 12 mm', 'mm', 'TEST_Corner height (includes some back rest)'),
    ('test_gap',    '40 mm',    'mm', 'Test pieces sit this far apart, outboard of Bracket_L'),
]
FILLET_CLASSES = ('fil_big', 'fil_med', 'fil_small')
PRINTERS = (('Bambu P1S', 256), ('Flashforge AD5M', 220))

# ================================================================= HELPERS
app = ui = design = root = um = None
H = V = None
NEW = JOIN = CUT = None
AX = {'x': 0, 'y': 1, 'z': 2}
STEP = 'startup'          # current build step, reported if something fails
SKIPPED = []              # dimensions Fusion had already constrained


def VI(expr):
    return adsk.core.ValueInput.createByString(expr)


def E(expr):
    """Evaluate an expression (may use user params) -> internal units (cm)."""
    return um.evaluateExpression(expr, 'mm')


def add_params():
    ups = design.userParameters
    for name, expr, units, comment in PARAMS:
        p = ups.itemByName(name)
        if p:
            p.expression = expr
        else:
            ups.add(name, VI(expr), units, comment)


def model_pt(axes, a, b):
    c = [0.0, 0.0, 0.0]
    c[AX[axes[0]]] = a
    c[AX[axes[1]]] = b
    return adsk.core.Point3D.create(c[0], c[1], c[2])


def nearest(lines, target):
    best, bd = None, 1e9
    for i in range(lines.count):
        ln = lines.item(i)
        for sp in (ln.startSketchPoint, ln.endSketchPoint):
            d = sp.geometry.distanceTo(target)
            if d < bd:
                best, bd = sp, d
    return best


def new_component(name, ground=False):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    occ.component.name = name
    if ground:
        occ.isGrounded = True
    return occ.component


class Sk:
    """Sketch in component `comp` on its XY or YZ origin plane, drawn in MODEL
    coordinates. Every position and size becomes a sketch dimension driven by
    a parameter expression, so the model stays editable."""

    def __init__(self, comp, axes, name):
        plane = {'xy': comp.xYConstructionPlane, 'yz': comp.yZConstructionPlane}[axes]
        self.s = comp.sketches.add(plane)
        self.s.name = name
        self.axes = axes
        # Work out which sketch axis each model axis lands on (plane-dependent).
        o = self.s.modelToSketchSpace(model_pt(axes, 0, 0))
        p = self.s.modelToSketchSpace(model_pt(axes, 1, 0))
        self.orient = (H, V) if abs(p.x - o.x) > abs(p.y - o.y) else (V, H)

    def _sp(self, a, b):
        return self.s.modelToSketchSpace(model_pt(self.axes, a, b))

    def _dim(self, p1, p2, axis_i, expr):
        val = E(expr)
        if abs(val) < 1e-6:
            return  # zero distance: leave geometry where it was drawn
        if val < 0:
            expr = '-(' + expr + ')'
        g1, g2 = p1.geometry, p2.geometry
        txt = adsk.core.Point3D.create((g1.x + g2.x) / 2 + 0.3,
                                       (g1.y + g2.y) / 2 + 0.3, 0)
        try:
            d = self.s.sketchDimensions.addDistanceDimension(
                p1, p2, self.orient[axis_i], txt)
        except RuntimeError as ex:
            # Fusion auto-aligns points that share an X or Y with existing
            # geometry; that direction is then already tied, so the extra
            # dimension is redundant (and would over-constrain).
            if 'OVER_CONSTRAIN' in str(ex).upper():
                SKIPPED.append('%s: %s' % (self.s.name, expr))
                return
            raise
        d.parameter.expression = expr

    def locate(self, pt, a_expr, b_expr):
        self._dim(self.s.originPoint, pt, 0, a_expr)
        self._dim(self.s.originPoint, pt, 1, b_expr)

    def rect(self, a0, b0, wa, wb):
        A0, B0 = E(a0), E(b0)
        p1 = self._sp(A0, B0)
        p2 = self._sp(A0 + E(wa), B0 + E(wb))
        lines = self.s.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)
        c1, c2 = nearest(lines, p1), nearest(lines, p2)
        if abs(A0) < 1e-6 and abs(B0) < 1e-6:
            self.s.geometricConstraints.addCoincident(c1, self.s.originPoint)
        else:
            self.locate(c1, a0, b0)
        self._dim(c1, c2, 0, wa)
        self._dim(c1, c2, 1, wb)

    def poly(self, pts):
        """Closed polygon through [(a_expr, b_expr), ...]. Each corner is
        dimensioned from the origin, so tilted shapes stay parametric."""
        lines = self.s.sketchCurves.sketchLines
        P = [self._sp(E(a), E(b)) for a, b in pts]
        first = lines.addByTwoPoints(P[0], P[1])
        corners = [first.startSketchPoint, first.endSketchPoint]
        prev = first
        for p in P[2:]:
            prev = lines.addByTwoPoints(prev.endSketchPoint, p)
            corners.append(prev.endSketchPoint)
        lines.addByTwoPoints(prev.endSketchPoint, first.startSketchPoint)
        for sp, (a, b) in zip(corners, pts):
            self.locate(sp, a, b)

    def circle(self, ca, cb, d_expr):
        dv = E(d_expr)
        c = self.s.sketchCurves.sketchCircles.addByCenterRadius(
            self._sp(E(ca), E(cb)), dv / 2)
        g = c.centerSketchPoint.geometry
        try:
            dd = self.s.sketchDimensions.addDiameterDimension(
                c, adsk.core.Point3D.create(g.x + dv, g.y + dv, 0))
            dd.parameter.expression = d_expr
        except RuntimeError as ex:
            if 'OVER_CONSTRAIN' not in str(ex).upper():
                raise
            SKIPPED.append('%s: dia %s' % (self.s.name, d_expr))
        if abs(E(ca)) < 1e-6 and abs(E(cb)) < 1e-6:
            self.s.geometricConstraints.addCoincident(c.centerSketchPoint, self.s.originPoint)
        else:
            self.locate(c.centerSketchPoint, ca, cb)

    def profiles(self, loops=None):
        oc = adsk.core.ObjectCollection.create()
        for i in range(self.s.profiles.count):
            pr = self.s.profiles.item(i)
            if loops is None or pr.profileLoops.count == loops:
                oc.add(pr)
        return oc


def extrude(comp, profs, op, dist, start=None, body=None, name=None):
    """Extrude along the sketch normal (+Z for XY, +X for YZ).
    `start` = offset of the start plane, `dist` = length; both expressions.
    `body` = the body to join/cut (keeps cuts from touching other parts)."""
    global STEP
    if name:
        STEP = name
    ef = comp.features.extrudeFeatures
    inp = ef.createInput(profs, op)
    if start is not None:
        inp.startExtent = adsk.fusion.OffsetStartDefinition.create(VI(start))
    inp.setDistanceExtent(False, VI(dist))
    if body is not None:
        inp.participantBodies = [body]
    f = ef.add(inp)
    if name:
        f.name = name
    return f


def step(name):
    global STEP
    STEP = name


# ---- Frames for the tilted geometry (all results are expressions)
def P(v, n):
    """Screen frame -> model (Y, Z). v = up the screen from the iPad bottom
    edge, n = back from the screen face (positive = toward the cart)."""
    return ('(ipad_y0) + (%s)*sin(tilt) + (%s)*cos(tilt)' % (v, n),
            '(ipad_z0) + (%s)*cos(tilt) - (%s)*sin(tilt)' % (v, n))


def tq(v0, v1, n0, n1):
    """Screen-frame rectangle v0..v1 x n0..n1, as a polygon shape."""
    return ('poly', [P(v0, n0), P(v1, n0), P(v1, n1), P(v0, n1)])


def AP(s, w):
    """Arm frame -> model (Y, Z). s = 0..1 from the bracket's bottom back
    corner to the wire pad centre, w = sideways offset (mm expression)."""
    return ('arm_jy + (%s)*arm_dy - (%s)*arm_dz/arm_len' % (s, w),
            'arm_jz + (%s)*arm_dz + (%s)*arm_dy/arm_len' % (s, w))


class Part:
    """One printable component built from YZ profiles extruded along X.
    side -1 = left (outer face at -bx_o, features grow toward +X), +1 = right.
    X positions are given inward from the outer face, so one recipe builds
    both mirror images. `shift` moves the outer face further out (test
    pieces)."""

    def __init__(self, name, side=-1, shift='0 mm', ground=False):
        self.c = new_component(name, ground)
        self.name, self.side, self.shift = name, side, shift
        self.started = False
        self.pts = []     # evaluated YZ corners (mm), for the print-bed check

    def B(self):
        return self.c.bRepBodies.itemByName(self.name)

    def xspan(self, a, t, side=None):
        side = self.side if side is None else side
        if side < 0:
            return '-(bx_o) - (%s) + (%s)' % (self.shift, a), t
        return '(bx_o) + (%s) - (%s) - (%s)' % (self.shift, a, t), t

    def add(self, label, shape, a='0 mm', t='wall_t', x=None, side=None, op=None):
        step('%s: %s' % (self.name, label))
        s = Sk(self.c, 'yz', label)
        kind = shape[0]
        if kind == 'poly':
            s.poly(shape[1])
            corners = shape[1]
        elif kind == 'rect':
            a0, b0, wa, wb = shape[1:]
            s.rect(a0, b0, wa, wb)
            corners = [(a0, b0), ('(%s) + (%s)' % (a0, wa), '(%s) + (%s)' % (b0, wb))]
        else:
            s.circle(*shape[1:])
            corners = []
        start, dist = x if x else self.xspan(a, t, side)
        if op == CUT:
            extrude(self.c, s.profiles(), CUT, dist, start=start, body=self.B(), name=label)
            return
        self.pts += [(E(ya) * 10, E(za) * 10) for ya, za in corners]
        if not self.started:
            f = extrude(self.c, s.profiles(), NEW, dist, start=start, name=label)
            f.bodies.item(0).name = self.name
            self.started = True
        else:
            extrude(self.c, s.profiles(), JOIN, dist, start=start, body=self.B(), name=label)

    def cut(self, label, shape, a, t, x=None, side=None):
        self.add(label, shape, a, t, x, side, op=CUT)


# ---- Finishing (CAD rule 3)
def inside(body, p, d, dist=0.005):
    q = adsk.core.Point3D.create(p.x + d.x * dist, p.y + d.y * dist, p.z + d.z * dist)
    return body.pointContainment(q) == adsk.fusion.PointContainment.PointInsidePointContainment


def face_normal(body, face, pt):
    """Normal at pt, flipped if needed so it points out of the material
    (the side is tested at the face's own interior point, not on an edge)."""
    pof = face.pointOnFace
    ok0, n0 = face.evaluator.getNormalAtPoint(pof)
    ok, n = face.evaluator.getNormalAtPoint(pt)
    if not (ok0 and ok):
        return None
    if inside(body, pof, n0):
        n.scaleBy(-1)
    return n


def is_concave(body, mid, n1, n2):
    """Step off the edge along (n1 - n2): that lands outside a convex corner
    but inside the material of a concave one."""
    d = adsk.core.Vector3D.create(n1.x - n2.x, n1.y - n2.y, n1.z - n2.z)
    if d.length < 1e-6:
        return False
    d.normalize()
    d.scaleBy(0.005)
    p = adsk.core.Point3D.create(mid.x + d.x, mid.y + d.y, mid.z + d.z)
    return body.pointContainment(p) == adsk.fusion.PointContainment.PointInsidePointContainment


def bed_face(body, d):
    """The outermost planar face whose normal points along d (the face that
    goes down on the print bed)."""
    best, best_key = None, None
    for f in body.faces:
        if f.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
            continue
        n = face_normal(body, f, f.pointOnFace)
        if n is None or n.x * d[0] + n.y * d[1] + n.z * d[2] < 0.999:
            continue
        p = f.pointOnFace
        key = (round(p.x * d[0] + p.y * d[1] + p.z * d[2], 4), f.area)
        if best is None or key > best_key:
            best, best_key = f, key
    return best


def classify_edges(body, bed):
    """Sort edges into fillet classes: r ~ 0.2 x the narrower adjacent face,
    concave one class smaller, bed edges and tiny features skipped."""
    radii = [(n, E(n)) for n in FILLET_CLASSES]
    skip = set(e.entityToken for e in bed.edges) if bed else set()
    out = dict((n, []) for n in FILLET_CLASSES)
    for e in body.edges:
        try:
            tok = e.entityToken
            if tok in skip or e.faces.count != 2:
                continue
            f1, f2 = e.faces.item(0), e.faces.item(1)
            mid = e.pointOnEdge
            n1, n2 = face_normal(body, f1, mid), face_normal(body, f2, mid)
            if n1 is None or n2 is None or n1.dotProduct(n2) > 0.995:
                continue  # tangent or nearly flat
            r = 0.2 * min(f1.area, f2.area) / e.length
            idx = next((i for i, (_, rv) in enumerate(radii) if r >= rv), None)
            if idx is None:
                continue
            if is_concave(body, mid, n1, n2):
                idx += 1
            if idx < len(radii):
                out[radii[idx][0]].append(tok)
        except Exception:
            continue
    return out


def in_chunks(tokens, make, stats):
    """Try one feature on all edges; on failure split the set in half and
    retry, so one awkward edge doesn't cost the whole class."""
    def resolve(toks):
        oc = adsk.core.ObjectCollection.create()
        for t in toks:
            for ent in design.findEntityByToken(t):
                e = adsk.fusion.BRepEdge.cast(ent)
                if e and e.isValid:
                    oc.add(e)
                    break
        return oc

    def attempt(toks):
        oc = resolve(toks)
        if oc.count == 0:
            return 0
        try:
            feat = make(oc)
            if feat.healthState == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
                feat.deleteMe()
                raise RuntimeError('feature failed')
            return oc.count
        except Exception:
            if len(toks) == 1:
                stats['skipped'] += 1
                return 0
            h = len(toks) // 2
            return attempt(toks[:h]) + attempt(toks[h:])
    return attempt(list(tokens))


def add_fillet(ff, edges, pname):
    fi = ff.createInput()
    try:
        fi.edgeSetInputs.addConstantRadiusEdgeSet(edges, VI(pname), False)
    except AttributeError:
        fi.addConstantRadiusEdgeSet(edges, VI(pname), False)
    f = ff.add(fi)
    f.name = 'Auto fillet (%s)' % pname
    return f


def add_chamfer(cf, edges):
    try:
        ci = cf.createInput2()
        ci.chamferEdgeSets.addEqualDistanceChamferEdgeSet(edges, VI('bed_ch'), True)
    except AttributeError:
        ci = cf.createInput(edges, True)
        ci.setToEqualDistance(VI('bed_ch'))
    f = cf.add(ci)
    f.name = 'Bed chamfer'
    return f


def finish(part, bed_dir):
    stats = {'filleted': 0, 'skipped': 0, 'chamfered': 0, 'bed': True}
    if not AUTO_FILLET:
        return stats
    step(part.name + ': auto fillet')
    classes = classify_edges(part.B(), bed_face(part.B(), bed_dir))
    ff = part.c.features.filletFeatures
    for pname in FILLET_CLASSES:
        if classes[pname]:
            stats['filleted'] += in_chunks(
                classes[pname], lambda oc, pn=pname: add_fillet(ff, oc, pn), stats)
    step(part.name + ': bed chamfer')
    bed = bed_face(part.B(), bed_dir)
    if bed is None:
        stats['bed'] = False
        return stats
    cf = part.c.features.chamferFeatures
    stats['chamfered'] = in_chunks([e.entityToken for e in bed.edges],
                                   lambda oc: add_chamfer(cf, oc), stats)
    return stats


def bed_fit(pts, height):
    """Smallest in-plane rotation that fits each printer, or None."""
    res = []
    for printer, size in PRINTERS:
        ok = None
        if height <= size:
            for deg in range(0, 180):
                a = math.radians(deg)
                xs = [y * math.cos(a) - z * math.sin(a) for y, z in pts]
                ys = [y * math.sin(a) + z * math.cos(a) for y, z in pts]
                if max(xs) - min(xs) <= size and max(ys) - min(ys) <= size:
                    ok = deg
                    break
        res.append((printer, ok))
    return res


# =================================================================== MODEL
def add_channel(p, top, rest_top, wall=True, top_lip=True, thick=None):
    """Ledge, front lips, back plate and back rest (+ side wall)."""
    T = lambda t: thick or t
    if wall:
        p.add('Side wall', tq('v_b', top, 'n_f', 'n_b'), '0 mm', 'wall_t')
    # Each piece overlaps the one it joins (not just touching faces), so the
    # joins are solid whatever the rounding.
    p.add('Ledge', tq('v_b', '-(clr)', 'n_f', 'n_b'), '0 mm', T('wall_t + grip'))
    p.add('Bottom lip', tq('v_b', 'lip_h', 'n_f', '-(clr)'), '0 mm', T('wall_t + grip'))
    if wall:
        p.add('Side lip (low)', tq('v_b', 'win_lo', 'n_f', '-(clr)'), '0 mm', 'wall_t + lip_w')
        if top_lip:
            p.add('Side lip (top)', tq('ipad_h - win_hi', top, 'n_f', '-(clr)'),
                  '0 mm', 'wall_t + lip_w')
    p.add('Back plate', tq('v_b', top, 'n_p', 'n_b'), '0 mm', T('wall_t + grip'))
    p.add('Back rest', tq('rest_lo', rest_top, 'n_r', 'n_p + back_t/2'), '0 mm', T('wall_t + grip'))


def add_hanger(p, thick=None):
    """Arch over the handle and a pad on top of the wire, both open
    downward, joined by an arm from the bracket's bottom back corner and a
    gusset."""
    T = lambda t: thick or t
    p.add('Arch', ('poly', [('r_sad', '0 mm'), ('r_sad', 'r_sad'),
                            P('v_c1', 'n_p'), P('v_a0', 'n_p')]), '0 mm', T('arm_w'))
    p.add('Arm', ('poly', [AP('0', 'arm_h/2'), AP('1', 'arm_h/2'),
                           AP('1', '-(arm_h/2)'), AP('0', '-(arm_h/2)')]), '0 mm', T('arm_t'))
    # Gusset: fills the triangle between the back plate, the arch and the
    # arm, so the arm is anchored along its root, not at one corner. Its top
    # stays a tube's width below the arch (room to slide it over the handle)
    # and it sits outboard of the tie path (tie_x).
    p.add('Gusset', ('poly', [P('v_b', 'n_p'), P('v_g', 'n_p'), ('bore_r', 'z_gus'),
                              AP('0.3', 'arm_h/2'), AP('0', 'arm_h/2'),
                              AP('0', '-(arm_h/2)')]), '0 mm', T('arm_t'))
    p.add('Wire pad', ('rect', 'rim_dy - r_pad', '-(rim_drop)', '2*r_pad', 'r_pad'),
          '0 mm', T('arm_w'))


def hanger_cuts(p, ties=True):
    p.cut('Handle bore', ('circle', '0 mm', '0 mm', 'handle_d + 2*handle_fit'),
          '-1 mm', 'arm_w + 2 mm')
    p.cut('Wire notch', ('circle', 'rim_dy', '-(rim_drop)', 'rim_d + 2*rim_fit'),
          '-1 mm', 'arm_w + 2 mm')
    # Straight-walled entry below the notch, so nothing blocks the wire;
    # starts inside the notch so the cut always has material to remove.
    p.cut('Wire mouth', ('rect', 'rim_dy - r_wb', '-(rim_drop) - r_pad - 10 mm',
                         '2*r_wb', 'r_pad + 10 mm + r_wb/2'),
          '-1 mm', 'arm_w + 2 mm')
    if not ties:
        return
    # Handle tie: up the gap behind the back plate, over the arch, down its
    # cart side and back under the tube.
    p.cut('Handle tie tunnel',
          tq('v_g', 'v_c1 + 8 mm',
             'n_b + (hook_gap - zt_h)/2', 'n_b + (hook_gap + zt_h)/2'),
          'tie_x - zt_w/2', 'zt_w')
    # Wire tie: through the pad just above the notch, round under the wire.
    p.cut('Wire tie tunnel',
          ('rect', 'rim_dy - r_pad - 1 mm', '-(rim_drop) + r_wb + tun_floor',
           '2*r_pad + 2 mm', 'zt_h'),
          'tie_x - zt_w/2', 'zt_w')


def socket_tie_slot():
    return tq('sk_v0 - 1 mm', 'sk_v1 + 1 mm',
              'n_b + sfit + sp_t/2 - zt_w/2', 'n_b + sfit + sp_t/2 + zt_w/2')


def build_bracket(name, side):
    p = Part(name, side, ground=(side < 0))
    add_channel(p, 'v_t', 'rest_hi')
    add_hanger(p)
    p.add('Socket', tq('sk_v0', 'sk_v1', 'n_p', 'sk_n1'), '0 mm', 'wall_t + sk_l')
    p.cut('Side window', tq('win_lo', 'ipad_h - win_hi', 'n_f - 1 mm', 'n_r'),
          '-1 mm', 'wall_t + 2 mm')
    p.cut('Top button relief', tq('ipad_h - win_hi', 'v_t + 1 mm', '-(clr)', 'n_r'),
          'wall_t - btn_relief', 'btn_relief + 1 mm')
    p.cut('Socket hole', tq('sp_v - sfit', 'sp_v + sp_h + sfit', 'n_b', 'n_b + sp_t + 2*sfit'),
          'wall_t', 'sk_l + 1 mm')
    p.cut('Socket tie slot', socket_tie_slot(), 'wall_t + pin_x - zt_h/2', 'zt_h')
    hanger_cuts(p)
    return p


def build_spacer():
    p = Part('Spacer')
    p.add('Spacer bar', tq('sp_v', 'sp_v + sp_h', 'n_b + sfit', 'n_b + sfit + sp_t'),
          x=('-(ipad_w/2 + clr - sp_end)', 'ipad_w + 2*(clr - sp_end)'))
    for side, label in ((-1, 'left'), (1, 'right')):
        p.cut('Tie slot (%s)' % label, socket_tie_slot(),
              'wall_t + pin_x - zt_h/2', 'zt_h', side=side)
    return p


def build_tests():
    """TEST_Corner: bottom corner of the channel, for the iPad fit.
    TEST_Profile: a thin slice of the hanger + channel, for the handle and
    wire fit and the screen angle."""
    c = Part('TEST_Corner', shift='test_gap')
    add_channel(c, 'test_h', 'test_h', top_lip=False)
    c.cut('Side window', tq('win_lo', 'test_h + 1 mm', 'n_f - 1 mm', 'n_r'),
          '-1 mm', 'wall_t + 2 mm')
    s = Part('TEST_Profile', shift='2*test_gap')
    add_channel(s, 'v_c1', 'v_c1', wall=False, top_lip=False, thick='test_t')
    add_hanger(s, thick='test_t')
    hanger_cuts(s, ties=False)
    return [c, s]


def build_reference():
    """Envelopes for collision checks and screenshots. Not for printing."""
    for name, shape, start, dist in [
            ('REF_Handle', ('circle', '0 mm', '0 mm', 'handle_d'), '-300 mm', '600 mm'),
            ('REF_Wire', ('circle', 'rim_dy', '-(rim_drop)', 'rim_d'), '-250 mm', '500 mm'),
            ('REF_iPad', tq('0 mm', 'ipad_h', '0 mm', 'ipad_d'), '-(ipad_w/2)', 'ipad_w')]:
        step(name)
        c = new_component(name)
        s = Sk(c, 'yz', name)
        if shape[0] == 'circle':
            s.circle(*shape[1:])
        else:
            s.poly(shape[1])
        f = extrude(c, s.profiles(), NEW, dist, start=start, name=name)
        f.bodies.item(0).name = name


def build():
    warnings, report = [], []
    t = um.evaluateExpression('tilt', 'deg')
    left = build_bracket('Bracket_L', -1)
    right = build_bracket('Bracket_R', 1)
    spacer = build_spacer()
    tests = build_tests() if BUILD_TESTS else []
    if SHOW_REFERENCE:
        try:
            build_reference()
        except Exception:
            warnings.append('Reference envelopes failed (real parts are fine):\n'
                            + traceback.format_exc().splitlines()[-1])

    # Rule 3 finishing, then the print-bed check
    beds = [(left, (-1, 0, 0)), (right, (1, 0, 0)),
            (spacer, (0, math.cos(t), -math.sin(t)))] + [(p, (-1, 0, 0)) for p in tests]
    for part, d in beds:
        try:
            st = finish(part, d)
            if AUTO_FILLET:
                line = '%s: %d edges filleted, %d bed edges chamfered' % (
                    part.name, st['filleted'], st['chamfered'])
                if st['skipped']:
                    line += ', %d edges skipped' % st['skipped']
                if not st['bed']:
                    line += ' (bed face not found: chamfer by hand)'
                report.append(line)
        except Exception:
            warnings.append('%s finishing failed (part is fine, add fillets by hand):\n%s'
                            % (part.name, traceback.format_exc().splitlines()[-1]))

    L = E('ipad_w + 2*(clr - sp_end)') * 10
    spacer.pts = [(0, 0), (L, 0), (L, E('sp_h') * 10), (0, E('sp_h') * 10)]
    heights = {'Spacer': E('sp_t') * 10, 'TEST_Profile': E('test_t') * 10}
    tallest = max(E('wall_t + grip'), E('wall_t + sk_l'), E('arm_w')) * 10
    fits = []
    for part in [left, right, spacer] + tests:
        h = heights.get(part.name, tallest)
        res = bed_fit(part.pts, h)
        fits.append('%s: %s' % (part.name, ', '.join(
            '%s %s' % (pr, 'no' if deg is None else ('yes' if deg == 0 else 'yes, rotated %d deg' % deg))
            for pr, deg in res)))

    if STL_DIR:
        step('STL export')
        os.makedirs(STL_DIR, exist_ok=True)
        em = design.exportManager
        for part in [left, right, spacer] + tests:
            path = os.path.join(STL_DIR, 'ipadmount_%s.stl' % part.name.lower())
            opts = em.createSTLExportOptions(part.B(), path)
            opts.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
            em.execute(opts)
    return warnings, report, fits


def run(context):
    global app, ui, design, root, um, H, V, NEW, JOIN, CUT
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        root = design.rootComponent
        um = design.unitsManager
        H = adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation
        V = adsk.fusion.DimensionOrientations.VerticalDimensionOrientation
        NEW = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        JOIN = adsk.fusion.FeatureOperations.JoinFeatureOperation
        CUT = adsk.fusion.FeatureOperations.CutFeatureOperation
        del SKIPPED[:]
        try:  # show mm whatever the user's default units are
            fum = design.fusionUnitsManager
            fum.distanceDisplayUnits = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
        except Exception:
            pass

        step('parameters')
        add_params()
        if E('rim_drop') > E('rim_c'):
            ui.messageBox('rim_drop can be at most rim_c (equal = wire straight below '
                          'the handle). Fix PARAMS and re-run.')
            return
        warnings, report, fits = build()
        off = math.degrees(math.atan2(E('rim_dy'), E('rim_drop')))
        if off > 25:
            warnings.append('The wire is %.0f deg forward of straight below the handle. '
                            'Past ~25 deg the pad can roll off the wire when the screen '
                            'tips toward the shopper (check/check.py shows it): rely on '
                            'the wire zip ties, or ask for a forward-facing notch.' % off)
        app.activeViewport.fit()

        measure = [n for n, _, _, c in PARAMS if c.startswith('MEASURE')]
        msg = ('KART iPad mount built.\n\n'
               'Components: Bracket_L (grounded), Bracket_R, Spacer'
               + (', TEST_Corner, TEST_Profile' if BUILD_TESTS else '') + '.\n'
               'Print the TEST pieces first (README, "Fit test").\n\n'
               'Print beds:\n  ' + '\n  '.join(fits) + '\n\n'
               'Still nominal (MEASURE): ' + ', '.join(measure) + '\n\n'
               'Edit: Modify > Change Parameters.')
        if STL_DIR:
            msg += '\nSTLs: ' + STL_DIR
        if report:
            msg += '\n\nFinishing:\n  ' + '\n  '.join(report)
        if SKIPPED:
            msg += ('\n\n(%d sketch dimensions were already tied by Fusion '
                    'auto-alignment; skipped, no action needed.)' % len(SKIPPED))
        if warnings:
            msg += '\n\nWarnings:\n' + '\n'.join(warnings)
        ui.messageBox(msg)
    except Exception:
        if ui:
            ui.messageBox('iPad mount script failed at step: %s\n\n%s'
                          % (STEP, traceback.format_exc()))
