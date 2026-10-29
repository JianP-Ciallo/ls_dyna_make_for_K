"""Install/verify the optional Windows CPU runtime without modifying host Python."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lsprepost_mcp.architecture.cpu_response.runtime import DEFAULT_PYTHON,inspect_runtime,run_process,runtime_identity
from lsprepost_mcp.architecture.cpu_response.results import json_write

PYTHON_URL='https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'
PYTHON_SHA256='4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--install',action='store_true',help='explicit official download and locked wheel install')
    action.add_argument('--verify-only',action='store_true',help='two tiny probes; no install or model generation')
    args=parser.parse_args()
    root=DEFAULT_PYTHON.parent
    if args.install:
        if sys.platform!='win32':parser.error('this locked runtime is Windows x64 only')
        root.mkdir(parents=True,exist_ok=True)
        if not DEFAULT_PYTHON.is_file():
            archive=root/'python-3.12.10-embed-amd64.zip'
            urllib.request.urlretrieve(PYTHON_URL,archive)
            if hashlib.sha256(archive.read_bytes()).hexdigest()!=PYTHON_SHA256:raise ValueError('official Python archive SHA256 mismatch')
            with zipfile.ZipFile(archive) as bundle:
                for name in bundle.namelist():
                    if not (root/name).resolve().is_relative_to(root.resolve()):raise ValueError('archive path escapes runtime')
                bundle.extractall(root)
            json_write(root/'python-source.json',dict(url=PYTHON_URL,sha256=PYTHON_SHA256))
        # The embedded distribution intentionally has no pip. Host pip targets only
        # this installation, requests Python 3.12 wheels and checks the pinned hashes.
        requirements=ROOT/'lsprepost_mcp/architecture/cpu_response/requirements-win-py312.txt'
        command=[sys.executable,'-m','pip','install','--target',str(root/'Lib/site-packages'),
                 '--python-version','3.12','--only-binary=:all:','--no-compile','--require-hashes',
                 '--report',str(root/'pip-install-report.json'),'-r',str(requirements)]
        subprocess.run(command,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (root/'python312._pth').write_text('python312.zip\n.\nLib/site-packages\n'+str(ROOT)+'\nimport site\n',encoding='utf8')
    if root.is_dir():json_write(root/'capabilities.json',dict(available=False,verified=False,reason='explicit runtime verification in progress or failed'))
    info=inspect_runtime(str(DEFAULT_PYTHON))
    if not info['available']:raise RuntimeError(info['reason'])
    if info['python'].split()[0]!='3.12.10' or info['package']!='3.8.0.0':raise RuntimeError('runtime versions differ from the verified Python/OpenSees lock')
    target=root/'capabilities-probe.json'
    outcome=run_process([str(DEFAULT_PYTHON),'-m','lsprepost_mcp.architecture.cpu_response.native_probes',str(target)],timeout_s=30,log_dir=root/'probe-log')
    if outcome['status']!='completed':raise RuntimeError('native probe failed; inspect .venv/cpu-response/probe-log')
    probe=json.loads(target.read_text(encoding='utf8'))
    if not probe.get('verified'):raise RuntimeError('native responses not verified')
    json_write(root/'capabilities.json',dict(probe,runtime=info,runtime_identity=runtime_identity(DEFAULT_PYTHON),probe_process=outcome))
    print(json.dumps(dict(verified=True,python=info['python'].split()[0],solver=info['solver'],executable=str(DEFAULT_PYTHON))))
    return 0


if __name__=='__main__':raise SystemExit(main())
