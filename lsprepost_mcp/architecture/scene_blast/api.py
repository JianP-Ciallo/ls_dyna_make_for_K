import json
import re

PREFIX='/api/cpu-blast/'


def handle_request(service,method,path,payload=None):
    headers={'Cache-Control':'no-store','Content-Type':'application/json; charset=utf-8','X-Content-Type-Options':'nosniff'}
    head=method=='HEAD';method='GET' if head else method;route=path[len(PREFIX):];status=200
    try:
        if method=='GET' and route=='catalog':body=service.capabilities()
        elif method=='POST' and route=='prepare':body=service.prepare(payload)
        elif method=='POST' and route=='runs':body=service.submit(payload);status=202
        elif method=='GET' and route in {'runs','deleted-runs'}:body={'runs':service.history(include_deleted=route=='deleted-runs')}
        elif m:=re.fullmatch(r'runs/([a-f0-9]{32})(?:/(input|result|gravity|cancel|delete|restore))?',route):
            rid,action=m.groups()
            if method=='GET' and action in {None,'input','result','gravity'}:body={None:service.job,'input':service.input,'result':service.result,'gravity':service.gravity}[action](rid)
            elif method=='POST' and action in {'cancel','delete','restore'}:
                if payload!={}:raise ValueError('操作不接受额外参数')
                body=getattr(service,action)(rid)
            else:status,body=404,dict(error='场景接口或方法不存在')
        else:status,body=404,dict(error='场景接口或方法不存在')
    except FileNotFoundError:status,body=404,dict(error='记录不存在')
    except (ValueError,TypeError,KeyError,OSError) as exc:status,body=400,dict(error=str(exc))
    return status,headers,b'' if head else json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf8')
