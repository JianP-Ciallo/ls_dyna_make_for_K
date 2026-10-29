"""Read sealed three-storey semantic metadata; no mesh generation or solver."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lsprepost_mcp.architecture.cpu_response.building import inventory_template
from lsprepost_mcp.architecture.cpu_response.results import json_write


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,default=ROOT/'resources/fixed_building_pressure/three-storey-structural.zip')
    p.add_argument('--output-dir',type=Path,required=True);args=p.parse_args()
    with zipfile.ZipFile(args.archive) as z:
        info=z.getinfo('structural-template.json')
        if info.file_size>2_000_000:raise ValueError('semantic index too large')
        raw=z.read(info)
    report=inventory_template(json.loads(raw))
    report['semantic_file_sha256']=hashlib.sha256(raw).hexdigest()
    report['native_files_verified']=False
    dest=args.output_dir.resolve();dest.mkdir(parents=True,exist_ok=False)
    json_write(dest/'inventory.json',report)
    groups=report['groups'];cs=report['components']
    differences=[k for k,c in cs.items() if c['native_bounds_differ']]
    lines=['# 三层柱板体系：第一轮映射清单','',
           '用户选择：柱与楼板承重，填充墙传递压力并计入质量。该清单只读取封存语义数据，未生成网格、运行整栋求解或修改 K 文件。','',
           f"模板：`{report['template_id']}`；指纹：`{report['template_fingerprint']}`。",'',
           '| 分组 | 数量 | 下一步映射 |','| --- | --- | --- |',
           f"| 混凝土柱 | {len(groups['columns'])} | 纤维梁柱，核验原生截面、柱端及配筋 |",
           f"| 混凝土楼板/屋面 | {len(groups['plates'])} | 分层配筋壳，保留洞口与局部弯曲 |",
           f"| 填充墙/隔墙/井筒/女儿墙 | {len(groups['infill'])} | 核验上下支承边，分配压力与质量，不计承重刚度 |",
           f"| 其他构件 | {len(groups['other'])} | 单列质量/荷载路径；楼梯、基础和设备顶板不能无说明删除 |",'',
           f"没有 beam 角色。{len(differences)} 个构件的语义顶点范围与原生范围不同，详见 JSON；不能直接把显示范围变成实体。",'',
           '混凝土屋面包含电梯超高顶盖，不能自动连接到普通屋面；plaster 井筒不作为混凝土核心筒。原 K 的材料与侵蚀参数不是已标定的建筑抗爆参数。','',
           '单跨验证采用局部板厚偏心刚臂和可弯曲楼板。填充墙采用沿高度简支条带的均布荷载传力；该假设只计算支承传力，不求墙体局部振动、破坏或接触。','',
           '待核验：原生节点/单元拓扑和连接偏心、实际配筋与材料方案、填充墙支承边、基础约束、重复体积和附属构件质量。完整模型规模和耗时估计完成后，再按项目约定申请受影响的真实整栋验证。','',
           '明细中保留每个构件的顶点、角色、材料、分组和范围差异；ready_to_solve 保持 false。']
    (dest/'inventory.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(dict(counts={k:len(v) for k,v in groups.items()},bounds_differences=len(differences),ready_to_solve=False)))


if __name__=='__main__':main()
