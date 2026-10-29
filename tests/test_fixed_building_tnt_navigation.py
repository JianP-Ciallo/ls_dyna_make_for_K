"""TNT identities survive navigation without entering the shared scene_id field."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_tnt_query_has_its_own_persisted_navigation_identity():
    node=shutil.which('node')
    if not node:pytest.skip('Node runtime unavailable')
    source=Path(__file__).parents[1]/'lsprepost_mcp/web/static/workbench_session.js'
    script="""
const assert=require('node:assert/strict');
const S=require(process.argv[1]),id='a'.repeat(32);
assert.equal(S.canonicalUrl('pressure','/structural-pressure?tnt_scene_id='+id),'/structural-pressure?tnt_scene_id='+id);
assert.equal(new URL(S.canonicalUrl('pressure','/structural-pressure?tnt_scene_id='+id),'http://local').searchParams.get('scene_id'),null);
assert.equal(S.canonicalUrl('pressure','/structural-pressure?scene_id='+id),'/structural-pressure?scene_id='+id);
"""
    r=subprocess.run([node,'-e',script,str(source)],capture_output=True,text=True,timeout=15)
    assert r.returncode==0,r.stderr
