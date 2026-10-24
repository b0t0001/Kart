"""
SmartCart enclosure: parametric Fusion 360 script
==================================================

What it builds (in a NEW Fusion document, every run):
  * Base: open tray for a Raspberry Pi 4B. Press-fit pegs (no screws, no
    heat-set inserts because there's no soldering iron at the venue), cable notches,
    two T-slot bosses for the cart clips, and zip-tie slots as a fallback.
  * Clip: separate, replaceable cart clip (shown installed in slot 1). A rigid
    J-hook carries the weight and a barbed latch snaps over the wire. Sized
    by FEA (see clip_fea.png / ENCLOSURE.md). Print 4, lying on the -X face.
  * Lid: press-fit lid with a locating lip, a cable slot for the LCD
    (the LCD mounts ON TOP with tape/velcro; there's no room inside above
    the Pi's USB stack), and vent slots, since the Pi 4 throttles when hot.

Two ways to change the model:
  1. Edit PARAMS below and re-run (fastest for big changes).
  2. In Fusion: Modify > Change Parameters. Every size and position in the
     timeline is driven by these named User Parameters, so changing e.g.
     `wire_d` or `wall` recomputes the whole model. You can also edit any
     sketch or feature in the timeline by hand like a normal model.

Layout: X = box length (Pi USB/Ethernet end at +X), Y = width (cart clips on
+Y, USB-C notch on -Y), Z = up. The lid is placed in front of the base (-Y)
so both fit on one Bambu A1 mini plate (180 x 180).

Reusing this for new parts: everything under "HELPERS" is generic. Copy the
file, replace PARAMS and build(), and keep using Sk.rect / Sk.circle /
extrude so new parts stay parametric too.
"""

import adsk.core
import adsk.fusion
import os
import traceback

# Set to a folder path (e.g. '/Users/you/Desktop') to auto-export STLs.
STL_DIR = ''

# ============================================================== PARAMETERS
# (name, expression, units, comment). Later entries may reference earlier ones.
PARAMS = [
    # Raspberry Pi 4B (official mechanical drawing)
    ('pi_l',          '85 mm',  'mm', 'Pi board length (USB/Ethernet end = +X)'),
    ('pi_w',          '56 mm',  'mm', 'Pi board width'),
    ('pi_hole_x0',    '3.5 mm', 'mm', 'Mount hole inset from board -X edge'),
    ('pi_hole_y0',    '3.5 mm', 'mm', 'Mount hole inset from board -Y edge'),
    ('pi_hole_dx',    '58 mm',  'mm', 'Mount hole spacing along X'),
    ('pi_hole_dy',    '49 mm',  'mm', 'Mount hole spacing along Y'),
    ('usbc_x',        '11.2 mm','mm', 'USB-C power centre from board -X edge'),

    # Shell
    ('wall',          '2 mm',   'mm', 'Wall + floor thickness (2 mm keeps print time down)'),
    ('clear',         '2 mm',   'mm', 'Gap board<->wall on -X, -Y, +Y'),
    ('clear_end',     '4 mm',   'mm', 'Gap at +X end (USB/Ethernet jacks overhang the board)'),
    ('inner_h',       '28 mm',  'mm', 'Floor-to-rim interior height (USB stack ~23 mm + lid lip)'),
    ('box_l',         'pi_l + clear + clear_end + 2*wall', 'mm', 'Outer length'),
    ('box_w',         'pi_w + 2*clear + 2*wall',           'mm', 'Outer width'),
    ('box_h',         'inner_h + wall',                    'mm', 'Outer height'),
    ('board_x0',      'wall + clear', 'mm', 'Board -X edge position'),
    ('board_y0',      'wall + clear', 'mm', 'Board -Y edge position'),

    # Pi mounting
    ('standoff_d',    '6 mm',   'mm', 'Standoff diameter'),
    ('standoff_h',    '5 mm',   'mm', 'Standoff height above floor'),
    ('peg_d',         '2.3 mm', 'mm', 'Press-fit peg (Pi holes are 2.7 mm)'),
    ('peg_h',         '3 mm',   'mm', 'Peg height above standoff'),

    # Cable notches (open at the rim, so cables drop in from above)
    ('notch_z',       'wall + standoff_h', 'mm', 'Notch bottom = underside of board'),
    ('usbc_notch_w',  '14 mm',  'mm', 'USB-C power notch width (-Y wall)'),
    ('end_notch_w',   '54 mm',  'mm', 'USB-A/Ethernet notch width (+X wall), for the webcams'),

    # Cart clip: SEPARATE part (print x4, lying on its side). J-hook carries the
    # load; only the barbed latch flexes. Values below come from the FEA sweep
    # (clip_fea.png): about 1.1% peak strain vs 1.5% allowable for printed PLA.
    ('wire_d',        '6 mm',   'mm', 'CART WIRE DIAMETER: measure your cart (fits about wire_d-0.7 .. wire_d+0.5)'),
    ('hook_extra',    '0.5 mm', 'mm', 'Hook clearance over wire_d'),
    ('hook_w',        'wire_d + hook_extra', 'mm', 'Hook inner width'),
    ('barb_d',        '2.4 mm', 'mm', 'Barb diameter; interference = barb_d/2 - hook_extra (FEA: 0.7 mm)'),
    ('seat_play',     '3 mm',   'mm', 'Extra latch length below the wire (longer = lower strain)'),
    ('leg_l',         'wire_d + seat_play + barb_d', 'mm', 'Latch length'),
    ('leg_t',         '2 mm',   'mm', 'Latch thickness (FEA-chosen; do not go below 1.2)'),
    ('arm_t',         '2.4 mm', 'mm', 'Hook top-arm thickness (load-bearing)'),
    ('spine_t',       '2.4 mm', 'mm', 'Clip spine thickness'),
    ('root_r',        '1 mm',   'mm', 'Root fillet radius (the peak-strain spot; keep >= 1)'),
    ('clip_h',        '16 mm',  'mm', 'Clip height = T-tab length'),
    ('clip_w',        '10 mm',  'mm', 'Clip width along the wire (fit between vertical wires)'),
    ('clip_inset',    '12 mm',  'mm', 'Clip distance from each box end'),
    # T-slot (L-shaped so the clip prints flat with no overhang)
    ('sfit',          '0.2 mm', 'mm', 'Slide-fit clearance per side for tab in slot'),
    ('tab_head_w',    '8 mm',   'mm', 'Tab head width (X)'),
    ('tab_neck_w',    '4 mm',   'mm', 'Tab neck width (X)'),
    ('head_d',        '2 mm',   'mm', 'Tab head depth (Y)'),
    ('slot_lip',      '1.6 mm', 'mm', 'Boss lip that retains the tab head'),
    ('boss_side',     '2 mm',   'mm', 'Boss side wall'),
    ('stop_t',        '2 mm',   'mm', 'Slot floor (the clip rests on this)'),
    ('boss_d',        'head_d + 2*sfit + slot_lip', 'mm', 'Boss depth off the back wall'),
    ('clip_y0',       'box_w + boss_d + sfit', 'mm', 'Clip spine back face (Y)'),
    ('clip_x1',       'clip_inset', 'mm', 'Clip/slot 1 X start'),
    ('clip_x2',       'box_l - clip_inset - clip_w', 'mm', 'Clip/slot 2 X start'),

    # Zip-tie fallback slots in the floor
    ('zt_l',          '5 mm',   'mm', 'Slot length (X)'),
    ('zt_w',          '3 mm',   'mm', 'Slot width (Y)'),
    ('zt_sep',        'wire_d + 4 mm', 'mm', 'Gap between the two slots of a pair'),
    ('zt_dx',         '50 mm',  'mm', 'Distance between the two slot pairs'),

    # Lid
    ('lid_t',         '2 mm',   'mm', 'Lid plate thickness'),
    ('lip_h',         '4 mm',   'mm', 'Locating lip depth'),
    ('lip_t',         '1.6 mm', 'mm', 'Lip thickness'),
    ('fit',           '0.25 mm','mm', 'Lip clearance: raise if too tight, lower if loose'),
    ('lid_gap',       '10 mm',  'mm', 'Spacing between base and lid on the plate'),
    ('cable_slot_w',  '20 mm',  'mm', 'LCD cable slot length'),
    ('cable_slot_h',  '6 mm',   'mm', 'LCD cable slot width'),
    ('cable_dx',      '0 mm',   'mm', 'LCD cable slot offset from lid centre (X)'),
    ('vent_n',        '6',      '',   'Vent slots per row'),
    ('vent_w',        '3 mm',   'mm', 'Vent slot width'),
    ('vent_l',        '6 mm',   'mm', 'Vent slot length'),
    ('vent_pitch',    '9 mm',   'mm', 'Vent slot spacing'),
    ('vent_off',      '22 mm',  'mm', 'Vent row distance from lid centreline (clear of LCD)'),

    # ---- REFERENCE GEOMETRY (see PARTS.md). Used for keep-out envelopes and
    # future mounts. Conservative envelopes, NOT exact models.
    ('pi_pcb_t',      '1.5 mm', 'mm', 'Pi PCB thickness'),
    ('pi_port_h',     '16 mm',  'mm', 'USB/Ethernet stack height above PCB (tallest part)'),
    ('pi_port_d',     '21 mm',  'mm', 'USB/Ethernet block depth from +X board edge'),
    ('pi_port_over',  '2.5 mm', 'mm', 'USB/Ethernet overhang past +X board edge'),
    ('pi_gpio_h',     '8.5 mm', 'mm', 'GPIO header height above PCB'),
    ('lcd_l',         '80 mm',  'mm', 'Grove LCD RGB v4.0 length (vendor; MEASURE)'),
    ('lcd_w',         '40 mm',  'mm', 'Grove LCD width (vendor 40, old datasheet 36; MEASURE)'),
    ('lcd_h',         '13.5 mm','mm', 'Grove LCD total thickness incl. Grove socket (MEASURE)'),
    ('cam_w',         '72.9 mm','mm', 'Logitech Brio 100 width (vendor spec)'),
    ('cam_h',         '31.9 mm','mm', 'Brio 100 height (vendor spec)'),
    ('cam_d',         '66.6 mm','mm', 'Brio 100 depth incl. folded clip (vendor spec)'),
]
SHOW_REFERENCE = True   # build grey REF_ envelope components (don't print them)

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


# =================================================================== MODEL
def build_base():
    c = new_component('Base', ground=True)
    step('Base outline')
    s = Sk(c, 'xy', 'Base outline')
    s.rect('0 mm', '0 mm', 'box_l', 'box_w')
    f = extrude(c, s.profiles(), NEW, 'box_h', name='Base block')
    b = f.bodies.item(0)
    b.name = 'Base'
    step('Shell')
    top = adsk.core.ObjectCollection.create()
    top.add(f.endFaces.item(0))
    shells = c.features.shellFeatures
    si = shells.createInput(top, False)
    si.insideThickness = VI('wall')
    shells.add(si).name = 'Shell'
    B = lambda: c.bRepBodies.itemByName('Base')

    # Pi standoffs + pegs
    hx = ['board_x0 + pi_hole_x0', 'board_x0 + pi_hole_x0 + pi_hole_dx']
    hy = ['board_y0 + pi_hole_y0', 'board_y0 + pi_hole_y0 + pi_hole_dy']
    for label, dia, height in [('Standoffs', 'standoff_d', 'wall + standoff_h'),
                               ('Pegs', 'peg_d', 'wall + standoff_h + peg_h')]:
        step(label + ' sketch')
        s = Sk(c, 'xy', 'Pi ' + label.lower())
        for x in hx:
            for y in hy:
                s.circle(x, y, dia)
        extrude(c, s.profiles(), JOIN, height, body=B(), name=label)

    # Cable notches (open at the rim)
    step('Notch sketches')
    s = Sk(c, 'xy', 'End notch (USB-A / Ethernet)')
    s.rect('box_l - wall - 1 mm', 'box_w/2 - end_notch_w/2', 'wall + 2 mm', 'end_notch_w')
    extrude(c, s.profiles(), CUT, 'box_h', start='notch_z', body=B(), name='End notch')
    s = Sk(c, 'xy', 'USB-C notch')
    s.rect('board_x0 + usbc_x - usbc_notch_w/2', '-1 mm', 'usbc_notch_w', 'wall + 2 mm')
    extrude(c, s.profiles(), CUT, 'box_h', start='notch_z', body=B(), name='USB-C notch')

    # T-slot bosses on the +Y wall (clips slide down in, gravity locks them)
    slot_z = 'box_h - clip_h'
    for i, cx in enumerate(['clip_x1', 'clip_x2']):
        n = i + 1
        step('Boss %d sketch' % n)
        s = Sk(c, 'xy', 'Boss %d' % n)
        s.rect('%s - sfit - boss_side' % cx, 'box_w - 0.5 mm',
               'tab_head_w + 2*sfit + 2*boss_side', 'boss_d + 0.5 mm')
        extrude(c, s.profiles(), JOIN, 'clip_h + stop_t', start='%s - stop_t' % slot_z,
                body=B(), name='Boss %d' % n)
        s = Sk(c, 'xy', 'Slot %d head' % n)
        s.rect('%s - sfit' % cx, 'box_w', 'tab_head_w + 2*sfit', 'head_d + 2*sfit')
        extrude(c, s.profiles(), CUT, 'clip_h + 1 mm', start=slot_z, body=B(),
                name='Slot %d head' % n)
        s = Sk(c, 'xy', 'Slot %d neck' % n)
        s.rect('%s - sfit' % cx, 'box_w + head_d + 2*sfit - 0.5 mm',
               'tab_neck_w + 2*sfit', 'slot_lip + 1.5 mm')
        extrude(c, s.profiles(), CUT, 'clip_h + 1 mm', start=slot_z, body=B(),
                name='Slot %d neck' % n)

    # Zip-tie fallback slots (pairs straddle a wire running along X)
    step('Zip-tie slot sketch')
    s = Sk(c, 'xy', 'Zip-tie slots')
    for xc in ['box_l/2 - zt_dx/2', 'box_l/2 + zt_dx/2']:
        for y0 in ['box_w/2 - zt_sep/2 - zt_w', 'box_w/2 + zt_sep/2']:
            s.rect('(%s) - zt_l/2' % xc, y0, 'zt_l', 'zt_w')
    extrude(c, s.profiles(), CUT, 'wall + 1 mm', body=B(), name='Zip-tie slots')
    return c


def build_clip():
    """Cart clip, modelled installed in slot 1. J-hook + barbed latch."""
    c = new_component('Clip')
    slot_z = 'box_h - clip_h'
    step('Clip spine sketch')
    s = Sk(c, 'yz', 'Clip spine')
    s.rect('clip_y0', slot_z, 'spine_t', 'clip_h')
    f = extrude(c, s.profiles(), NEW, 'clip_w', start='clip_x1', name='Clip spine')
    f.bodies.item(0).name = 'Clip'
    C = lambda: c.bRepBodies.itemByName('Clip')
    step('Clip hook arm sketch')
    s = Sk(c, 'yz', 'Clip hook arm')
    s.rect('clip_y0', 'box_h - arm_t', 'spine_t + hook_w + leg_t', 'arm_t')
    extrude(c, s.profiles(), JOIN, 'clip_w', start='clip_x1', body=C(), name='Clip hook arm')
    step('Clip latch sketch')
    s = Sk(c, 'yz', 'Clip latch')
    s.rect('clip_y0 + spine_t + hook_w', 'box_h - arm_t - leg_l', 'leg_t', 'leg_l')
    extrude(c, s.profiles(), JOIN, 'clip_w', start='clip_x1', body=C(), name='Clip latch')
    step('Clip barb sketch')
    s = Sk(c, 'yz', 'Clip barb')
    s.circle('clip_y0 + spine_t + hook_w', 'box_h - arm_t - leg_l + barb_d/2', 'barb_d')
    extrude(c, s.profiles(), JOIN, 'clip_w', start='clip_x1', body=C(), name='Clip barb')
    # T-tab (XY profile, along Z). Flush with the clip's -X face, so it prints flat.
    step('Clip tab sketches')
    s = Sk(c, 'xy', 'Clip tab head')
    s.rect('clip_x1', 'box_w + sfit', 'tab_head_w', 'head_d')
    extrude(c, s.profiles(), JOIN, 'clip_h', start=slot_z, body=C(), name='Clip tab head')
    s = Sk(c, 'xy', 'Clip tab neck')
    s.rect('clip_x1', 'box_w + sfit + head_d - 0.5 mm', 'tab_neck_w',
           'clip_y0 - box_w - sfit - head_d + 1 mm')
    extrude(c, s.profiles(), JOIN, 'clip_h', start=slot_z, body=C(), name='Clip tab neck')

    # Root fillets: the FEA peak-strain location. Find the two inner X-direction edges.
    step('Clip root fillets')
    warn = None
    try:
        targets = [(E('clip_y0 + spine_t + hook_w'), E('box_h - arm_t')),
                   (E('clip_y0 + spine_t'), E('box_h - arm_t'))]
        edges = adsk.core.ObjectCollection.create()
        for e in C().edges:
            a, b = e.startVertex.geometry, e.endVertex.geometry
            if abs(a.y - b.y) > 1e-5 or abs(a.z - b.z) > 1e-5:
                continue  # not parallel to X
            for ty, tz in targets:
                if abs(a.y - ty) < 1e-4 and abs(a.z - tz) < 1e-4:
                    edges.add(e)
        if edges.count != 2:
            raise RuntimeError('found %d root edges, expected 2' % edges.count)
        ff = c.features.filletFeatures
        fi = ff.createInput()
        try:
            fi.edgeSetInputs.addConstantRadiusEdgeSet(edges, VI('root_r'), True)
        except AttributeError:
            fi.addConstantRadiusEdgeSet(edges, VI('root_r'), True)
        ff.add(fi).name = 'Clip root fillets'
    except Exception:
        warn = ('Clip root fillet failed. ADD IT BY HAND (Modify > Fillet, radius '
                'root_r, on the 2 inside corners under the hook arm):\n'
                + traceback.format_exc().splitlines()[-1])
    return c, warn


def build_lid():
    """Lid, placed in front of the base (-Y), printed plate-down, lip up."""
    c = new_component('Lid')
    ly = '-(box_w + lid_gap)'
    step('Lid plate sketch')
    s = Sk(c, 'xy', 'Lid plate')
    s.rect('0 mm', ly, 'box_l', 'box_w')
    f = extrude(c, s.profiles(), NEW, 'lid_t', name='Lid plate')
    f.bodies.item(0).name = 'Lid'
    L = lambda: c.bRepBodies.itemByName('Lid')

    step('Lid lip sketch')
    s = Sk(c, 'xy', 'Lid lip')
    s.rect('wall + fit', '(%s) + wall + fit' % ly,
           'box_l - 2*(wall + fit)', 'box_w - 2*(wall + fit)')
    s.rect('wall + fit + lip_t', '(%s) + wall + fit + lip_t' % ly,
           'box_l - 2*(wall + fit + lip_t)', 'box_w - 2*(wall + fit + lip_t)')
    extrude(c, s.profiles(loops=2), JOIN, 'lid_t + lip_h', body=L(), name='Lid lip')

    step('LCD cable slot sketch')
    s = Sk(c, 'xy', 'LCD cable slot')
    s.rect('box_l/2 + cable_dx - cable_slot_w/2', '(%s) + box_w/2 - cable_slot_h/2' % ly,
           'cable_slot_w', 'cable_slot_h')
    extrude(c, s.profiles(), CUT, 'lid_t + 1 mm', body=L(), name='LCD cable slot')

    warn = None
    try:
        step('Lid vents')
        s = Sk(c, 'xy', 'Vent slot')
        s.rect('box_l/2 - ((vent_n - 1)*vent_pitch + vent_w)/2',
               '(%s) + box_w/2 - vent_off - vent_l/2' % ly, 'vent_w', 'vent_l')
        vcut = extrude(c, s.profiles(), CUT, 'lid_t + 1 mm', body=L(), name='Vent slot')
        ents = adsk.core.ObjectCollection.create()
        ents.add(vcut)
        rp = c.features.rectangularPatternFeatures
        pin = rp.createInput(ents, c.xConstructionAxis, VI('vent_n'), VI('vent_pitch'),
                             adsk.fusion.PatternDistanceType.SpacingPatternDistanceType)
        pin.setDirectionTwo(c.yConstructionAxis, VI('2'), VI('2*vent_off'))
        rp.add(pin).name = 'Lid vents'
    except Exception:
        warn = ('Vent pattern failed (cosmetic, lid is otherwise fine):\n'
                + traceback.format_exc().splitlines()[-1])
    return c, warn


def build_reference():
    """Keep-out envelopes for the Pi 4B, sitting on the standoffs.
    Not for printing: they're for collision checks and joint targets."""
    c = new_component('REF_Pi4B_envelope')
    pcb_z = 'wall + standoff_h'
    top = '%s + pi_pcb_t' % pcb_z
    step('REF Pi PCB')
    s = Sk(c, 'xy', 'REF PCB')
    s.rect('board_x0', 'board_y0', 'pi_l', 'pi_w')
    f = extrude(c, s.profiles(), NEW, 'pi_pcb_t', start=pcb_z, name='REF PCB')
    f.bodies.item(0).name = 'REF_PCB'
    step('REF Pi port block')
    s = Sk(c, 'xy', 'REF USB+Ethernet')
    s.rect('board_x0 + pi_l - pi_port_d', 'board_y0 + 2 mm',
           'pi_port_d + pi_port_over', 'pi_w - 4 mm')
    f = extrude(c, s.profiles(), NEW, 'pi_port_h', start=top, name='REF USB+Ethernet')
    f.bodies.item(0).name = 'REF_ports'
    step('REF Pi GPIO')
    s = Sk(c, 'xy', 'REF GPIO header')
    s.rect('board_x0 + 7 mm', 'board_y0 + pi_w - 6.5 mm', '51 mm', '5 mm')
    f = extrude(c, s.profiles(), NEW, 'pi_gpio_h', start=top, name='REF GPIO header')
    f.bodies.item(0).name = 'REF_GPIO'


def build():
    warnings = []
    base = build_base()
    clip, w = build_clip()
    if w:
        warnings.append(w)
    lid, w = build_lid()
    if w:
        warnings.append(w)
    if SHOW_REFERENCE:
        try:
            build_reference()
        except Exception:
            warnings.append('Reference envelopes failed (real parts are fine):\n'
                            + traceback.format_exc().splitlines()[-1])

    if STL_DIR:
        step('STL export')
        em = design.exportManager
        for comp in (base, lid, clip):
            path = os.path.join(STL_DIR, 'smartcart_%s.stl' % comp.name.lower())
            em.execute(em.createSTLExportOptions(comp.bRepBodies.item(0), path))
    return warnings


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

        step('parameters')
        add_params()
        warnings = build()
        app.activeViewport.fit()

        msg = ('SmartCart enclosure built.\n\n'
               'Box: %.1f x %.1f x %.1f mm\n'
               'Components: Base (grounded), Clip, Lid.\n'
               'Print Clip x4, lying on its -X face.\n\n'
               'Edit: Modify > Change Parameters.\n'
               'Measure your cart wire and set wire_d before printing!'
               % (E('box_l') * 10, E('box_w') * 10, E('box_h') * 10))
        if SKIPPED:
            msg += ('\n\n(%d sketch dimensions were already tied by Fusion '
                    'auto-alignment; skipped, no action needed.)' % len(SKIPPED))
        if warnings:
            msg += '\n\nWarnings:\n' + '\n'.join(warnings)
        ui.messageBox(msg)
    except Exception:
        if ui:
            ui.messageBox('SmartCart script failed at step: %s\n\n%s'
                          % (STEP, traceback.format_exc()))
