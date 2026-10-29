"""Exact reflection of the uniform flat elastic panel benchmark, not buildings."""
import math
import numpy as np


class PanelSymmetry:
    def __init__(self,native,case):
        if case['source']['id']!='rc-panel-v1' or case['materials']['profile']!='elastic_reference':
            raise ValueError('quarter symmetry is limited to the uniform elastic reference panel')
        n=case['mesh']['n'];q=n//2;a=case['geometry']['a_m'];b=case['geometry']['b_m']
        nodes=[[a*i/n,b*j/n,0] for j in range(n+1) for i in range(n+1)]
        self.node_indices=[];self.u_sign=[];self.r_sign=[]
        for j in range(n+1):
            for i in range(n+1):
                self.node_indices.append(min(j,n-j)*(q+1)+min(i,n-i))
                sx=1 if i<=q else -1;sy=1 if j<=q else -1
                self.u_sign.append([sx,sy,1]);self.r_sign.append([sy,sx,sx*sy])
        self.node_indices=np.asarray(self.node_indices);self.u_sign=np.asarray(self.u_sign);self.r_sign=np.asarray(self.r_sign)
        gps=[(-1,-1),(1,-1),(1,1),(-1,1)];samples=[];elements=[];masses=[0.0]*len(nodes);self.steel_indices=[]
        element_mass=native['mass_kg']*4/(n*n)
        for j in range(n):
            for i in range(n):
                first=j*(n+1)+i;nodes4=[first,first+1,first+n+2,first+n+1];elements.append(nodes4)
                for node in nodes4:masses[node]+=element_mass/4
                ni=i if i<q else n-1-i;nj=j if j<q else n-1-j
                sx=1 if i<q else -1;sy=1 if j<q else -1
                for ip,(xi,eta) in enumerate(gps,1):
                    native_ip=gps.index((xi*sx,eta*sy))+1
                    for li in range(4):
                        index=((nj*q+ni)*4+native_ip-1)*4+li;source=native['steel_samples'][index]
                        self.steel_indices.append(index)
                        samples.append(dict(source,id=f'e{j*n+i+1}-ip{ip}-{source["side"]}-{source["axis"]}',element=j*n+i+1,ip=ip,
                                            native_element=source['element'],native_ip=source['ip'],
                                            position_m=[(i+(xi/math.sqrt(3)+1)/2)*a/n,(j+(eta/math.sqrt(3)+1)/2)*b/n,source['position_m'][2]]))
        self.steel_indices=np.asarray(self.steel_indices)
        self.first_full={}
        for i,index in enumerate(self.steel_indices):self.first_full.setdefault(int(index),i)
        self.mesh=dict(native,nodes=nodes,elements=elements,steel_samples=samples,monitor_node=q*(n+1)+q,
                       mass_kg=native['mass_kg']*4,node_masses_kg=masses,
                       support_nodes=[j*(n+1)+i for j in range(n+1) for i in range(n+1) if i in (0,n) or j in (0,n)],
                       symmetry=dict(fraction=.25,native_nodes=len(native['nodes']),native_elements=len(native['elements']),
                                     scope='uniform_symmetric_elastic_reference_only'))

    def sample_id(self,native_index):return self.mesh['steel_samples'][self.first_full[native_index]]['id']

    def frame(self,sample):
        return dict(time_s=sample['time_s'],
                    displacements_m=(np.asarray(sample['displacements_m'])[self.node_indices]*self.u_sign).tolist(),
                    rotations_rad=(np.asarray(sample['rotations_rad'])[self.node_indices]*self.r_sign).tolist(),
                    steel_stress_pa=np.asarray(sample['steel_stress_pa'])[self.steel_indices].tolist(),
                    steel_strain=np.asarray(sample['steel_strain'])[self.steel_indices].tolist())
