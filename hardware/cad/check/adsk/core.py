"""Minimal mock of adsk.core for dry-running Fusion scripts."""
import math

LOG = {'messages': []}


class Point3D:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z

    @staticmethod
    def create(x=0.0, y=0.0, z=0.0):
        return Point3D(x, y, z)

    def distanceTo(self, o):
        return math.sqrt((self.x - o.x) ** 2 + (self.y - o.y) ** 2 + (self.z - o.z) ** 2)

    def copy(self):
        return Point3D(self.x, self.y, self.z)

    def translateBy(self, v):
        self.x += v.x; self.y += v.y; self.z += v.z
        return True


class Vector3D:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z

    @staticmethod
    def create(x=0.0, y=0.0, z=0.0):
        return Vector3D(x, y, z)

    @property
    def length(self):
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    def normalize(self):
        L = self.length
        self.x /= L; self.y /= L; self.z /= L
        return True

    def scaleBy(self, s):
        self.x *= s; self.y *= s; self.z *= s
        return True

    def dotProduct(self, o):
        return self.x * o.x + self.y * o.y + self.z * o.z


class Matrix3D:
    @staticmethod
    def create():
        return Matrix3D()


class ObjectCollection:
    def __init__(self):
        self._items = []

    @staticmethod
    def create():
        return ObjectCollection()

    def add(self, x):
        self._items.append(x)
        return True

    @property
    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]

    def __iter__(self):
        return iter(self._items)


class ValueInput:
    def __init__(self, expr):
        self.expr = expr

    @staticmethod
    def createByString(expr):
        if not isinstance(expr, str):
            raise TypeError('ValueInput.createByString needs a string, got %r' % (expr,))
        return ValueInput(expr)


class DocumentTypes:
    FusionDesignDocumentType = 'design'


class SurfaceTypes:
    PlaneSurfaceType = 0
    CylinderSurfaceType = 1


class _Viewport:
    def fit(self):
        return True


class _UI:
    def messageBox(self, msg, *a):
        LOG['messages'].append(msg)
        print('---- messageBox ----\n' + msg + '\n--------------------')
        return 0


class _Documents:
    def __init__(self, app):
        self.app = app

    def add(self, kind):
        from . import fusion
        self.app.activeProduct = fusion.Design()
        return self.app.activeProduct


class Application:
    _inst = None

    def __init__(self):
        self.userInterface = _UI()
        self.documents = _Documents(self)
        self.activeProduct = None
        self.activeViewport = _Viewport()

    @staticmethod
    def get():
        if Application._inst is None:
            Application._inst = Application()
        return Application._inst
