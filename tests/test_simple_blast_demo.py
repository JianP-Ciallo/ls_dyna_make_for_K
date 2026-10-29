"""Lightweight demonstration only; never imports a native structural solver."""
from pathlib import Path
import json
import subprocess

from node_runtime import node_executable

ROOT=Path(__file__).parents[1]

def test_simple_demo_geometry_dynamics_and_source_sensitivity():
    result=subprocess.run([str(node_executable()),str(ROOT/'web/tests/blast-demo.runtime.cjs')],cwd=ROOT,
                          capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
    data=json.loads(result.stdout)
    assert data['status']=='passed' and data['checks']==8
    assert data['strong']['broken']>data['weak']['broken'] and data['strong']['broken']>data['far']['broken']


def test_four_added_buildings_are_independent_and_computed():
    result=subprocess.run([str(node_executable()),str(ROOT/'web/tests/blast-buildings.runtime.cjs')],cwd=ROOT,
                          capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
    data=json.loads(result.stdout)
    assert data['status']=='passed' and data['checks']==9
    assert len(data['buildings'])==5 and all(b['broken']>0 for b in data['buildings'])


def test_original_designed_scene_appearance_and_lightweight_dynamics():
    result=subprocess.run([str(node_executable()),str(ROOT/'web/tests/original-scenes.runtime.cjs')],cwd=ROOT,
                          capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
    data=json.loads(result.stdout)
    assert data['status']=='passed' and data['checks']==12
    assert {s['id'] for s in data['scenes']}=={'commercial_supermarket','residential_community','subway_entrance','city_street'}
