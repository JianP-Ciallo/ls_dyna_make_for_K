"""Result calculations retain native clocks and reject changed monitor IDs."""
import numpy as np
import pytest
from pathlib import Path
import json
import shutil


def test_pressure_uses_compression_sign_actual_clock_and_reference():
    from lsprepost_mcp.architecture.tnt_results import pressure_history
    t=np.array([0.,2e-6,5e-6,7e-6])
    absolute=np.array([101325.,101425.,101375.,101325.])
    stress=np.repeat((-absolute)[:,None,None],3,axis=2)
    m=dict(id='p',element_id=42,requested_position_m=[1,2,3],sample_position_m=[1.01,2,3])
    r=pressure_history(t,np.array([42]),stress,m,101325.)
    assert r['time_s']==t.tolist()
    assert r['overpressure_pa']==[0.,100.,50.,0.]
    assert r['pressure_kind']=='cell_mean_hydrostatic'
    assert r['peak_overpressure_pa']==100.
    assert r['positive_impulse_pa_s']==pytest.approx(.000375)
    assert r['sample_position_m']==m['sample_position_m']


def test_changed_ids_missing_monitor_and_nonmonotone_clock_are_rejected():
    from lsprepost_mcp.architecture.tnt_results import pressure_history
    m=dict(id='p',element_id=42,sample_position_m=[0,0,0])
    s=np.zeros((2,1,3))
    for clock,ids in [(np.array([0.,1.]),np.array([[42],[43]])),
                      (np.array([0.,1.]),np.array([44])),(np.array([1.,0.]),np.array([42]))]:
        with pytest.raises(ValueError): pressure_history(clock,ids,s,m,101325.)


def test_saved_native_binary_is_read_without_treating_schema_json_as_binout(tmp_path):
    from lsprepost_mcp.architecture.tnt_results import read_native_pressure
    fixture=Path(__file__).parent/'fixtures/fixed_building_tnt'
    metadata=json.loads((fixture/'native-pressure.json').read_text())
    shutil.copyfile(fixture/'binout',tmp_path/'binout')
    (tmp_path/'binout-keys.json').write_text('{"native_schema":true}')
    monitor=dict(id='saved',kind='air_pressure',element_id=metadata['element_id'],sample_position_m=[0,0,0])
    curves=read_native_pressure(tmp_path,[monitor])
    assert curves[0]['time_s']==metadata['time_s']
    assert curves[0]['pressure_pa'][0]==pytest.approx(metadata['initial_pressure_pa'])


@pytest.mark.parametrize('name',['=HYPERLINK("test")','+cmd','-cmd','@SUM(A1)','  =1+1','\t=1'])
def test_result_csv_neutralizes_formula_like_monitor_names(name):
    import csv,io
    from lsprepost_mcp.architecture.tnt_results import curves_csv
    curve=dict(id=name,element_id=1,time_s=[0.],pressure_pa=[101325.],overpressure_pa=[0.],pressure_kind='cell_mean_hydrostatic')
    row=list(csv.reader(io.StringIO(curves_csv([curve]).decode('utf-8-sig'))))[1]
    assert row[0].startswith("'")
