"""Geometry checks for the planar convex hexahedra used by the new architecture."""
from itertools import product
import math

from .geometry import FACES, SIGNS, determinant, bounds_of, overlap

EDGES = ((0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7))
CHECK_LOCATIONS = tuple(product((-1,1), repeat=3)) + tuple(product((-1/math.sqrt(3),1/math.sqrt(3)), repeat=3))


def subtract(a, b):
    return tuple(a[i]-b[i] for i in range(3))


def dot(a, b):
    return sum(x*y for x,y in zip(a,b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def scaled_jacobian(points, location):
    columns = [[0.,0.,0.] for _ in range(3)]
    for p, signs in zip(points, SIGNS):
        for axis in range(3):
            d = signs[axis]/8 * math.prod(1+signs[j]*location[j] for j in range(3) if j != axis)
            for k in range(3):
                columns[axis][k] += p[k]*d
    denominator = math.prod(math.sqrt(dot(v,v)) for v in columns)
    return determinant(columns)/denominator if denominator else 0.


def face_planes(points):
    """Outward unit normals; reject warped/non-convex shapes instead of using their AABB."""
    result = []
    for face in FACES:
        a,b,c,d = (points[i] for i in face)
        normal = cross(subtract(b,a), subtract(c,a))
        length = math.sqrt(dot(normal,normal))
        if length <= 1e-14:
            raise ValueError('degenerate solid face')
        normal = tuple(x/length for x in normal)
        if abs(dot(normal, subtract(d,a))) > 1e-7:
            raise ValueError('architecture requires planar solid faces')
        if any(dot(normal, subtract(p,a)) > 1e-7 for p in points):
            raise ValueError('architecture requires convex solid geometry')
        result.append((a,normal))
    return result


def contains_point(points, point, tolerance=1e-8):
    return all(dot(n,subtract(point,a)) <= tolerance for a,n in face_planes(points))


def interiors_overlap(a, b, tolerance=1e-8):
    if not overlap(bounds_of(a),bounds_of(b)):
        return False
    axes = [n for _,n in face_planes(a)] + [n for _,n in face_planes(b)]
    # Separating-axis theorem: all face normals and edge cross-products.
    axes.extend(cross(subtract(a[j],a[i]),subtract(b[l],b[k]))
                for i,j in EDGES for k,l in EDGES)
    for axis in axes:
        length = math.sqrt(dot(axis,axis))
        if length <= 1e-12:
            continue
        axis = tuple(x/length for x in axis)
        p = [dot(axis,x) for x in a]
        q = [dot(axis,x) for x in b]
        if min(max(p),max(q))-max(min(p),min(q)) <= tolerance:
            return False
    return True
