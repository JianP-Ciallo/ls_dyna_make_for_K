"""Explicit tiny native-library characterization, only in the isolated worker."""
import json
from pathlib import Path
import sys
import openseespy.opensees as ops


def require(condition,details='native characterization failed'):
    if not condition:raise RuntimeError(str(details))


def analysis():
    ops.constraints('Transformation');ops.numberer('RCM');ops.system('UmfPack')
    ops.test('NormDispIncr',1e-12,30);ops.algorithm('Newton')
    ops.integrator('LoadControl',1);ops.analysis('Static')
    require(ops.analyze(1)==0,'native probe did not converge')


def probe():
    ops.wipe();ops.model('basic','-ndm',3,'-ndf',6)
    ops.node(1,0,0,0);ops.node(2,0,0,1);ops.fix(1,1,1,1,1,1,1)
    ops.uniaxialMaterial('Elastic',1,200e9)
    ops.section('Fiber',1,'-GJ',1e6)
    for y in (-0.1,0.1):
        for z in (-0.1,0.1):ops.fiber(y,z,0.0002,1)
    ops.geomTransf('Linear',1,0,1,0);ops.beamIntegration('Lobatto',1,1,3)
    ops.element('dispBeamColumn',1,1,2,1,1)
    ops.timeSeries('Linear',1);ops.pattern('Plain',1,1);ops.load(2,0,0,0,100,0,0)
    analysis()
    steel=ops.eleResponse(1,'section',1,'fiber',0.1,0.1,1,'stressStrain')
    require(len(steel)==2 and abs(steel[0])>0,'missing nonzero native fiber stress')
    require(abs(steel[0]/steel[1]-200e9)<1,'fiber stress/strain mismatch')
    ops.wipe();ops.model('basic','-ndm',3,'-ndf',6)
    ops.nDMaterial('ElasticIsotropic',1,30e9,0.2)
    ops.uniaxialMaterial('Elastic',2,200e9)
    ops.nDMaterial('PlateRebar',2,2,0)
    ops.nDMaterial('PlateRebar',3,2,90)
    ops.section('LayeredShell',1,3,1,0.098,2,0.001,3,0.001)
    for j in range(3):
        for i in range(3):ops.node(j*3+i+1,i/2,j/2,0)
    for j in range(2):
        for i in range(2):
            n=j*3+i+1;ops.element('ShellMITC4',j*2+i+1,n,n+1,n+4,n+3,1)
    ops.timeSeries('Linear',1);ops.pattern('Plain',1,1)
    for j in range(3):
        for i in range(3):
            node=j*3+i+1
            for dof in range(3,7):ops.sp(node,dof,0)
            if i in (0,2) or j in (0,2):
                ops.sp(node,1,1e-4*i/2);ops.sp(node,2,2e-4*j/2)
    analysis()
    sx=ops.eleResponse(1,'material',1,'fiber',2,'stress')
    sy=ops.eleResponse(1,'material',1,'fiber',3,'stress')
    require(len(sx)==5 and len(sy)==5,(sx,sy))
    require(abs(sx[0]-20e6)<1 and abs(sy[1]-40e6)<1,(sx,sy))
    report=dict(available=True,verified=True,solver=ops.version(),column_fiber_stress=True,
                panel_rebar_stress=True,sparse_solver=True,column_stress_strain=steel,
                panel_0deg_stress=sx,panel_90deg_stress=sy,
                scope='tiny_library_characterization_not_blast_validation')
    ops.wipe()
    return report


if __name__=='__main__':
    report=probe()
    if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))
