"""Build an isolated Windows runtime from a checked CPython ZIP and wheelhouse.

No system installation is modified. Dependency versions are taken from the
project lock; pip runs offline against the supplied wheels.
"""
from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): digest.update(chunk)
    return digest.hexdigest()


def key(name: str) -> str:
    return name.lower().replace('_','-').replace('.','-')


def checked_archive(archive: zipfile.ZipFile) -> None:
    for info in archive.infolist():
        path = PurePosixPath(info.filename.replace('\\','/'))
        if path.is_absolute() or '..' in path.parts or ':' in info.filename:
            raise ValueError('unsafe archive path')
        if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
            raise ValueError('archive links are not supported')


def verify_runtime(target: Path, source: dict) -> dict:
    python_dir = target/'python'
    # CPython's Windows _pth reader requires Windows separators when collapsing
    # consecutive parent segments. Forward-slash ../.. resolves only one level.
    (python_dir/'python313._pth').write_text('python313.zip\n.\nLib\\site-packages\n..\\..\n',encoding='ascii')
    probe = """import io,json,sys,numpy,scipy,pandas,h5py,sklearn
from PIL import Image
from lasso.dyna import D3plot
from blast_damage_assessment.api import capabilities
buffer=io.BytesIO()
Image.new('RGB',(2,2),(12,34,56)).save(buffer,format='PNG')
buffer.seek(0)
assert Image.open(buffer).getpixel((0,0)) == (12,34,56)
print(json.dumps({'python':sys.version.split()[0],'isolated':sys.flags.isolated,'paths':sys.path,'assessment':capabilities()['dependencies']}))
"""
    env = os.environ.copy(); env.update(PYTHONHOME='invalid-host-home',PYTHONPATH='invalid-host-site')
    result = subprocess.run([str(python_dir/'python.exe'),'-B','-X','utf8','-c',probe],
                            env=env,capture_output=True,text=True,encoding='utf8',timeout=60)
    if result.returncode: raise RuntimeError(result.stdout+result.stderr)
    verification = json.loads(result.stdout)
    if verification['python'] != source['version'] or verification['isolated'] != 1:
        raise ValueError('Unexpected embedded Python identity')
    paths = [Path(p).resolve() for p in verification['paths']]
    if target.parent.resolve() not in paths:
        raise ValueError('Embedded Python cannot import the application from the package root')
    if any(not p.is_relative_to(target.parent.resolve()) for p in paths):
        raise ValueError('Embedded Python used an external search path')
    return verification


def write_manifest(target: Path, source: dict, available: dict, removed_wrappers: list) -> dict:
    files = {p.relative_to(target).as_posix():sha(p) for p in sorted(target.rglob('*'))
             if p.is_file() and p != target/'runtime-manifest.json'}
    manifest = dict(schema_version='portable.runtime@1',platform='win_amd64',python=source,
                    packages=available,files=files,isolated=True,removed_console_wrapper_dirs=removed_wrappers)
    (target/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-archive',type=Path,required=True)
    parser.add_argument('--wheelhouse',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True,help='New directory containing python/ and the manifest')
    parser.add_argument('--work-dir',type=Path,required=True,help='New build-only scratch directory')
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.maxsize <= 2**32:
        parser.error('Build on 64-bit Windows using Python 3.13')
    if sys.version_info[:2] != (3,13): parser.error('The pinned wheelhouse requires CPython 3.13')
    target = args.destination.resolve(); work = args.work_dir.resolve()
    if target.exists() or work.exists(): parser.error('Refusing to reuse a runtime or build scratch directory')
    if target == work or target.is_relative_to(work) or work.is_relative_to(target):
        parser.error('Runtime and scratch directories must be separate')
    source = json.loads((ROOT/'resources/runtime/windows-amd64-python.json').read_text(encoding='utf8'))
    if sha(args.python_archive) != source['sha256']: raise ValueError('CPython ZIP checksum mismatch')
    expected = {}
    for line in (ROOT/'resources/runtime/windows-amd64-requirements.txt').read_text().splitlines():
        if line and not line.startswith('#'):
            name, version = line.split('=='); expected[key(name)] = version
    wheels = args.wheelhouse.resolve()
    available = {}
    for path in wheels.glob('*.whl'):
        with zipfile.ZipFile(path) as z:
            checked_archive(z)
            metadata_names = [name for name in z.namelist() if name.endswith('.dist-info/METADATA')]
            if len(metadata_names) != 1: raise ValueError('wheel metadata missing')
            metadata = BytesParser().parsebytes(z.read(metadata_names[0]))
            name = key(metadata['Name']); version = metadata['Version']
        if name in expected:
            if version != expected[name] or name in available: raise ValueError('wheel version conflict: '+name)
            available[name] = dict(version=version,file=path.name,sha256=sha(path))
    if set(available) != set(expected): raise ValueError('Missing pinned wheels: '+str(set(expected)-set(available)))
    work.mkdir(parents=True)
    build_temp = work/'pip-temp'; build_temp.mkdir()
    build_env = os.environ.copy()
    build_env.update(TEMP=str(build_temp),TMP=str(build_temp),PYTHONDONTWRITEBYTECODE='1')
    assessment_source = work/'assessment-source'
    shutil.copytree(ROOT/'packages/blast_damage_assessment',assessment_source,
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.egg-info','build','dist'))
    local_wheels = work/'local-wheels'; local_wheels.mkdir()
    subprocess.run([sys.executable,'-B','-m','pip','wheel','--disable-pip-version-check','--no-cache-dir',
                    '--no-deps','--no-build-isolation','--wheel-dir',str(local_wheels),str(assessment_source)],
                   env=build_env,check=True)
    local = list(local_wheels.glob('blast_damage_assessment-*.whl'))
    if len(local) != 1: raise ValueError('Local assessment wheel missing')
    with zipfile.ZipFile(local[0]) as z:
        metadata_name = next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))
        local_version = BytesParser().parsebytes(z.read(metadata_name))['Version']
    available['blast-damage-assessment'] = dict(version=local_version,file=local[0].name,sha256=sha(local[0]))
    frozen = work/'offline-requirements.txt'
    frozen.write_text('\n'.join(f"{name}=={item['version']} --hash=sha256:{item['sha256']}"
                               for name,item in sorted(available.items()))+'\n',encoding='utf8')
    python_dir = target/'python'; python_dir.mkdir(parents=True)
    with zipfile.ZipFile(args.python_archive) as z:
        checked_archive(z); z.extractall(python_dir)
    site = python_dir/'Lib/site-packages'
    subprocess.run([sys.executable,'-B','-m','pip','install','--disable-pip-version-check','--no-cache-dir',
                    '--no-index','--find-links',str(wheels),'--find-links',str(local_wheels),
                    '--only-binary=:all:','--ignore-installed','--require-hashes','--no-compile',
                    '--no-warn-script-location','--target',str(site),'-r',str(frozen)],env=build_env,check=True)
    # pip's optional console wrappers contain the build interpreter's absolute
    # path. The application calls modules explicitly through its bundled Python.
    removed_wrappers = []
    for name in ('bin','Scripts'):
        scripts = site/name
        if scripts.exists():
            resolved = scripts.resolve()
            if not resolved.is_relative_to(site.resolve()) or scripts.is_symlink() or scripts.is_junction():
                raise ValueError('unsafe generated wrapper path')
            removed_wrappers.append(name); shutil.rmtree(resolved)
    for path in site.glob('*.dist-info/direct_url.json'):
        path.unlink()
    for path in site.glob('*.pth'):
        raise ValueError('Unexpected startup hook in pinned wheels: '+path.name)
    verification = verify_runtime(target, source)
    manifest = write_manifest(target, source, available, removed_wrappers)
    print(json.dumps(dict(status='prepared',target=str(target),python=verification['python'],
                         packages=len(available),files=len(manifest['files']),isolated=True)))
    return 0


if __name__ == '__main__': raise SystemExit(main())
