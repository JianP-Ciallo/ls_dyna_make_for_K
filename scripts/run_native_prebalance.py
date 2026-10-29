"""Inspect by default. --execute launches ONE isolated gravity-only process.

Real-building --execute requires current explicit user approval under AGENTS.md.
No production service, case retry, batch enumeration or TNT operation.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lsprepost_mcp.architecture.scene_blast.native_prebalance import validate_request
from lsprepost_mcp.architecture.cpu_response.runtime import run_process
from lsprepost_mcp.architecture.cpu_response.results import json_write


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    request=validate_request(json.loads(Path(args.request).read_text(encoding='utf8')))
    if not args.execute:
        print(json.dumps(dict(status='not_run',scope=request['preflight'],budget=request['budget'],
            case_fingerprint=request['case_fingerprint'],method_fingerprint=request['method_fingerprint']),ensure_ascii=False,indent=2));return
    output=Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):raise ValueError('输出目录必须为空，不能覆盖已有证据')
    output.mkdir(parents=True,exist_ok=True);source=output/'frozen-request.json';json_write(source,request)
    command=[request['python_executable'],'-m','lsprepost_mcp.architecture.scene_blast.native_prebalance',
        '--input',str(source),'--output',str(output/'worker')]
    outcome=run_process(command,timeout_s=request['budget']['parent_timeout_s'],log_dir=output/'logs')
    json_write(output/'process-outcome.json',outcome)
    print(json.dumps(outcome,ensure_ascii=False,indent=2))
    if outcome['status']!='completed':raise SystemExit(1)


if __name__=='__main__':main()
