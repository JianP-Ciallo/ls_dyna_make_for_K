"""Closed scene inputs for the retained fixed-building template (SI units)."""
from copy import deepcopy
import hashlib
import json
import math

SCHEMA = 'architecture.fixed-building-blast@1'
CONTROL_RANGES = {'termination_s': (.1, .3), 'plot_interval_s': (.0005, .001),
                  'history_interval_s': (.00001, .00005)}
CONTROL_DEFAULTS = {'termination_s': .1, 'plot_interval_s': .001, 'history_interval_s': .00002}
MARGIN_KEYS = ('xmin', 'xmax', 'ymin', 'ymax', 'top')
MONITOR_KINDS = ('air_pressure', 'structure_node', 'ground_node', 'solid_stress')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode('utf8')).hexdigest()


def _closed(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f'{name}: unknown or missing fields')


def _number(value, name, low=0., high=math.inf, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{name}: finite numeric required')
    if not low <= value <= high or (positive and value <= 0):
        raise ValueError(f'{name}: value outside permitted range')
    return float(value)


def _vector(value, count, name):
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise ValueError(f'{name}: expected {count} coordinates')
    return [_number(v, name, -math.inf) for v in value]


def default_blast_config(template_metadata: dict) -> dict:
    m = template_metadata
    return dict(schema_version=SCHEMA, template_id=m['template_id'],
                template_fingerprint=m['template_fingerprint'], name='参考工况', notes='',
                scenario='outdoor', location=dict(room_id=None, xy_m=list(m['default_location_xy_m']),
                                                   bottom_clearance_m=.5),
                cylinder=dict(mode='dimensions', diameter_m=.1, height_m=.2),
                detonation_time_s=0., opening_states={}, mesh=deepcopy(m['default_mesh']),
                controls=deepcopy(CONTROL_DEFAULTS), monitors=[])


def resolve_blast_cylinder(cylinder: dict, density: float) -> dict:
    density = _number(density, 'density', positive=True)
    if not isinstance(cylinder, dict):
        raise ValueError('cylinder: object required')
    if cylinder.get('mode') == 'dimensions':
        _closed(cylinder, ('mode', 'diameter_m', 'height_m'), 'cylinder')
        diameter = _number(cylinder['diameter_m'], 'diameter_m', positive=True)
        height = _number(cylinder['height_m'], 'height_m', positive=True)
    elif cylinder.get('mode') == 'mass':
        _closed(cylinder, ('mode', 'mass_kg', 'aspect_ratio'), 'cylinder')
        mass = _number(cylinder['mass_kg'], 'mass_kg', positive=True)
        ratio = _number(cylinder['aspect_ratio'], 'aspect_ratio', positive=True)
        diameter = (4 * mass / (density * math.pi * ratio)) ** (1/3)
        height = diameter * ratio
    else:
        raise ValueError('cylinder: unknown input mode')
    try:
        volume = math.pi * (diameter/2)**2 * height
        mass = density * volume
    except OverflowError as exc:
        raise ValueError('cylinder: numerical overflow') from exc
    if not all(math.isfinite(v) and v > 0 for v in (diameter, height, volume, mass)):
        raise ValueError('cylinder: unrepresentable dimensions or mass')
    return dict(diameter_m=diameter, height_m=height, volume_m3=volume, mass_kg=mass)


def normalize_blast_config(config: dict, template_metadata: dict) -> dict:
    m = template_metadata
    _closed(config, default_blast_config(m), 'scene')
    c = deepcopy(config)
    for key, expected in [('schema_version', SCHEMA), ('template_id', m['template_id']),
                          ('template_fingerprint', m['template_fingerprint'])]:
        if c[key] != expected:
            raise ValueError(key+': template/schema mismatch')
    for field, maximum in [('name', 120), ('notes', 4000)]:
        if not isinstance(c[field], str) or len(c[field]) > maximum or (field == 'name' and not c[field].strip()):
            raise ValueError(field+': invalid text')
    if c['scenario'] not in ('indoor', 'outdoor'):
        raise ValueError('scenario: indoor or outdoor required')
    location = c['location']
    _closed(location, ('room_id', 'xy_m', 'bottom_clearance_m'), 'location')
    location['xy_m'] = _vector(location['xy_m'], 2, 'xy_m')
    location['bottom_clearance_m'] = _number(location['bottom_clearance_m'], 'bottom_clearance_m')
    room_id = location['room_id']
    if c['scenario'] == 'outdoor':
        if room_id is not None:
            raise ValueError('outdoor location: room_id must be null')
    elif not isinstance(room_id, str) or not m['rooms'].get(room_id, {}).get('eligible', False):
        raise ValueError('room_id: unsupported indoor room')
    resolve_blast_cylinder(c['cylinder'], m['tnt_density_kg_m3'])
    # Normalize numeric representation so save/load produces a stable fingerprint.
    for key in c['cylinder']:
        if key != 'mode':
            c['cylinder'][key] = float(c['cylinder'][key])
    controls = c['controls']
    _closed(controls, CONTROL_RANGES, 'controls')
    for field, (low, high) in CONTROL_RANGES.items():
        controls[field] = _number(controls[field], field, low, high)
    c['detonation_time_s'] = _number(c['detonation_time_s'], 'detonation_time_s')
    if c['detonation_time_s'] >= controls['termination_s']:
        raise ValueError('detonation_time_s must precede termination_s')
    mesh = c['mesh']
    _closed(mesh, ('margins_m', 'background_cell_m', 'charge_cell_m', 'room_cell_m', 'opening_cell_m'), 'mesh')
    _closed(mesh['margins_m'], MARGIN_KEYS, 'margins_m')
    for field in MARGIN_KEYS:
        mesh['margins_m'][field] = _number(mesh['margins_m'][field], 'margins_m.'+field, positive=True)
    for field in mesh:
        if field != 'margins_m':
            mesh[field] = _number(mesh[field], field, positive=True)
    states = c['opening_states']
    if not isinstance(states, dict) or len(states) > 2048:
        raise ValueError('opening_states: invalid object')
    for key, state in states.items():
        if not isinstance(key, str):
            raise ValueError('opening_states: string ID required')
        if key in m['door_leaves']:
            allowed = ('keep', 'closed') if m['door_leaves'][key].get('elevator') else ('keep', 'closed', 'open_90')
        elif m['openings'].get(key, {}).get('kind') == 'window':
            allowed = ('keep_glass', 'clear_opening')
        else:
            raise ValueError('opening_states: unknown or unsupported ID '+key)
        if not isinstance(state, str) or state not in allowed:
            raise ValueError('opening_states: unsupported state for '+key)
    if not isinstance(c['monitors'], list) or len(c['monitors']) > 128:
        raise ValueError('monitors: list of at most 128 points required')
    seen = set()
    for monitor in c['monitors']:
        _closed(monitor, ('id', 'kind', 'position_m'), 'monitor')
        key = monitor['id']
        if not isinstance(key, str) or not key.strip() or len(key)>120 or key in seen:
            raise ValueError('monitor: invalid or duplicate ID')
        seen.add(key)
        if monitor['kind'] not in MONITOR_KINDS:
            raise ValueError('monitor: unknown kind')
        monitor['position_m'] = _vector(monitor['position_m'], 3, 'monitor.position_m')
    return c


def blast_config_fingerprint(config: dict) -> str:
    return fingerprint(config)


def build_blast_schema(template_metadata: dict) -> dict:
    return dict(schema_version=SCHEMA, units=dict(length='m', time='s', mass='kg', pressure='Pa'),
                defaults=default_blast_config(template_metadata), control_ranges=deepcopy(CONTROL_RANGES),
                monitor_kinds=list(MONITOR_KINDS), rooms=deepcopy(template_metadata['rooms']),
                openings=deepcopy(template_metadata['openings']), door_leaves=deepcopy(template_metadata['door_leaves']),
                door_labels=dict(closed='初始关闭（未锁闭）', open_90='初始打开（可转动）'),
                window_labels=dict(clear_opening='净开口（移除玻璃，保留窗框）'),
                limits=dict(air_elements=200000, air_nodes=250000, native_id=99999999),
                timestep_scale=.67, engineering_validated=False)
