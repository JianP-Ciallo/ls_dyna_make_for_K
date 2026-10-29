"""Metric Swisdak (1994) simplified Kingery surface-burst coefficients.

Coefficient transcription adapted from fcento100/kingery-bulmash (MIT, 2024).
See resources/scene_blast/THIRD_PARTY_NOTICES.txt. Ground burst only, 0.2<=Z<=40.
The triangular positive pulse matches the independently tabulated peak and impulse;
its equivalent duration is NOT the empirical positive-phase duration. No clearing,
shielding, diffraction, multiple reflections, negative phase, or air-domain field.
"""
import math
import numpy as np


def poly(z, coefficients):
    x=math.log(z)
    return math.exp(sum(c*x**i for i,c in enumerate(coefficients)))


def parameters(mass_kg, distance_m):
    if not all(math.isfinite(x) and x>0 for x in (mass_kg,distance_m)):raise ValueError('TNT 当量与距离必须为有限正数')
    w=mass_kg**(1/3);z=distance_m/w
    if not .2<=z<=40:raise ValueError(f'缩尺距离 Z={z:.3g} 超出首版地面爆炸范围 0.2–40 m/kg^(1/3)')
    arrival=poly(z,(-.7604,1.8058,.1257,-.0437,-.031,-.00669) if z<=1.5 else (-.7137,1.5732,.5561,-.4213,.1054,-.00929))*w/1000
    incident=poly(z,(7.2106,-2.1069,-.3229,.1117,.0685) if z<=2.9 else ((7.5938,-3.0523,.40977,.0261,-.01267) if z<=23.8 else (6.0536,-1.4066)))*1000
    reflected=poly(z,(9.006,-2.6893,-.6295,.1011,.29255,.13505,.019736) if z<=2 else (8.8396,-1.733,-2.64,2.293,-.8232,.14247,-.0099))*1000
    ci=(5.522,1.117,.6,-.292,-.087) if z<=.96 else ((5.465,-.308,-1.464,1.362,-.432) if z<=2.38 else ((5.2749,-.4677,-.2499,.0588,-.00554) if z<=33.7 else (5.9825,-1.062)))
    return dict(scaled_distance=z,arrival_s=arrival,incident_pa=incident,reflected_pa=reflected,
                incident_impulse_pa_s=poly(z,ci)*w, reflected_impulse_pa_s=poly(z,(6.7853,-1.3466,.101,-.01123))*w)


def pulse(time_s, arrival_s, peak_pa, impulse_pa_s):
    t=np.asarray(time_s)-arrival_s
    duration=2*np.asarray(impulse_pa_s)/np.asarray(peak_pa)
    return np.where((t>=0)&(t<=duration),peak_pa*(1-t/duration),0.)


def pulse_average(start_s,end_s,arrival_s,peak_pa,impulse_pa_s):
    """Exact positive-pulse impulse in a time bin; never miss a narrow arrival."""
    duration=2*np.asarray(impulse_pa_s)/np.asarray(peak_pa)
    def integral(t):
        u=np.clip(t-arrival_s,0,duration)
        return peak_pa*(u-u*u/(2*duration))
    return (integral(end_s)-integral(start_s))/(end_s-start_s)


def surface_parameters(config, model):
    """Independent-field approximation, including rear faces (never silently zeroed)."""
    origin=np.array(config['tnt']['position_m']);rows=[]
    for s in model['surfaces']:
        point=np.array(s['point_m']); delta=origin-point;distance=float(np.linalg.norm(delta))
        p=parameters(config['tnt']['mass_kg'],distance)
        cosine=max(0.,float(np.dot(np.array(s['normal']),delta/distance)))
        # Explicit cosine-squared interpolation; not an exact oblique reflection law.
        p['peak_pa']=p['incident_pa']+(p['reflected_pa']-p['incident_pa'])*cosine**2
        p['impulse_pa_s']=p['incident_impulse_pa_s']+(p['reflected_impulse_pa_s']-p['incident_impulse_pa_s'])*cosine**2
        rows.append(p)
    return rows
