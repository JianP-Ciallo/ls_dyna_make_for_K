"""Pressure interpolation and consistent beam/shell nodal loads."""
import math
from .contracts import finite


def validate_curve(curve):
    if not isinstance(curve, list) or not 2 <= len(curve) <= 10000:
        raise ValueError('pressure curve needs 2..10000 rows')
    previous = -1
    for row in curve:
        if not isinstance(row,list) or len(row)!=2:
            raise ValueError('curve row needs time and pressure')
        t,p = row
        finite(t,0,1,'curve time'); finite(p,0,100000,'pressure')
        if t <= previous:
            raise ValueError('curve times must increase strictly')
        previous = t
    if curve[0] != [0,0] or curve[-1][1] != 0:
        raise ValueError('curve must start at zero and finish unloaded')


def curve_to_si(curve):
    if not isinstance(curve,list):
        raise ValueError('curve requires rows')
    converted = []
    for row in curve:
        if not isinstance(row,list) or len(row)!=2:
            raise ValueError('curve row needs ms and kPa')
        t,p = row
        finite(t,0,1000,'time_ms');finite(p,0,100,'pressure_kpa')
        converted.append([t/1000,p*1000])
    validate_curve(converted)
    return converted


def curve_impulse(curve):
    return sum((b[0]-a[0])*(a[1]+b[1])/2 for a,b in zip(curve,curve[1:]))


def pressure_at(curve, time_s):
    for (ta,pa),(tb,pb) in zip(curve,curve[1:]):
        if ta <= time_s <= tb:
            return pa+(pb-pa)*(time_s-ta)/(tb-ta)
    return 0.0


def map_pressure(model: dict, load: dict) -> dict:
    normal = load['direction']
    vectors = [[0.0]*6 for _ in model['nodes']]
    area = 0.0
    for element in model['elements']:
        points = [model['nodes'][i] for i in element]
        if model['kind']=='column':
            length = math.dist(*points)
            a = model['width_m']*length
            axis = [(points[1][i]-points[0][i])/length for i in range(3)]
            cross = [axis[1]*normal[2]-axis[2]*normal[1],axis[2]*normal[0]-axis[0]*normal[2],axis[0]*normal[1]-axis[1]*normal[0]]
            for end,node in enumerate(element):
                for k in range(3):
                    vectors[node][k] += a*normal[k]/2
                    vectors[node][k+3] += (1 if end==0 else -1)*cross[k]*a*length/12
        else:
            a = math.dist(points[0],points[1])*math.dist(points[1],points[2])
            for node in element:
                for k in range(3):
                    vectors[node][k] += a*normal[k]/4
        area += a
    return dict(area_m2=area, nodal_vectors_per_pa=vectors)
