"""Sealed portable TNT template; ordinary reads inspect metadata only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from uuid import uuid4
import zipfile

from .tnt_native.architecture_blast_contracts import fingerprint

RESOURCE = Path(__file__).resolve().parents[2] / 'resources' / 'fixed_building_tnt' / 'template.zip'
INDEX = 'blast-template.json'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


class TntResource:
    def __init__(self, archive=None):
        self.archive = Path(archive or RESOURCE).resolve()
        with zipfile.ZipFile(self.archive) as z:
            infos = z.infolist()
            if len(infos) != 17 or len({i.filename for i in infos}) != 17:
                raise ValueError('TNT模板文件清单不匹配')
            if any(i.is_dir() or Path(i.filename).name != i.filename or '/' in i.filename or '\\' in i.filename
                   or i.file_size > 65_000_000 or (i.external_attr >> 16) & 0o170000 == 0o120000 for i in infos):
                raise ValueError('TNT模板包含不安全文件')
            if sum(i.file_size for i in infos) > 220_000_000 or z.getinfo(INDEX).file_size > 16_000_000:
                raise ValueError('TNT模板超过资源预算')
            self.sealed = json.loads(z.read(INDEX))
            p = self.sealed['payload']
            if set(z.namelist()) != set(p['files']) | {INDEX} or len(p['files']) != 16:
                raise ValueError('TNT模板包含缺失或额外文件')
            if p['schema_version'] != 'architecture.blast-template@1' or fingerprint(p) != self.sealed['template_fingerprint']:
                raise ValueError('TNT模板元数据校验失败')
        self.archive_sha256 = digest(self.archive)
        if archive is None:
            descriptor = json.loads((RESOURCE.parent / 'resource.json').read_text(encoding='utf8'))
            structure = json.loads((RESOURCE.parent.parent / 'fixed_building_pressure' / 'resource.json').read_text(encoding='utf8'))
            if descriptor['archive_sha256'] != self.archive_sha256 or any(p['files'].get(n) != sha for n, sha in structure['files'].items()):
                raise ValueError('TNT模板与当前建筑结构资源不一致')
        self.payload = deepcopy(p)

    def verify(self):
        if digest(self.archive) != self.archive_sha256:
            raise ValueError('TNT模板资源已变化，请重新载入')

    def metadata(self):
        m = deepcopy(self.payload['metadata'])
        m.update(template_id=self.sealed['template_id'], template_fingerprint=self.sealed['template_fingerprint'])
        return m

    def unpack(self, parent):
        """Only explicit K generation calls this; never invoked by schema/save/preview."""
        self.verify()
        parent = Path(parent).resolve(); parent.mkdir(parents=True, exist_ok=True)
        target = parent / self.sealed['template_fingerprint']
        if target.is_symlink():
            raise ValueError('TNT模板缓存不能是符号链接')
        if not target.exists():
            stage = parent / ('.stage-' + uuid4().hex); stage.mkdir()
            try:
                with zipfile.ZipFile(self.archive) as z:
                    for name in [*self.payload['files'], INDEX]:
                        with z.open(name) as source, (stage / name).open('xb') as output:
                            shutil.copyfileobj(source, output, length=1024 * 1024)
                for name, sha in self.payload['files'].items():
                    if digest(stage / name) != sha:
                        raise ValueError('TNT模板K文件校验失败：' + name)
                stage.rename(target)
            finally:
                if stage.exists() and not stage.is_symlink() and stage.resolve().parent == parent:
                    shutil.rmtree(stage)
        for name, sha in self.payload['files'].items():
            if (target / name).is_symlink() or digest(target / name) != sha:
                raise ValueError('TNT模板缓存校验失败：' + name)
        return target
