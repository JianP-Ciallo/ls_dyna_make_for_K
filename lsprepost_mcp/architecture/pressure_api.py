"""Local HTTP adapter for supplied structural pressure, without filesystem inputs."""
import re

PREFIX = '/api/architecture/pressure/'


def fields(payload, allowed, required):
    if not isinstance(payload, dict) or set(payload)-set(allowed) or set(required)-set(payload):
        raise ValueError('unknown or missing request fields')


def handle_pressure_request(service, method, path, payload=None):
    if service is None: return 503, dict(error='固定结构模板未配置，请设置 pressure-template-dir 后重启服务')
    from .pressure_service import PressureConflict
    try:
        if method == 'GET' and path == PREFIX+'schema': return 200, service.schema()
        if method == 'GET' and path == PREFIX+'preview-scene': return 200, service.template.preview_scene()
        if method == 'GET' and path == PREFIX+'scenes': return 200, dict(scenes=service.list_scenes())
        if method == 'POST' and path == PREFIX+'scenes/save':
            fields(payload, ('config','scene_id','revision'), ('config',))
            return 200, service.save(payload['config'], scene_id=payload.get('scene_id'), revision=payload.get('revision'))
        match = re.fullmatch(re.escape(PREFIX)+r'scenes/([a-f0-9]{32})(?:/(preview|exports))?', path)
        if match:
            sid, action = match.groups()
            if method == 'GET' and action is None: return 200, service.load(sid)
            if method == 'POST' and action == 'preview':
                fields(payload, ('revision',), ('revision',)); return 200, service.preview(sid, payload['revision'])
            if method == 'POST' and action == 'exports':
                fields(payload, ('revision','scene_fingerprint'), ('revision','scene_fingerprint'))
                return 202, service.start_export(sid, payload['revision'], payload['scene_fingerprint'])
        match = re.fullmatch(re.escape(PREFIX)+r'exports/([a-f0-9]{32})(/download)?', path)
        if method == 'GET' and match:
            jid, download = match.groups()
            return 200, service.download(jid) if download else service.export_status(jid)
        return 404, dict(error='unknown pressure route or ID')
    except PressureConflict as exc: return 409, dict(error=str(exc))
    except FileNotFoundError: return 404, dict(error='工况或导出任务不存在')
    except (ValueError, TypeError, KeyError) as exc: return 400, dict(error=str(exc))
