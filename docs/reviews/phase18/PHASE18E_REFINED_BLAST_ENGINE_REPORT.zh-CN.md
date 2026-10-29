# Phase 18E 精细化建筑爆炸引擎：软件验收报告

## 结论

截至提交 \`cd039bc09a5992cab041c49b46948a816cdf1565\`，Phase 18E 软件验收**通过**。已交付独立、版本化的 \`refined_building_blast@1\` 后端：仅读取 Phase 18C/18D 的不可变建筑工件，不修改建筑网格，也不依赖城市生成器、旧爆炸生成器、旧编辑器状态或 \`dyna_assembly.py\`。

此结论只代表软件合同、数据闭合、确定性、审计与兼容性验证通过。每个包均保持：

| 标志 | 实测值 |
| --- | --- |
| \`solver_ready\` | \`false\` |
| \`requires_project_review\` | \`true\` |
| \`engineering_validated\` | \`false\` |
| \`external_program_started\` | \`false\` |

未执行 LS-PrePost 导入门禁、LS-DYNA 求解、收敛检查、爆炸载荷标定、材料参数验证、试验对比或工程等效性验证。因此不得将本阶段 K/Include 包称为已完成真实求解或工程验证。

## 交付边界

项目根模式严格为 \`refined_building_blast@1\`。提供器恰为：

| 提供器 | 软件范围 |
| --- | --- |
| \`explicit_ale_fsi\` | 中性 ALE 域、爆源与 FSI 面数据；不是经验证的 ALE/FSI 求解。 |
| \`lbe_segment\` | 确定性的表面载荷候选；明确不等同于 ALE/FSI。 |
| \`imported_pressure_history\` | 有限、SI 归一化的压力时程；来源、标定与适用性仍须项目审核。 |

支持场景恰为 \`external\`、\`internal\`、\`semi_enclosed\`。服务层提供闭合校验结果/确认记录、版本化 Store/CAS、确定性 K/Include 装配、ScenarioSet、公开包重验与九层预览：空腔/开口、结构、钢筋/连接、非结构、暴露面、爆源、流体域、边界、支承/地基。

## 本次新鲜验收

在 HEAD \`cd039bc09a5992cab041c49b46948a816cdf1565\`、干净工作树执行：

\`\`\`powershell
$phase18eTests = (Get-ChildItem tests -Filter 'test_phase18e_*.py').FullName
python -m pytest -q $phase18eTests
\`\`\`

结果：\`235 passed, 2 skipped in 614.92s (0:10:14)\`。

\`\`\`powershell
python -m pytest -q tests/test_phase18c_dependency_boundaries.py tests/test_phase18d_phase18abc_compatibility.py
python -m compileall -q lsprepost_mcp/refined_blast
git diff --check
\`\`\`

结果：\`24 passed, 165 subtests passed in 15.84s\`；\`compileall\` 与 \`git diff --check\` 均以 0 退出。命令完成后 HEAD 未变且工作树无未提交修改。

两项跳过项是 Task 2 既有 Windows 普通符号链接权限测试（当前账户无法创建 symlink）。Windows junction/reparse-point 与句柄安全路径仍实际执行并通过；原生 POSIX 文件锁只做了非跳过的受控路径覆盖，未在本 Windows 主机做原生 POSIX 运行。

## 真实 Phase 18C 工件：三提供器 × 三场景

验收使用真实 Phase 18C \`rc_box\` 工件，而不是手写几何。

- 建筑工件：\`3900d59b2a27813c93e71678a9b443e99264460fae67b80e5f951bfb8e1423c1\`
- 拓扑：\`b246a3c4b173f8bbfd3a3318550c1b2292cfd627db10249994b938a968fc55bc\`
- 每组合均执行 \`normalize -> estimate -> compile -> preview -> validate\`，并第二次重复编译。
- 下表 9 个组合均为 0 个提供器 finding，第二轮 fragment 指纹与首轮完全一致。

| 提供器 / 场景 | 输入 / estimate / fragment / preview 指纹 | 节点 / 单元 / 面 |
| --- | --- | --- |
| ALE / external | \`ed2f75bf2923b864d3312e5421a0883b0a2ef7f36be9f94922b164ccd3b818d6\` / \`5f43b323b5467b2ef332b6589566194963cd06a03ce2501e9b381b3294415205\` / \`229fca60758937a3cb3c0d59eea1f03b76652f7e5620c6616433b0e81c31021e\` / \`e466a02d2b97ae8b29735efdbfb862a229ed9d5907b9fb404d24b0b2289d44e9\` | 168 / 90 / 860 |
| ALE / internal | \`1ce52833048f38efb03f28b82a52d1698507362a1476bd51e0da99994af15442\` / \`5f43b323b5467b2ef332b6589566194963cd06a03ce2501e9b381b3294415205\` / \`5cf5b30d8121994f4cb19b44ba88b4746d8e0797ccfce12fbe861b6487784bd1\` / \`0b708d46bec43eb31033960f6161a7be065b5aae3dff09e8645c0a7986534858\` | 168 / 90 / 860 |
| ALE / semi_enclosed | \`1ce52833048f38efb03f28b82a52d1698507362a1476bd51e0da99994af15442\` / \`5f43b323b5467b2ef332b6589566194963cd06a03ce2501e9b381b3294415205\` / \`274545883018e230b195fde4bc2d152864848ab8276c7708b33e4a669816d682\` / \`0d339ee3f0b7332ce23e2164bd5c913941d548a1f565483ccaefad720598cc7a\` | 168 / 90 / 860 |
| LBE / external | \`6c60d0060afe3daaaef794adb26d4502b917fd01dc553f172157081f14096744\` / \`08f6ad2c1a60bdf6a66e28ae5d8d1cd5f7c81855c209fd7e50f2cf51ad16c0ed\` / \`291587432f5cfcc185df3bbb08d2eef619144cad193e32e94014928c2b6c3ba6\` / \`85ad6ca487bbe2f47bf61fbae94b5c106bc5c54973f5c99b165c05506033d5f0\` | 0 / 0 / 860 |
| LBE / internal | \`d9c7c5bbac567fa22de4941452926737a5c29d5ec12f44a4f782560a57a77f90\` / \`08f6ad2c1a60bdf6a66e28ae5d8d1cd5f7c81855c209fd7e50f2cf51ad16c0ed\` / \`6edfe76e9417ecaf82d09458aa4a94fd3373ac04a2ff2fdabdef52e375a64c20\` / \`a551bb6d09f8e338a35391d2eacb4e10bcfcf99d38c122293394df3589b9280a\` | 0 / 0 / 434 |
| LBE / semi_enclosed | \`d9c7c5bbac567fa22de4941452926737a5c29d5ec12f44a4f782560a57a77f90\` / \`08f6ad2c1a60bdf6a66e28ae5d8d1cd5f7c81855c209fd7e50f2cf51ad16c0ed\` / \`21d5ef649edd5c5c41b9ea1c4bd9249fbfafc338eec875e0ba4dff649ff9f5e5\` / \`b771764baca2eb948462009c06481d8938479d5388c7cae7d194294fdde35980\` | 0 / 0 / 434 |
| 时程 / external | \`707ffb237f196e2708777b0e76133616c751fca15c5bab0a859504f603037c6b\` / \`59a77ecc604d5af5a6c7e8c81b8289dd50743c04a797dc233d23eda08f058133\` / \`61812c50654afd28fb239ddfce4dd56fc26bc7f0bb8a3e88470ad24acddc069c\` / \`484df7fe8c6c84d01238098a8ba4988e5e7ffe17e82f97e84e9e9fd29be467a8\` | 0 / 0 / 860 |
| 时程 / internal | \`4e8e8853031a55ba609bca7517027f6a59ebc6f06b10acb9facf6f0a098c9ea7\` / \`59a77ecc604d5af5a6c7e8c81b8289dd50743c04a797dc233d23eda08f058133\` / \`4156bea17e542cab797bbc1583c47aa7eda930c7d80fb440c00c0a70b73be28b\` / \`13823d90c69f302ee82e0b63974e270393bd627f05121f010cd63f2da9290aaa\` | 0 / 0 / 860 |
| 时程 / semi_enclosed | \`4e8e8853031a55ba609bca7517027f6a59ebc6f06b10acb9facf6f0a098c9ea7\` / \`59a77ecc604d5af5a6c7e8c81b8289dd50743c04a797dc233d23eda08f058133\` / \`aafa3fef71ce42d15621dec21ec51f33a0edc5e118b215ee2e510b438c42f0ee\` / \`d787afb037e36ff1a67bbfe22e235fe00d85c6ca97b1c8b80f5cc9ebeaf0a68c\` | 0 / 0 / 860 |

ALE 三场景的轴点数均为 \`(7, 6, 4)\`。LBE 与时程提供器不分配 ALE 域节点/实体单元，故计数为 0；面数为由不可变建筑网格反算并闭合的目标面。

## Store、预览与 ScenarioSet 确定性

每个三提供器 external 项目均通过 Store -> validate -> 审核 warning 确认 -> preview -> ScenarioSet -> 第二轮 ScenarioSet。均为 1 条 \`project_review\` warning、0 error、\`preview_is_final=true\`，第二轮的包和 result ID 均逐字相同。

共同建筑计数为 2,070 节点、1,024 单元；controls / outputs fragment 指纹分别为 \`4cab21dad5c1e6a643067172e1a8e34097fba40d67657adbed9e9496937ff478\` / \`071ec9e9b1d8d93241aee63072d8ce12d3e3b115a5d0ec2d5c47a2c901fae62a\`。

| 提供器 | 包指纹 / result ID / 提供器指纹 / 预览指纹 | 渲染计数：建筑节点/单元；提供器节点/单元/面；符号 |
| --- | --- | --- |
| ALE | \`031c7e8b0656044bf33b5eca13ebb984800da516710d8010b75465971993f6af\` / \`result-b63680d01632fca8c9df3862\` / \`229fca60758937a3cb3c0d59eea1f03b76652f7e5620c6616433b0e81c31021e\` / \`8a814b0e6d1dee347ed789b8766138e5856753b1b1dea0b17dc0871c730743d3\` | 2,070/1,024；168/90/860；266 |
| LBE | \`b5d17cc1f8a79239ae7b758ad07c4baebf3f7ef46510527b61c5a5f912870a85\` / \`result-ace639842533b6c2111de858\` / \`291587432f5cfcc185df3bbb08d2eef619144cad193e32e94014928c2b6c3ba6\` / \`3ae93190bc1448f8bcee0475c966f05b9d6780a1434bea51412b10bd8de12c36\` | 2,070/1,024；0/0/860；8 |
| 时程 | \`734a55143f3a0ce662a5af3e6a79dab84e1ccda816837e90572b1eb8d408617f\` / \`result-beb03686e1e6a0a058c55e9e\` / \`61812c50654afd28fb239ddfce4dd56fc26bc7f0bb8a3e88470ad24acddc069c\` / \`21a56d424d78d322ba71187e4bd9d5b646e2d749a3458cf0f7512196bbbe20d7\` | 2,070/1,024；0/0/860；9 |

每包均有 \`main.k\`、\`01_building.k\`、\`02_provider.k\`、\`80_controls.k\`、\`90_outputs.k\`。其字节/行摘要依次为：main 178 B/11 行、building 75,020 B/3,101 行、controls 422 B/8 行、outputs 400 B/8 行；provider：ALE 97,603 B/262 行，LBE 192,006 B/3 行，时程 63,816 B/3 行。公开包边界重新解析 include、K 语法、字节/行/哈希、计数、面几何、资源、ID 分配并做 canonical 重编译，不信任调用方 manifest。

## Phase 18D 地铁入口完整链路

真实 Phase 18D “一组楼梯＋两组扶梯＋独立地下通道”地铁入口 LBE 外部场景已通过 Store -> validate -> acknowledgement -> \`compile_scenario_set\` -> \`validate_public_package\` 完整链路。测试 \`test_approved_subway_lbe_area_is_stable_through_scenario_set_compilation\` 的真实终端结果为 \`1 passed in 572.71s\`。

同一工件独立两轮直接 LBE 复核：

- 资产：\`subway_entrance_001\`
- 建筑 / 拓扑：\`f2c61ce690341c567d3532484351e59b84714634cc6314d3089791645b3c3a79\` / \`9708d81e17acf51611502a5b311f85eef9d7eaa1ca6ef25a018b6f8bd28d0703\`
- 输入 / estimate / fragment / preview：\`7cec4970cd7ef4659b73a3999ebe3e35f697eab7b7dfd04a4386657972c26379\` / \`d1d929464f5c4594111447c95df12ede364648f1f8d5e86299bbc552431beacc\` / \`9e0e2af95195ad24f3baed8c230b0fa1e9353b4add909b9925b1c10a5b989701\` / \`2872ab71c38db7040ea6f22fd45dd5c118395269791c983cb6280f53b26453c3\`
- 41,629 节点、30,206 建筑单元、5,493 目标面、0 finding；第二轮 fragment 指纹相同。

本链路曾暴露同一 5,493 面因遍历顺序导致的浮点面积聚合差异；已统一使用 \`math.fsum\`，保持 \`1e-12\` 严格容差，未改变 Phase 18D 几何、schema 或工件指纹。

## 审核闭环、预算与剩余边界

Task 1–8 均经过独立 scoped review；最终 Critical/Important findings 均为 0。覆盖内容包括闭合合同和循环输入、跨进程 CAS/路径防护、ALE 域预算与半封闭拓扑、LBE/时程输入预算与网格面闭合、地基 HEX8 Jacobian/全局符号命名空间、三提供器 canonical 重建、公开包重验、八项计数和九层可渲染预览。

所有预算在坐标、曲线或目标面分配前执行：ALE 校验轴点/节点/单元，LBE 校验面数量/面积，压力时程校验输入字节/行数/目标面数。预览的八项计数明确分为 \`exact\` 和 \`upper_bound\`，最终包按相应语义闭合验证。Store 以 revision CAS 保存，确认记录绑定 finding 内容哈希、validation 指纹和 revision。

仍需明确的非阻塞项：

- Win32 \`ReplaceFileW\` 失败包装未保留原始 \`winerror\` 名称，但原子性语义已通过测试。
- 普通 Windows symlink 与原生 POSIX 行为应在具备权限/平台的 CI 做原生复验。
- 地铁入口完整 ScenarioSet 约 572.71 秒，完整 Phase 18E 约 614.92 秒；正确性通过，但 Phase 18F 应提供进度、缓存与性能优化。
- Phase 18C 壳/梁没有可推断实体碰撞体积的物理厚度；系统不虚构该工程信息。
- LBE 只支持显式 \`occlusion_policy=none\`，不推断真实遮挡；时程提供器不验证来源、标定或工程适用性。

用户在进入求解前仍必须审核构件/材料卡、钢筋与连接、边界/支承、装药与位置、ALE 域与网格、压力时程来源、控制/输出和 LS-DYNA 版本兼容性。本任务仅新增本报告；未修改 ROADMAP 或 Phase 18F。
