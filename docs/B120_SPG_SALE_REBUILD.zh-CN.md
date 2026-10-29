# B120 圆柱分层体、钢套与 SPG/S-ALE 重建

此适配器重建 `B-120-C5-50-6kg-SPG-SALE-total.k` 的节点、HEX8 网格和空间集合，复用原物理卡片。单位为用户确认的 SI：m、s、kg、N、Pa。它是固定来源模型的专用适配器，不代表任意 K 文件自动逆向建模能力。

## 来源与输入

- 原文件 SHA-256：`b4a0d8d363817e691152186fd073440c9e2dc70057b1f2e941ea6110c6b1df38`。
- 资源索引 SHA-256：`4cf9dee2394d484319454d1129d605845b1a9f0e96c37d5bde6f863dc1078c1a`。
- 模型类型：`b120_spg_sale_rebuild`；参数版本：`b120_spg_sale.rebuild@1`。
- 默认工程名：`B120_C5_50_SPG_SALE_rebuilt`。
- 几何与物理参数固定为本次来源识别结果；可调整项仅为模型名称和网格划分。
- 参数不接受原节点数组、单元连接数组或替代网格路径。

尺寸来自源网格的圆柱/平面拟合，最大坐标拟合差约 2 微米。材料、截面、接触、控制参数、S-ALE 区域和初始体积分数几何直接读取源卡片。没有把原网格直接拷入生成器。

## 几何、部件和连接

| PID | 部件 | 几何 / m | 截面与材料 |
|---|---|---|---|
| 2 | CONCRETE | R=1.05，z=-0.54…0.86；孔 R=0.049，z=0…0.86 | SEC2 SPG/47，MID2 MT41 |
| 4 | C5 | R=1.05，z=-1.04…-0.54 | SEC2 SPG/47，MID4 SOIL_AND_FOAM |
| 5 | RC40 | R=1.05，z=-1.54…-1.04 | SEC3 SOLID/1，MID5 MT41 |
| 6 | 钢套 | 内 R=1.05，外 R=1.066，z=-1.54…0.86 | SEC3 SOLID/1，MID6 PLASTIC_KINEMATIC |
| 1 / 3 | TNT / AIR | 作为 S-ALE 多材料组的材料部件 | SEC1/11，MID1+EOS1 / MID3+EOS2 |

钢套在 z=-0.42…-0.26 和 0.70…0.86 的两道外环加厚至 R=1.086；外环和钢套共享节点。PID4/5 在 z=-1.04 共享节点；PID2/4 在 z=-0.54 独立重合，通过原 CID1 接触。钢套与 PID2/4/5 保留原 CID3/4/5 接触。没有把接触界面焊接成共享节点。

NSID1 按 z=-1.54 重新选择底面节点；SSID2 按实际 HEX8 外表面重新提取底面，法向 -z。SSID1 保留 SALEFAC 对 MSH1001 六个面的作用范围。原底面固定与无反射边界同时存在，未更改其物理意图。

S-ALE 区域仍为 [-0.5,-0.5,-0.5]…[0.5,0.5,1.6]，步长 0.02，262,500 单元、275,706 节点，由求解器按结构化网格卡生成；动态 PID101 不是缺失的普通 PART。保留原 PID2↔PID101 耦合和 AMMG1。初始 TNT 圆柱 R=0.049、z=0…0.56，起爆点 (0,0,0.56)，均沿用原卡片。

## 生成方法与默认网格

`b120_spg_sale_mesh.py` 调用项目已有的 `phase15.compile_axisymmetric_quad_mesh` 构造二维拓扑块，再映射圆孔/外圆、共形拼接并沿 z 拉伸成 HEX8。分层界面、孔底和外环端面都进入分段轴向坐标；不同部件根据原连接关系选择共享或独立节点。

默认网格参数：`core_divisions=8`、`core_radial_layers=3`、`bore_transition_layers=4`、`outer_extension_cells=21`、`outer_radial_layers=25`、`axial_step_m=0.02`。

默认结果为 1,000,415 个显式节点、947,200 个 HEX8：PID2 533,800，PID4/5 各 193,100，PID6 27,200。新显式节点/单元从 2,000,001 起编号；S-ALE 从 9,000,001 起预留，范围不重叠。原始单元表不参与生成。

## 分类资源

资源前缀为 `b120_spg_sale_b4a0d8d36381_`，共 47 条：

- 6 个材料包位于 `resources/materials/source_rebuild/b120_spg_sale/`，必要 EOS 随材料保存。
- 41 个截面、部件关系、集合选择规则、接触、耦合、控制和输出资源位于 `resources/model_library/structural/source_rebuild/b120_spg_sale/`。
- 索引位于 `resources/reviews/source_rebuild/b120_spg_sale/source_index.json`。

每条记录保存原始 ID、资源 ID、来源行号、原卡片哈希、资源依赖与单位。46 个物理定义块逐字保留（仅统一换行）；6 个网格相关块依据保存的规则重建，包含两个集合块、一个 S-ALE 网格块和三个控制点块。旧节点/面成员列表只在分析归档中，不能被生成器复用。

资源注册先检查所有目标，遇到不同内容的同名资源即失败；同内容重复注册不覆盖。单位转换未发生，原值保留。资源状态为 `source_reference`，不是求解认证。MT41 外部实现缺失如实记录。

## 可重复执行

在项目根目录执行。当前注册资源可直接生成，生成步骤不再读取原节点或单元。若需从原文件重新注册资源，入口如下：

```powershell
python -B -m lsprepost_mcp.b120_spg_sale_rebuild register-resources '<原始K文件路径>'
python -B -m lsprepost_mcp.b120_spg_sale_rebuild prepare --spec-json '<重建参数JSON路径>'
python -B -m lsprepost_mcp.b120_spg_sale_rebuild generate --spec-json '<重建参数JSON路径>' --if-exists versioned
```

生成命令返回实际工程目录；同名存在时 `versioned` 创建新版本，不覆盖旧工程。默认 `error` 拒绝同名。MCP 对应入口为 `prepare_b120_spg_sale_rebuild` 和 `generate_b120_spg_sale_rebuild`。

对命令返回的目录运行来源验证：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_generated_k.ps1 -ProjectDir '<实际工程目录>'
```

只有 `ok: true` 且 `classification: generated_by_lsprepost_mcp` 才表示当前 K 与当前 model.json、资源和生成器一致。交付目录的 model.k 是工程生成文件的字节一致副本。

## 验证范围与限制

专项测试覆盖小网格拓扑、界面连接、空间集合、材料原值、资源依赖/冲突、防篡改、流式生成及校验、前两个重建模型和已有流式模型兼容性。按根目录 AGENTS.md 约定执行相关专项，不自动启动全量回归或重型案例。

本次实际交付另有独立文件解析：检查全部 947,200 个 HEX8 的八个高斯点 Jacobian、部件体积、几何范围、孔和共享界面、集合外表面拓扑以及原卡片一致性；LS-PrePost 实际读取并导出预览。详见交付目录 `REBUILD_REPORT.zh-CN.md`。

尚未进行 LS-DYNA 求解或响应等价性验证。MID2/MID5 的 MT41 材料实现缺失，不能宣称模型已具备求解条件。原底面固定与无反射边界重叠须工程确认；文件名“6kg”与原圆柱几何/密度推算的连续 TNT 质量约 6.462812 kg 有差异，保持原卡片，未改成名义 6 kg。离散初始填充质量和 SPG/S-ALE 稳定性尚未验证。
