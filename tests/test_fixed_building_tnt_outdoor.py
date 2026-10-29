"""The current TNT workspace permits only a complete cylinder outside the building."""
from copy import deepcopy

import pytest

from lsprepost_mcp.architecture.tnt_service import TntService, write_record


@pytest.fixture
def service(tmp_path):
    s = TntService(tmp_path/'tnt')
    try:
        yield s
    finally:
        s.close()


@pytest.mark.parametrize('position', ['inside', 'straddling', 'tangent', 'corner_overlap'])
def test_save_and_estimate_reject_full_cylinder_entering_building(service, position):
    schema = service.schema(); c = deepcopy(schema['defaults']); b = schema['geometry']['building_bounds_m']
    r = c['cylinder']['diameter_m']/2
    x, y = (b[0]+b[3])/2, (b[1]+b[4])/2
    if position == 'straddling': x = b[0]-r/2
    if position == 'tangent': x = b[0]-r
    if position == 'corner_overlap': x, y = b[0]-.6*r, b[1]-.6*r
    c['location']['xy_m'] = [x,y]
    for operation in (service.save, service.estimate):
        with pytest.raises(ValueError, match='建筑外|建筑内部'):
            operation(c)
    assert not service.list_scenes()


def test_mass_input_is_checked_by_resolved_radius_and_corner_gap_remains_valid(service):
    schema=service.schema();c=deepcopy(schema['defaults']);b=schema['geometry']['building_bounds_m']
    c['cylinder']={'mode':'mass','mass_kg':100.,'aspect_ratio':1.}
    c['location']['xy_m']=[b[0]-.01,(b[1]+b[4])/2]
    with pytest.raises(ValueError,match='建筑外|建筑内部'):service.save(c)
    c=deepcopy(schema['defaults']);r=c['cylinder']['diameter_m']/2
    c['location']['xy_m']=[b[0]-.8*r,b[1]-.8*r]
    assert service.estimate(c)['placement']['center_m'][:2]==c['location']['xy_m']


def test_entire_cylinder_above_roof_is_outside_but_vertical_contact_is_rejected(service):
    schema=service.schema();c=deepcopy(schema['defaults']);b=schema['geometry']['building_bounds_m']
    c['location']['xy_m']=[(b[0]+b[3])/2,(b[1]+b[4])/2]
    c['location']['bottom_clearance_m']=b[5]-schema['geometry']['grade_m']+.1
    assert service.estimate(c)['placement']['bounds_m'][2]>b[5]
    c['location']['bottom_clearance_m']=b[5]-schema['geometry']['grade_m']
    with pytest.raises(ValueError,match='建筑外|建筑内部'):service.save(c)


def test_indoor_history_stays_readable_but_cannot_be_resaved_previewed_or_exported(service):
    schema=service.schema();c=deepcopy(schema['defaults']);rid,room=next((k,v) for k,v in schema['rooms'].items() if v['eligible'])
    c['scenario']='indoor';c['location'].update(room_id=rid,xy_m=[(room['bounds_m'][i]+room['bounds_m'][i+3])/2 for i in (0,1)])
    sid='d'*32;record=dict(scene_id=sid,revision=1,config=c,analysis_type='tnt_air_fsi',updated_at='historical')
    path=service.root/'scenes'/(sid+'.json');write_record(path,record);before=path.read_bytes()
    assert service.load(sid)==record
    for operation in (lambda:service.save(c,scene_id=sid,revision=1),lambda:service.preview(sid,1),lambda:service.start_export(sid,1,'old',scope_accepted=True)):
        with pytest.raises(ValueError,match='仅.*室外|仅.*建筑外'):operation()
    with pytest.raises(ValueError,match='历史室内.*只读'):
        service.save(schema['defaults'],scene_id=sid,revision=1)
    assert path.read_bytes()==before
    assert not list((service.root/'jobs').iterdir())
    assert not list((service.root/'exports').iterdir())
    assert not list(service.root.rglob('*.k'))


def test_outdoor_scene_id_cannot_bypass_constraint_through_preview_or_export(service):
    c=service.schema()['defaults'];b=service.schema()['geometry']['building_bounds_m'];c['location']['xy_m']=[(b[0]+b[3])/2,(b[1]+b[4])/2]
    sid='e'*32;record=dict(scene_id=sid,revision=1,config=c,analysis_type='tnt_air_fsi',updated_at='historical')
    path=service.root/'scenes'/(sid+'.json');write_record(path,record);before=path.read_bytes()
    for operation in (lambda:service.preview(sid,1),lambda:service.start_export(sid,1,'old',scope_accepted=True)):
        with pytest.raises(ValueError,match='建筑外|建筑内部'):operation()
    assert path.read_bytes()==before
    assert not list((service.root/'jobs').iterdir())


def test_api_cannot_submit_indoor_or_overlapping_outdoor_config(service):
    from lsprepost_mcp.architecture.tnt_api import handle_tnt_request,PREFIX
    c=service.schema()['defaults'];c['scenario']='indoor';c['location']['room_id']=next(k for k,v in service.schema()['rooms'].items() if v['eligible'])
    assert handle_tnt_request(service,'POST',PREFIX+'scenes/save',{'config':c})[0]==400
    c=service.schema()['defaults'];b=service.schema()['geometry']['building_bounds_m'];c['location']['xy_m']=[(b[0]+b[3])/2,(b[1]+b[4])/2]
    assert handle_tnt_request(service,'POST',PREFIX+'scenes/save',{'config':c})[0]==400
