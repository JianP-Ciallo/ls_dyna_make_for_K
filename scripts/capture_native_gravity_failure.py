"""Inspect by default. Explicit --execute consumes one empty output directory."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lsprepost_mcp.architecture.scene_blast.native_failure_capture import prepare_request, validate_request
from lsprepost_mcp.architecture.cpu_response.runtime import run_process
from lsprepost_mcp.architecture.cpu_response.results import json_write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-request', required=True)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    source = Path(args.source_request)
    raw = source.read_bytes()
    request = prepare_request(json.loads(raw)['case'], args.runtime)
    validate_request(request)
    if not args.execute:
        print(json.dumps({k:v for k,v in request.items() if k not in ('case', 'runtime_identity')}, indent=2))
        return
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    json_write(output / 'source-input.json', dict(path=str(source.resolve()), sha256=hashlib.sha256(raw).hexdigest()))
    frozen = output / 'frozen-request.json'
    json_write(frozen, request)
    command = [request['python_executable'], '-m', 'lsprepost_mcp.architecture.scene_blast.native_failure_capture',
               '--input', str(frozen), '--output', str(output / 'worker')]
    json_write(output / 'execution-started.json', dict(command=command, native_worker_launch_count=1,
        started_utc=datetime.now(timezone.utc).isoformat(), budget=request['budget'], policy=request['policy']))
    outcome = run_process(command, timeout_s=180., log_dir=output / 'logs')
    json_write(output / 'process-outcome.json', outcome)
    print(json.dumps(outcome, indent=2))
    if outcome['status'] != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
