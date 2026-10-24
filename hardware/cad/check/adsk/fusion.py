"""Minimal mock of adsk.fusion for dry-running the CAD scripts without Fusion.

It evaluates every expression against the user parameters, checks each
sketch dimension against the geometry it was drawn at, and records every
extrusion (YZ/XY profile + extent) so check.py can rebuild real solids.
Bodies get a tiny fake B-rep so the auto-fillet / chamfer code paths run.
"""
import math
import re
from . import core

LOG = {'dim_errors': [], 'eval_errors': [], 'prisms': [], 'dims': 0, 'sketches': 0,
       'stl': [], 'params': {}, 'finishing': []}

_FUNCS = {'sin': 'math.sin', 'cos': 'math.cos', 'tan': 'math.tan', 'sqrt': 'math.sqrt',
          'abs': 'abs', 'max': 'max', 'min': 'min'}
_UNITS = {'mm': '*0.1', 'cm': '*1.0', 'deg': '*(math.pi/180)', 'rad': '*1.0'}


def evaluate(expr, params):
    """Fusion-style expression -> internal units (cm, rad)."""
    def sub(m):
        w = m.group(0)
        if w in _UNITS:
            return _UNITS[w]
        if w in _FUNCS:
            return _FUNCS[w]
        if w in params:
            return '(%r)' % params[w]
        raise NameError('unknown identifier %r in %r' % (w, expr))
    py = re.sub(r'[A-Za-z_][A-Za-z0-9_]*', sub, expr.replace('^', '**'))
    return eval(py, {'math': math})


class FeatureOperations:
    NewBodyFeatureOperation = 'NEW'
    JoinFeatureOperation = 'JOIN'
    CutFeatureOperation = 'CUT'


class DimensionOrientations:
    HorizontalDimensionOrientation = 'H'
    VerticalDimensionOrientation = 'V'


class DesignTypes:
    ParametricDesignType = 'param'


class PointContainment:
    PointInsidePointContainment = 0
    PointOutsidePointContainment = 1


class FeatureHealthStates:
    HealthyFeatureHealthState = 0
    ErrorFeatureHealthState = 2


class MeshRefinementSettings:
    MeshRefinementHigh = 0


class OffsetStartDefinition:
    def __init__(self, vi):
        self.vi = vi

    @staticmethod
    def create(vi):
        return OffsetStartDefinition(vi)


class Coll:
    def __init__(self, items=None):
        self._items = list(items or [])

    @property
    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]

    def __iter__(self):
        return iter(self._items)


# ------------------------------------------------------------------ params
class UserParameter:
    def __init__(self, design, name, expr, units, comment):
        self.design, self.name, self.units, self.comment = design, name, units, comment
        self._expr = None
        self.expression = expr

    @property
    def expression(self):
        return self._expr

    @expression.setter
    def expression(self, e):
        self._expr = e
        try:
            self.design.params[self.name] = evaluate(e, self.design.params)
        except Exception as ex:
            LOG['eval_errors'].append('param %s = %r: %s' % (self.name, e, ex))
            raise


class UserParameters:
    def __init__(self, design):
        self.design = design
        self._p = {}

    def itemByName(self, n):
        return self._p.get(n)

    def add(self, name, vi, units, comment):
        if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', name):
            raise RuntimeError('bad param name ' + name)
        p = UserParameter(self.design, name, vi.expr, units, comment)
        self._p[name] = p
        return p


class UnitsManager:
    def __init__(self, design):
        self.design = design

    def evaluateExpression(self, expr, units):
        try:
            return evaluate(expr, self.design.params)
        except Exception as ex:
            LOG['eval_errors'].append('%r: %s' % (expr, ex))
            raise RuntimeError('3 : invalid expression %r' % expr)


# ----------------------------------------------------------------- sketches
class SketchPoint:
    def __init__(self, g):
        self.geometry = g


class SketchLine:
    def __init__(self, a, b):
        self.startSketchPoint, self.endSketchPoint = a, b


class SketchCircle:
    def __init__(self, c, r):
        self.centerSketchPoint, self.radius = SketchPoint(c), r


class _Param:
    """A dimension's parameter: setting the expression checks it against the
    distance the sketch geometry was actually drawn at."""

    def __init__(self, dim):
        self.dim = dim
        self._e = None

    @property
    def expression(self):
        return self._e

    @expression.setter
    def expression(self, e):
        self._e = e
        d = self.dim
        val = evaluate(e, d.sketch.design.params)
        LOG['dims'] += 1
        if d.kind == 'dia':
            actual = 2 * d.ent.radius
        elif d.kind == 'H':
            actual = abs(d.p1.geometry.x - d.p2.geometry.x)
        else:
            actual = abs(d.p1.geometry.y - d.p2.geometry.y)
        if val < -1e-9 or abs(val - actual) > 1e-6:
            LOG['dim_errors'].append('%s: %s=%r evaluates %.4f mm, geometry %.4f mm'
                                     % (d.sketch.name, d.kind, e, val * 10, actual * 10))


class _Dim:
    def __init__(self, sketch, kind, p1=None, p2=None, ent=None):
        self.sketch, self.kind, self.p1, self.p2, self.ent = sketch, kind, p1, p2, ent
        self.parameter = _Param(self)


class _Dims:
    def __init__(self, sk):
        self.sk = sk

    def addDistanceDimension(self, p1, p2, orient, txt):
        return _Dim(self.sk, orient, p1, p2)

    def addDiameterDimension(self, c, txt):
        return _Dim(self.sk, 'dia', ent=c)


class _Constraints:
    def addCoincident(self, a, b):
        return True


class _Lines:
    """Tracks open polylines; closing one (back onto its first point)
    records a polygon profile."""

    def __init__(self, sk):
        self.sk = sk
        self.chain_start = None
        self.chain = []

    def addByTwoPoints(self, a, b):
        if not isinstance(a, SketchPoint):
            a = SketchPoint(a)
            self.chain_start, self.chain = a, [a]
        if not isinstance(b, SketchPoint):
            b = SketchPoint(b)
        if b is self.chain_start:
            self.sk.shapes.append(('poly', [p.geometry for p in self.chain]))
            self.chain_start, self.chain = None, []
        else:
            self.chain.append(b)
        return SketchLine(a, b)

    def addTwoPointRectangle(self, p1, p2):
        c = [SketchPoint(core.Point3D(p1.x, p1.y)), SketchPoint(core.Point3D(p2.x, p1.y)),
             SketchPoint(core.Point3D(p2.x, p2.y)), SketchPoint(core.Point3D(p1.x, p2.y))]
        self.sk.shapes.append(('poly', [p.geometry for p in c]))
        return Coll([SketchLine(c[i], c[(i + 1) % 4]) for i in range(4)])


class _Circles:
    def __init__(self, sk):
        self.sk = sk

    def addByCenterRadius(self, c, r):
        self.sk.shapes.append(('circle', (c, r)))
        return SketchCircle(c, r)


class _Curves:
    def __init__(self, sk):
        self.sketchLines = _Lines(sk)
        self.sketchCircles = _Circles(sk)


class _Profile:
    def __init__(self, sketch, shape):
        self.sketch, self.shape = sketch, shape
        self.profileLoops = Coll([1])


class Sketch:
    def __init__(self, design, plane):
        self.design, self.plane = design, plane
        self.name = ''
        self.shapes = []
        self.originPoint = SketchPoint(core.Point3D(0, 0, 0))
        self.sketchCurves = _Curves(self)
        self.sketchDimensions = _Dims(self)
        self.geometricConstraints = _Constraints()
        LOG['sketches'] += 1

    # YZ plane: sketch x = -Z, sketch y = Y (exercises the axis detection)
    def modelToSketchSpace(self, p):
        if self.plane == 'yz':
            return core.Point3D(-p.z, p.y, 0)
        return core.Point3D(p.x, p.y, 0)

    def to_model(self, sp):
        """Sketch point -> model (Y, Z) for a YZ sketch, (X, Y) for XY."""
        if self.plane == 'yz':
            return (sp.y, -sp.x)
        return (sp.x, sp.y)

    @property
    def profiles(self):
        return Coll([_Profile(self, s) for s in self.shapes])


class _Sketches:
    def __init__(self, comp):
        self.comp = comp

    def add(self, plane):
        return Sketch(self.comp.design, plane)


# ------------------------------------------------- bodies + fake B-rep
class _Eval:
    def __init__(self, n):
        self.n = n

    def getNormalAtPoint(self, p):
        return True, core.Vector3D(*self.n)


class _Surface:
    surfaceType = core.SurfaceTypes.PlaneSurfaceType


class BRepFace:
    def __init__(self, n, area):
        self.evaluator = _Eval(n)
        self.area = area
        self.pointOnFace = core.Point3D(0, 0, 0)
        self.geometry = _Surface()
        self.edges = Coll()


_TOKENS = {}


class BRepEdge:
    def __init__(self, f1, f2, length):
        self.faces = Coll([f1, f2])
        self.length = length
        self.pointOnEdge = core.Point3D(0, 0, 0)
        self.isValid = True
        self.entityToken = 'edge%d' % len(_TOKENS)
        _TOKENS[self.entityToken] = self
        f1.edges._items.append(self)
        f2.edges._items.append(self)

    @staticmethod
    def cast(x):
        return x if isinstance(x, BRepEdge) else None


class BRepBody:
    def __init__(self, comp):
        self.comp = comp
        self.name = ''
        self.isValid = True
        # Fake faces/edges of mixed sizes: enough to drive classification,
        # the bisect-on-failure path and the bed-face chamfer.
        fx0, fx1 = BRepFace((-1, 0, 0), 50.0), BRepFace((1, 0, 0), 40.0)
        fy, fz = BRepFace((0, 1, 0), 30.0), BRepFace((0, 0, 1), 2.0)
        self.faces = Coll([fx0, fx1, fy, fz])
        self.edges = Coll([BRepEdge(fx0, fy, 3.0), BRepEdge(fx1, fy, 3.0), BRepEdge(fx0, fz, 1.0),
                           BRepEdge(fx1, fz, 1.0), BRepEdge(fy, fz, 1.0), BRepEdge(fy, fz, 0.2),
                           BRepEdge(fy, fz, 0.5), BRepEdge(fx1, fz, 0.4)])

    def pointContainment(self, p):
        return PointContainment.PointOutsidePointContainment


class _Bodies(Coll):
    def itemByName(self, n):
        for b in self._items:
            if b.name == n:
                return b
        return None


class ExtrudeInput:
    def __init__(self, profs, op):
        self.profs, self.op = profs, op
        self.startExtent = None
        self.dist = None
        self.participantBodies = None

    def setDistanceExtent(self, sym, vi):
        self.dist = vi
        return True


class _Feature:
    def __init__(self, bodies):
        self.name = ''
        self.bodies = Coll(bodies)
        self.endFaces = Coll([object()])
        self.healthState = FeatureHealthStates.HealthyFeatureHealthState

    def deleteMe(self):
        return True


class _Extrudes:
    def __init__(self, comp):
        self.comp = comp

    def createInput(self, profs, op):
        if profs.count == 0:
            raise RuntimeError('createInput: no profiles')
        return ExtrudeInput(profs, op)

    def add(self, inp):
        params = self.comp.design.params
        x0 = evaluate(inp.startExtent.vi.expr, params) if inp.startExtent else 0.0
        d = evaluate(inp.dist.expr, params)
        if d <= 0:
            raise RuntimeError('extrude distance %r <= 0' % inp.dist.expr)
        if inp.op == 'NEW':
            body = BRepBody(self.comp)
            self.comp.bRepBodies._items.append(body)
        else:
            if not inp.participantBodies or inp.participantBodies[0] is None:
                raise RuntimeError('join/cut without a participant body')
            body = inp.participantBodies[0]
        shapes = []
        for pr in inp.profs:
            kind, g = pr.shape
            if kind == 'poly':
                shapes.append(('poly', [pr.sketch.to_model(p) for p in g]))
            else:
                c, r = g
                shapes.append(('circle', (pr.sketch.to_model(c), r)))
        LOG['prisms'].append({'comp': self.comp.name, 'op': inp.op, 'x0': x0, 'x1': x0 + d,
                              'shapes': shapes})
        return _Feature([body])


class _EdgeSets:
    def __init__(self, inp):
        self.inp = inp

    def addConstantRadiusEdgeSet(self, edges, vi, tangent):
        evaluate(vi.expr, LOG['params'])
        self.inp.sets.append((edges.count, vi.expr))
        return True

    def addEqualDistanceChamferEdgeSet(self, edges, vi, tangent):
        return self.addConstantRadiusEdgeSet(edges, vi, tangent)


class _FinishInput:
    def __init__(self):
        self.sets = []
        self.edgeSetInputs = _EdgeSets(self)
        self.chamferEdgeSets = self.edgeSetInputs


class _FinishFeatures:
    """Fillets / chamfers. Refuses more than 2 edges at once so the script's
    split-and-retry path gets exercised."""

    def __init__(self, kind):
        self.kind = kind

    def createInput(self):
        return _FinishInput()

    def createInput2(self):
        return _FinishInput()

    def add(self, inp):
        if sum(c for c, _ in inp.sets) > 2:
            raise RuntimeError('mock: too many edges at once')
        LOG['finishing'].append((self.kind, inp.sets))
        return _Feature([])


class _Features:
    def __init__(self, comp):
        self.extrudeFeatures = _Extrudes(comp)
        self.filletFeatures = _FinishFeatures('fillet')
        self.chamferFeatures = _FinishFeatures('chamfer')


class Component:
    def __init__(self, design):
        self.design = design
        self.name = ''
        self.xYConstructionPlane = 'xy'
        self.yZConstructionPlane = 'yz'
        self.sketches = _Sketches(self)
        self.features = _Features(self)
        self.bRepBodies = _Bodies()
        self.occurrences = _Occurrences(design)


class Occurrence:
    def __init__(self, comp):
        self.component = comp
        self.isGrounded = False


class _Occurrences:
    def __init__(self, design):
        self.design = design

    def addNewComponent(self, m):
        return Occurrence(Component(self.design))


class _STLOpts:
    def __init__(self, body, path):
        self.body, self.path = body, path
        self.meshRefinement = None


class ExportManager:
    """Records the export paths; check.py writes the real (preview) STLs."""

    def createSTLExportOptions(self, body, path):
        if body is None:
            raise RuntimeError('STL export: no body')
        return _STLOpts(body, path)

    def execute(self, opts):
        LOG['stl'].append(opts.path)
        return True


class Design:
    def __init__(self):
        self.params = LOG['params']
        self.params.clear()
        self.userParameters = UserParameters(self)
        self.unitsManager = UnitsManager(self)
        self.rootComponent = Component(self)
        self.exportManager = ExportManager()
        self.designType = None

    @staticmethod
    def cast(x):
        return x

    def findEntityByToken(self, t):
        return [_TOKENS[t]] if t in _TOKENS else []
