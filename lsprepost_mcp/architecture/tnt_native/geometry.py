"""Shared explicit solids for architecture preview and component FE sampling."""
from itertools import product
import math

SIGNS = ((-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
         (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1))
FACES = ((0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7))

def vertices(bounds):
    a,b,c,d,e,f = bounds
    return [[a,b,c],[d,b,c],[d,e,c],[a,e,c],[a,b,f],[d,b,f],[d,e,f],[a,e,f]]

def bounds_of(points):
    return [min(p[i] for p in points) for i in range(3)] + [max(p[i] for p in points) for i in range(3)]

def contains(bounds, point, strict=False):
    eps = 1e-8
    if strict:
        return all(bounds[i]+eps < point[i] < bounds[i+3]-eps for i in range(3))
    return all(bounds[i]-eps <= point[i] <= bounds[i+3]+eps for i in range(3))

def overlap(a,b):
    return all(min(a[i+3],b[i+3])-max(a[i],b[i]) > 1e-8 for i in range(3))

def subtract_box(box, cut):
    if not overlap(box, cut):
        return [list(box)]
    lo = [max(box[i],cut[i]) for i in range(3)]
    hi = [min(box[i+3],cut[i+3]) for i in range(3)]
    current = list(box)
    pieces = []
    for axis in range(3):
        if current[axis] < lo[axis]-1e-8:
            part = current.copy(); part[axis+3] = lo[axis]; pieces.append(part)
            current[axis] = lo[axis]
        if hi[axis] < current[axis+3]-1e-8:
            part = current.copy(); part[axis] = hi[axis]; pieces.append(part)
            current[axis+3] = hi[axis]
    return pieces

def determinant(matrix):
    a,b,c = matrix
    return a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])

def jacobian(points, location):
    matrix = [[0.0]*3 for _ in range(3)]
    for p, signs in zip(points, SIGNS):
        for axis in range(3):
            d = signs[axis]/8.0
            for other in range(3):
                if other != axis:
                    d *= 1+signs[other]*location[other]
            for coord in range(3):
                matrix[coord][axis] += p[coord]*d
    return determinant(matrix)

def signed_volume(points):
    q = 1/math.sqrt(3)
    return sum(jacobian(points, loc) for loc in product((-q,q), repeat=3))

def interpolate(points, u,v,w):
    location = (2*u-1,2*v-1,2*w-1)
    result = [0.0,0.0,0.0]
    for p, sign in zip(points,SIGNS):
        weight = math.prod(1+s*x for s,x in zip(sign,location))/8
        for axis in range(3):
            result[axis] += p[axis]*weight
    return result

class Builder:
    def __init__(self, scenario):
        self.scenario = scenario
        self.components = []
        self.rooms = []
        self.openings = []
        self.voids = []
        self.circulation = []

    def solid(self, key, label, role, points, level=0, material="concrete", **extra):
        row = {"id":key,"label":label,"role":role,"level":level,"material":material,
               "vertices_m":[[round(float(x),7) for x in p] for p in points],
               "bounds_m":bounds_of(points),"preview_only":role in {"furniture","finish","equipment"},
               **extra}
        self.components.append(row)
        return row

    def box(self, key, label, role, bounds, level=0, material="concrete", **extra):
        return self.solid(key,label,role,vertices(bounds),level,material,**extra)

    def cut_box(self, key, label, role, bounds, cuts=(), level=0, material="concrete", **extra):
        pieces = [list(bounds)]
        for cut in cuts:
            pieces = [out for piece in pieces for out in subtract_box(piece,cut)]
        for i,piece in enumerate(pieces):
            self.box(f"{key}.{i}",label,role,piece,level,material,**extra)

    def room(self, key,label,kind,bounds,level=0,unit="public"):
        self.rooms.append({"id":key,"label":label,"kind":kind,"bounds_m":bounds,
                           "level":level,"unit":unit,
                           "area_m2":round((bounds[3]-bounds[0])*(bounds[4]-bounds[1]),2)})
        return key

    def wall(self,key,axis,fixed,start,end,z,height,thickness,level=0,openings=(),
             exterior=False,role="wall",material="plaster"):
        b = [0,0,z,0,0,z+height]
        b[axis], b[axis+3] = start,end
        b[1-axis],b[4-axis] = fixed-thickness/2,fixed+thickness/2
        cuts=[]
        for i,o in enumerate(openings):
            low,high,bottom,top,kind,connects = o
            cut=b.copy();cut[axis]=low;cut[axis+3]=high;cut[2]=z+bottom;cut[5]=z+top
            cuts.append(cut)
            self.openings.append({"id":f"{key}.opening{i}","host":key,"bounds_m":cut,
                                  "kind":kind,"connects":list(connects),"width_m":high-low,
                                  "level":level,"axis":axis})
            if kind == "window":
                glass=cut.copy();glass[1-axis]=fixed-.014;glass[4-axis]=fixed+.014
                self.box(f"{key}.glass{i}","窗玻璃","glass",glass,level,"glass",exterior=exterior)
                for edge in (low, high, (low+high)/2):
                    frame=glass.copy();frame[axis]=edge-.028;frame[axis+3]=edge+.028
                    self.box(f"{key}.frame{i}.{edge:.3f}","窗框","window_frame",frame,level,"metal",exterior=exterior)
                for edge in (z+bottom,z+top):
                    frame=glass.copy();frame[2]=edge-.028;frame[5]=edge+.028
                    self.box(f"{key}.frame{i}.z{edge:.3f}","窗框","window_frame",frame,level,"metal",exterior=exterior)
            elif kind == "door":
                # A partly open leaf for legibility; opening itself is truly cut out.
                leaf=cut.copy();leaf[axis]=low;leaf[axis+3]=low+.04
                leaf[1-axis]=fixed;leaf[4-axis]=fixed+min(high-low,.8)
                self.box(f"{key}.leaf{i}","门扇（开启）","door",leaf,level,"wood",exterior=exterior,preview_only=True)
        self.cut_box(key,"外围墙" if exterior else "隔墙","wall" if exterior else role,
                     b,cuts,level,material,exterior=exterior)

    def ramp(self,key,label,x0,x1,y0,y1,z0,z1,thickness,level=0,role="stair",material="concrete"):
        pts = [[x0,y0,z0-thickness],[x1,y0,z0-thickness],[x1,y1,z1-thickness],[x0,y1,z1-thickness],
               [x0,y0,z0],[x1,y0,z0],[x1,y1,z1],[x0,y1,z1]]
        return self.solid(key,label,role,pts,level,material)

    def stair(self,key,x0,x1,y0,y1,z0,z1,level=0):
        count = math.ceil(abs(z1-z0)/.18)
        for i in range(count):
            ya=y0+(y1-y0)*i/count;yb=y0+(y1-y0)*(i+1)/count
            za=z0+(z1-z0)*i/count;zb=z0+(z1-z0)*(i+1)/count
            # Extruded trapezoidal tread. Adjacent pieces share a riser surface.
            top=max(za,zb)
            pts=[[x0,ya,za-.18],[x1,ya,za-.18],[x1,yb,zb-.18],[x0,yb,zb-.18],
                 [x0,ya,top],[x1,ya,top],[x1,yb,top],[x0,yb,top]]
            if y1<y0:
                pts=[pts[j] for j in (3,2,1,0,7,6,5,4)]
            self.solid(f"{key}.step{i}","楼梯踏步及梯板","stair",pts,level)
        for x in (x0+.04,x1-.04):
            # Glass balustrade envelope follows the flight without blocking it.
            self.ramp(f"{key}.rail{x:.3f}","楼梯栏板",x-.025,x+.025,min(y0,y1),max(y0,y1),
                      (z0 if y0<y1 else z1)+1.0,(z1 if y0<y1 else z0)+1.0,.9,level,"railing","glass")
