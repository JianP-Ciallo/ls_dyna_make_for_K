"""Closed path-based CPU API. Existing local-origin checks remain in Web App."""
import json
import re
from .contracts import closed
from .service import CpuConflict

PREFIX='/api/architecture/pressure/cpu-response/'


def handle_cpu_response_request(service,method,path,payload=None):
    headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Type':'application/json; charset=utf-8'}
    head=method=='HEAD';method='GET' if head else method
    status=200;body=None
    try:
        relative=path[len(PREFIX):] if path.startswith(PREFIX) else ''
        if method=='GET' and relative=='capabilities':body=service.capabilities()
        elif method=='GET' and relative=='benchmarks':body=dict(benchmarks=service.benchmarks())
        elif method=='GET' and relative=='building-trial':body=service.building_trial()
        elif method=='GET' and (match:=re.fullmatch(r'building-trial/artifacts/(result\.json|curves\.csv|report\.md|deformation-and-steel\.png|response-curves\.png)',relative)):
            name=match[1];raw,mime=service.saved_building.artifact(name);headers['Content-Type']=mime
            if mime!='image/png':headers['Content-Disposition']=f'attachment; filename="building-trial-{name}"'
            return 200,headers,b'' if head else raw
        elif method=='POST' and relative=='profiles':body=service.create_profile(payload)
        elif method=='POST' and relative=='preflight':
            closed(payload,('source','profile_id'),'preflight');body=service.preflight(**payload)
        elif method=='POST' and relative=='runs':
            closed(payload,('source','profile_id','input_fingerprint','client_request_id'),'run');body=service.start_run(**payload);status=202
        elif method=='GET' and (match:=re.fullmatch(r'profiles/([a-f0-9]{32})',relative)):
            body=service.get_profile(match[1])
        elif method=='GET' and (match:=re.fullmatch(r'sources/(benchmark)/([a-z0-9-]{1,64})/(runs|deleted-runs)',relative)):
            kind,source,listing=match.groups();body=dict(runs=service.history(kind,source,deleted=listing=='deleted-runs'))
        elif match:=re.fullmatch(r'runs/([a-f0-9]{32})(?:/(results|cancel|delete|restore|artifacts/(result\.json|curves\.csv)))?',relative):
            rid,action,name=match.groups()
            if method=='GET' and action is None:body=service.get_run(rid)
            elif method=='GET' and action=='results':body=service.get_results(rid)
            elif method=='POST' and action=='cancel':
                closed(payload,(),'cancel');body=service.cancel(rid)
            elif method=='POST' and action in ('delete','restore'):
                closed(payload,(),action);body=(service.delete_run if action=='delete' else service.restore_run)(rid)
            elif method=='GET' and name:
                service.get_results(rid)
                raw=(service.root/'runs'/rid/name).read_bytes()
                headers['Content-Type']='application/json; charset=utf-8' if name.endswith('.json') else 'text/csv; charset=utf-8'
                headers['Content-Disposition']=f'attachment; filename="{name}"'
                return 200,headers,b'' if head else raw
            else:status,body=404,dict(error='unknown CPU route or method')
        else:status,body=404,dict(error='unknown CPU route or ID')
    except CpuConflict as exc:status,body=409,dict(error=str(exc))
    except FileNotFoundError:status,body=404,dict(error='CPU record not found')
    except (ValueError,TypeError,KeyError,OSError) as exc:status,body=400,dict(error=str(exc))
    return status,headers,b'' if head else json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf8')
