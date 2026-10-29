"""Closed HTTP adapter for TNT scenes; no solver endpoint."""
import re

PREFIX = '/api/architecture/tnt/'


def fields(payload, allowed, required):
    if not isinstance(payload, dict) or set(payload)-set(allowed) or set(required)-set(payload):
        raise ValueError('未知或缺失字段')


def handle_tnt_request(service, method, path, payload=None):
    try:
        if method=='GET' and path==PREFIX+'schema': return 200, service.schema()
        if method=='GET' and path==PREFIX+'scenes': return 200, dict(scenes=service.list_scenes())
        if method=='POST' and path==PREFIX+'scenes/save':
            fields(payload,('config','scene_id','revision'),('config',))
            return 200,service.save(payload['config'],scene_id=payload.get('scene_id'),revision=payload.get('revision'))
        match=re.fullmatch(re.escape(PREFIX)+r'scenes/([a-f0-9]{32})(?:/(preview|exports))?',path)
        if match:
            sid, action=match.groups()
            if method=='GET' and action is None:return 200,service.load(sid)
            if method=='GET' and action=='exports':return 200,dict(exports=service.list_exports(sid))
            if method=='POST' and action=='preview':
                fields(payload,('revision',),('revision',));return 200,service.preview(sid,payload['revision'])
            if method=='POST' and action=='exports':
                fields(payload,('revision','scene_fingerprint','scope_accepted'),('revision','scene_fingerprint','scope_accepted'))
                return 202,service.start_export(sid,payload['revision'],payload['scene_fingerprint'],scope_accepted=payload['scope_accepted'])
        match=re.fullmatch(re.escape(PREFIX)+r'exports/([a-f0-9]{32})(/download)?',path)
        if method=='GET' and match:
            jid,download=match.groups();return 200,service.download(jid) if download else service.export_status(jid)
        match=re.fullmatch(re.escape(PREFIX)+r'exports/([a-f0-9]{32})/results(?:/(select|csv))?',path)
        if match:
            jid,action=match.groups()
            if method=='GET' and action is None:return 200,service.results(jid)
            if method=='GET' and action=='csv':
                from .tnt_results import curves_csv
                return 200,curves_csv(service.results(jid)['curves'])
            if method=='POST' and action=='select':
                fields(payload,(),())
                from .tnt_results import choose_result_directory
                folder=choose_result_directory()
                return 200,service.attach_results(jid,folder) if folder else dict(status='cancelled',curves=[])
        return 404,dict(error='未知TNT接口或ID')
    except FileNotFoundError:return 404,dict(error='工况、资源或导出任务不存在')
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        return (409 if '版本' in str(exc) or '过期' in str(exc) else 400),dict(error=str(exc))
