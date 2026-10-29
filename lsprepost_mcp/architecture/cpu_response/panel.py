"""Small-strain layered RC shell; each rebar field is a native layer response."""
import math
from .column import run_static, node_sample
from .loads import map_pressure


def section_layers(case, reinforced=True):
    g,r,m=case['geometry'],case['reinforcement'],case['materials']
    h=g['thickness_m'];d=r['diameter_m'];c=r['cover_m']
    ts=math.pi*d*d/(4*r['spacing_m'])
    steel=[]
    if reinforced:
        for side,sign in (('bottom',-1),('top',1)):
            for direction,offset in (('X',d/2),('Y',1.5*d)):
                steel.append(dict(kind='steel',axis=direction,side=side,z=sign*(h/2-c-offset),t=ts))
    steel.sort(key=lambda x:x['z'])
    layers=[];cursor=-h/2
    for layer in steel:
        lower=layer['z']-ts/2
        if lower>cursor:layers.append(dict(kind='concrete',z=(cursor+lower)/2,t=lower-cursor))
        layers.append(layer);cursor=layer['z']+ts/2
    if cursor<h/2:layers.append(dict(kind='concrete',z=(cursor+h/2)/2,t=h/2-cursor))
    # LayeredShell uses each layer's midpoint as its thickness quadrature point.
    # A thick concrete interval must be subdivided to retain bending stiffness.
    refined=[]
    for layer in layers:
        count=max(1,math.ceil(layer['t']/(h/20))) if layer['kind']=='concrete' else 1
        for i in range(count):
            refined.append(dict(layer,t=layer['t']/count,
                                z=layer['z']-layer['t']/2+(i+0.5)*layer['t']/count))
    return refined


def define_panel_section(ops,case,reinforced=True,*,tag=1,material_offset=0):
    """Shared verified layer construction; explicit tag offset for assemblies."""
    m=case['materials'];o=material_offset
    ec,nu,es=m['concrete_e_pa'],m['concrete_nu'],m['steel_e_pa']
    ops.nDMaterial('ElasticIsotropic',o+1,ec,nu,0)
    ops.uniaxialMaterial('Elastic',o+2,es)
    ops.nDMaterial('PlateRebar',o+2,o+2,0);ops.nDMaterial('PlateRebar',o+3,o+2,90)
    layers=section_layers(case,reinforced)
    args=[];dmat=[0.0]*4;ma=0
    for layer in layers:
        if layer['kind']=='concrete':
            mat=1;q=[ec/(1-nu*nu),ec/(1-nu*nu),nu*ec/(1-nu*nu),ec/(2*(1+nu))]
            density=m['concrete_density']
        else:
            mat=2 if layer['axis']=='X' else 3
            q=[es,0,0,0] if mat==2 else [0,es,0,0]
            density=m['steel_density']
        args.extend([o+mat,layer['t']]);ma+=density*layer['t']
        integral=layer['t']*layer['z']**2+layer['t']**3/12
        for k in range(4):dmat[k]+=q[k]*integral
    ops.section('LayeredShell',tag,len(layers),*args)
    return dict(layers=layers,area_mass_kg_m2=ma,laminate_d_nm=dmat)


def build_panel(ops,case,reinforced=True,*,quarter=False,bending_only=False):
    ops.wipe();ops.model('basic','-ndm',3,'-ndf',6)
    section=define_panel_section(ops,case,reinforced)
    layers,ma,dmat=section['layers'],section['area_mass_kg_m2'],section['laminate_d_nm']
    g,m=case['geometry'],case['materials'];n=case['mesh']['n'];a,b=g['a_m'],g['b_m']
    if quarter:n//=2;a/=2;b/=2
    es=m['steel_e_pa']
    nodes=[[a*i/n,b*j/n,0] for j in range(n+1) for i in range(n+1)]
    masses=[0.0]*len(nodes);elements=[];support=[]
    for i,xyz in enumerate(nodes):ops.node(i+1,*xyz)
    for j in range(n):
        for i in range(n):
            first=j*(n+1)+i
            element=[first,first+1,first+n+2,first+n+1]
            elements.append(element)
            ops.element('ShellMITC4',len(elements),*[v+1 for v in element],1)
            for node in element:masses[node]+=ma*a*b/(n*n*4)
    for j in range(n+1):
        for i in range(n+1):
            node=j*(n+1)+i;boundary=i in (0,n) or j in (0,n)
            # Navier-compatible hard simple support: w=0 and the edge-normal
            # physical rotation is zero; the bending slope across the edge is free.
            fix=[0,0,int(boundary),int(i in (0,n)),int(j in (0,n)),0]
            if quarter:
                # Physical supports on x=0/y=0; mirror planes on x=a/y=b.
                # Rotations are axial vectors and reflect differently from u.
                fix=[int(i==n),int(j==n),int(i==0 or j==0),int(i==0 or j==n),int(j==0 or i==n),int(i==n or j==n)]
            else:
                if node==0:fix[0]=fix[1]=1
                if node==n:fix[1]=1
            # The frozen flat symmetric laminate has B=0 and transverse loads
            # only. In-plane translation/drilling form an unforced zero block.
            if bending_only:fix[0]=fix[1]=fix[5]=1
            if any(fix):ops.fix(node+1,*fix);support.append(node)
            ops.mass(node+1,masses[node],masses[node],masses[node],0,0,0)
    samples=[]
    gauss=1/math.sqrt(3)
    # Native ShellMITC4 integration point ordering.
    gps=((-gauss,-gauss),(gauss,-gauss),(gauss,gauss),(-gauss,gauss))
    for eid,element in enumerate(elements,1):
        x,y,_=nodes[element[0]]
        for ip,(xi,eta) in enumerate(gps,1):
            for li,layer in enumerate(layers,1):
                if layer['kind']=='steel':
                    samples.append(dict(id=f'e{eid}-ip{ip}-{layer["side"]}-{layer["axis"]}',
                                        element=eid,ip=ip,layer=li,side=layer['side'],axis=layer['axis'],
                                        position_m=[x+(xi+1)*a/(2*n),y+(eta+1)*b/(2*n),layer['z']],
                                        local_axis=([1,0,0] if layer['axis']=='X' else [0,1,0]),
                                        scope='smeared_rebar_layer'))
    model=dict(kind='panel',nodes=nodes,elements=elements,steel_samples=samples,
               monitor_node=len(nodes)-1 if quarter else (n//2)*(n+1)+n//2,node_masses_kg=masses,mass_kg=ma*a*b,
               support_nodes=support,laminate_d_nm=dmat,layers=layers,steel_e_pa=es)
    model['load_map']=map_pressure(model,case['loads'])
    return model


def read_panel_sample(ops,model,time_s):
    sample=node_sample(ops,model,time_s);stress=[];strain=[]
    for s in model['steel_samples']:
        prefix=(s['element'],'material',s['ip'],'fiber',s['layer'])
        sv=ops.eleResponse(*prefix,'stress');ev=ops.eleResponse(*prefix,'strain')
        if len(sv)!=5 or len(ev)!=5:raise RuntimeError('missing native reinforcement layer stress/strain')
        k=0 if s['axis']=='X' else 1
        stress.append(sv[k]);strain.append(ev[k])
    sample.update(steel_stress_pa=stress,steel_strain=strain)
    return sample
