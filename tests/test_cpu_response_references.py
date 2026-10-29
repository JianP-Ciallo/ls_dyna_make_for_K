"""Independent closed-form SI references. No production builders/imports."""
import math


def plate_reference():
    # Actual four steel centroids. Each replaces concrete of the same smeared t.
    t=math.pi*0.01**2/(4*0.2)
    centers=[(-0.045,'X'),(-0.035,'Y'),(0.035,'Y'),(0.045,'X')]
    qc=[30e9/0.96,30e9/0.96,0.2*30e9/0.96,30e9/2.4]
    d=[q*0.15**3/12 for q in qc];b=[0.0]*4
    for z,axis in centers:
        qs=[200e9,0,0,0] if axis=='X' else [0,200e9,0,0]
        for i in range(4):
            d[i]+=(qs[i]-qc[i])*(t*z*z+t**3/12)
            b[i]+=(qs[i]-qc[i])*t*z
    def navier(limit):
        w=0
        for m in range(1,limit,2):
            for n in range(1,limit,2):
                den=math.pi**4*(d[0]*(m/2)**4+2*(d[2]+2*d[3])*(m/2)**2*(n/2)**2+d[1]*(n/2)**4)
                w+=16*10000/(math.pi**2*m*n)*math.sin(m*math.pi/2)*math.sin(n*math.pi/2)/den
        return w
    return dict(steel_t_m=t,centers=centers,d_nm=d,b_n=b,mass_kg=4*(2500*(0.15-4*t)+7850*4*t),
                center_w_m=navier(100),navier_truncation_m=abs(navier(100)-navier(50)))


def column_reference():
    area=math.pi*0.016**2/4
    ei=30e9*0.3**4/12+(200e9-30e9)*4*area*0.102**2
    mu=(0.09-4*area)*2500+4*area*7850
    return dict(ei_nm2=ei,mass_kg=3*mu,tip_static_m=3000*3**4/(8*ei),
                omega_rad_s=1.8751040687**2*math.sqrt(ei/(mu*3**4)))
