"""Explicit tiny native probes; not collected by pytest. Production implementation."""
import json
from pathlib import Path
import sys
from lsprepost_mcp.architecture.cpu_response.runtime import probe_backend

if __name__=='__main__':
    report=probe_backend()
    if not report.get('verified'):raise RuntimeError(report.get('reason','unverified native core'))
    if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))
