"""Verify native sources and prepare a regularized reference. Starts no solver."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lsprepost_mcp.architecture.cpu_response.building_source import audit_archive
from lsprepost_mcp.architecture.cpu_response.building_mapping import prepare_reference
from lsprepost_mcp.architecture.cpu_response.building_solver import validate_reference
from lsprepost_mcp.architecture.cpu_response.contracts import fingerprint
from lsprepost_mcp.architecture.cpu_response.results import json_write


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def material_label_conflicts(audit):
    materials={str(k):v for k,v in audit['materials'].items()}
    return [dict(component_id=k,semantic_material=c['material'],native_material_id=c['material_id'],native_density=c['host_density_kg_m3'])
        for k,c in audit['components'].items() if c['material']!='concrete' and 'CONCRETE' in materials[str(c['material_id'])]['model']]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--archive',type=Path,default=ROOT/'resources/fixed_building_pressure/three-storey-structural.zip')
    p.add_argument('--audit-cache',type=Path);p.add_argument('--target',default='F0.west.front.0')
    p.add_argument('--mesh-size-m',type=float,default=2.5);p.add_argument('--column-segments',type=int,choices=(2,4,8),default=4)
    args=p.parse_args();dest=args.output_dir.resolve();dest.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    archive_sha=sha(args.archive)
    with zipfile.ZipFile(args.archive) as z:sealed=json.loads(z.read('structural-template.json'))
    if args.audit_cache:
        manifest=json.loads(args.audit_cache.with_suffix('.manifest.json').read_text(encoding='utf8'))
        if manifest!={'archive_sha256':archive_sha,'audit_sha256':sha(args.audit_cache)}:raise ValueError('audit cache checksum mismatch')
        audit=json.loads(args.audit_cache.read_text(encoding='utf8'));shutil.copyfile(args.audit_cache,dest/'native-audit.json')
    else:
        audit=audit_archive(args.archive);json_write(dest/'native-audit.json',audit)
    json_write(dest/'native-audit.manifest.json',dict(archive_sha256=archive_sha,audit_sha256=sha(dest/'native-audit.json')))
    case=validate_reference(prepare_reference(audit,sealed,target_component_id=args.target,mesh_size_m=args.mesh_size_m,column_segments=args.column_segments))
    json_write(dest/'reference-case.json',case);json_write(dest/'sealed-template.json',sealed)
    cs=audit['components'];ledger=case['mass_ledger'];elements=case['elements'];m=ledger['total_kg'];fixed=ledger['fixed_mass_kg']
    conflicts=material_label_conflicts(audit)
    summary=dict(schema_version='cpu-response.building-preflight@1',status='prepared_not_solved',archive_sha256=archive_sha,
        template_fingerprint=case['template_fingerprint'],input_fingerprint=fingerprint(case),checks=case['checks'],
        structural_nodes=len(case['nodes']),fixed_nodes=len(case['fixed_nodes']),column_elements=sum(e['kind']=='column' for e in elements),
        shell_elements=sum(e['kind']=='panel' for e in elements),mass_points=len(case['mass_points']),column_section_profiles=len(case['column_sections']),
        mass_kg=m,fixed_mass_kg=fixed,dynamic_mass_kg=m-fixed,mass_ledger=ledger,material_label_conflicts=conflicts,
        loads=case['loads'],wall_budget_s=case['budget']['wall_s'],whole_building_run=False,preparation_s=time.perf_counter()-start)
    json_write(dest/'preflight.json',summary)
    lines=['# 三层柱板 CPU 参考模型：核验与试算准备','',
        '状态：输入与映射已准备，未进行真实整栋组装或求解。原 K 文件保留；恢复设计柱截面是用户明确选择的独立 CPU 参考方案。','',
        f"模板指纹 `{case['template_fingerprint']}`；输入指纹 `{summary['input_fingerprint']}`。",'',
        f"原生读取：{audit['native_counts']['solid_elements']} 个 Hex8，{audit['native_counts']['rebar_elements']} 根钢筋梁段；所有封存 K 文件哈希匹配，旋转梯步/栏杆按原生 Jacobian 积分体积。",'',
        f"参考模型：{summary['structural_nodes']} 个结构节点，{summary['shell_elements']} 个柔性壳、{summary['column_elements']} 个纤维梁柱单元，{summary['column_section_profiles']} 套原始纵筋坐标截面。填充、楼梯和超高顶盖只计质量/荷载，不计承重刚度。",'',
        f"恢复柱体积 {ledger['restored_column_volume_m3']:.6f} m³，同时从原始所有者扣除 {ledger['removed_source_volume_m3']:.6f} m³；扣除明细见 JSON。",'',
        f"总质量 {m:.3f} kg，其中固定地坪/基础质量 {fixed:.3f} kg，动态质量 {m-fixed:.3f} kg。本层板和板筋质量归本层壳面，柱筋归自身柱链。偏心附加质量点仅连接一个独立主节点；全局质量、一阶矩、二阶矩相对误差分别为 {ledger['mass_relative_error']:.3g}、{ledger['first_moment_relative_error']:.3g}、{ledger['second_moment_relative_error']:.3g}。",'',
        f"发现 {len(conflicts)} 个语义材质与原 K 混凝土指定不一致的构件，明细保留。外墙语义为 plaster，但 K 实际指定9002、密度2400；CPU保持该质量，按已选柱板体系不计墙承重刚度。",'',
        '柱筋保留原始4Φ16坐标，允许原图中不对称排布；箍筋、锚固和搭接数量计入质量，未用于约束效应或剪切破坏计算。板保留原始四层Φ16位置及等体积配筋层，膜弯耦合不强制为零。Ec=30 GPa 为声明的弹性参考值，Es使用原卡210 GPa。','',
        '连接：层间柱链与板中面共节点，板片共边合并且保留洞口；地坪和柱脚固定。该单元轴线/接头区理想化不模拟基础土体、接触、重力预应力或节点破坏。','',
        f"首试荷载：构件 `{args.target}` 的 south 面，恢复柱后有效面积 {case['loads']['area_m2']:.6f} m²；给定时程0→1 ms达10 kPa→10 ms卸载→150 ms结束。墙反力按实际净高传到上下支承边，只保留支承面至壳中面的偏心矩。不是空气爆炸压力预测。",'',
        '只读检查：`python scripts/run_cpu_response_building.py --case <reference-case.json>`。实际单次运行须先按 AGENTS.md 说明范围、预计耗时并取得当次同意，再显式加 `--run --output-dir <新目录>`；看护上限180秒、最多10000步，失败不发布成功。','',
        '整栋网格尚未做收敛验证。该准备报告不等于整栋动力试算通过，也不预测开裂、屈服、滑移、断裂或倒塌。']
    (dest/'preflight.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('mass_ledger','material_label_conflicts','loads')},ensure_ascii=False))


if __name__=='__main__':main()
