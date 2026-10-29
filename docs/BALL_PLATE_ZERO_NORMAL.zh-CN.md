# 球撞板案例：壳单元零法向量（2026-09-29）

## 已核实的输入与根因

案例文件 `26.9.21ball-plate.k`，SHA-256：
`3f6fa328a0c72bcc77992b9c64c5b6af1c9b1c78449967c826bd7421db0d8c34`。
附件副本与日志命令使用的同名输入文件逐字节一致。模型共1940个节点、256个壳单元、1512个实体单元。

板为PART 1，壳单元ID 1–256；其289个节点ID 1–289全部满足y=z=0，x从−150到150，只有17个不同空间坐标，每个坐标对应17个节点。整块板已退化为一条线。

原文件第70、71行的节点1、2均为(-150,0,0)；第87、88行的节点18、19均为(-131.25,0,0)。第5199行的壳单元1连接18,19,2,1，因此4个不同节点ID只对应2个空间位置。全部256个壳的面积及法向量均为0。节点坐标用固定列和空白分隔独立核对一致。

不能从这个文件唯一恢复缺失方向的板宽、位置和朝向。交换连接次序或合并重合节点都不能恢复板面。应依据原始几何尺寸恢复第二方向坐标或重新划分板网格，随后重新检查约束、接触、法向、单位和求解初始化。

## 报错关联

| 求解器信息 | 本例含义 | 项目处理 |
| --- | --- | --- |
| Error 30099 (INI+99) | 壳法向量为零 | `quality.geometry.shell_zero_normal`，error，包含完整单元ID及最多10条坐标证据 |
| Warning 30100 (INI+100) | 严重畸形单元 | 本例与退化板一致；保留面积、翘曲、形状比检查，不能把所有30100都归因于同一原因 |
| Warning 21129 (STR+1129) | 面积/最长对角线平方小于0.1，本例为0 | `quality.geometry.shell_shape_ratio`，warning，并阻止solver draft readiness |
| Error 20018 (STR+18) | 输入阶段256个致命错误的汇总 | 应追踪前面的30099，汇总本身不是另一种几何原因 |
| Warning 20006 (STR+6) | D3PLOT间隔从0重置为0.5 | 输出设置提示；不是本例256个致命几何错误的根因 |

日志对30099、30100、21129各显示50次后抑制屏幕打印。不能因此认为仅50个单元损坏；静态检查报告全部256个ID。

形状比采用法向量模长的一半作为投影面积；四边形使用最长对角线，三角形使用最长边。法向零值检测使用与单元跨度平方相关的1e-12相对容差，属于保守静态筛查，不声称与所有LS-DYNA单元公式完全等价。缺失节点、非有限坐标另行报错。合法的N3=N4或N4=0三角形不作为重复节点退化。

## 本次沉淀到项目的改动

- 通用壳零法向和形状比规则适用于导入文件及现有生成模型的静态校验；有限坐标错误也会阻断readiness。
- 补全坐标证据、单元总数、全部单元ID及求解器代码关联。
- 材料首卡按标准10列固定字段读取，也保留逗号、空白分隔输入；TITLE按一行消费，包括空标题和纯数字标题。首卡无法解析时不把后续卡当作MID。
- `parse_keyword_metadata`与几何检测共用材料首卡解析，本例材料被正确识别为1、2，消除了原来的材料0重复/材料缺失误报。
- 修复跳过缺失节点单元后，翘曲、长宽比和板法向检查中单元ID错位的问题。
- checker版本由v5改为v6，使旧静态检查缓存失效。
- `tests/test_ball_plate_regression.py`保留32个小型回归用例，无需本机原始模型路径或求解器许可；原有缓存测试补充v5失效验证。

## 使用与验证范围

在项目目录可运行：

```powershell
python -m pytest tests/test_ball_plate_regression.py tests/test_keyword_checks.py tests/test_import_keyword.py tests/test_tools.py::ToolTests::test_checker_version_tracks_r12_solver_compatibility_rules tests/test_phase10_error_inputs.py tests/test_phase13.py::Phase13BlastPresetTests::test_phase13_shell_presets_pass_aspect_ratio_solver_gate
```

用现有导入功能导入keyword并执行校验，即可在checks中看到新规则；底层调用为 `keyword_quality_checks(text, {"model_type": "imported_keyword"}, {"keyword_dir": source_directory})`。

本次只做静态复查、最小样本回归和相关专项测试，没有改写原模型，也没有执行LS-DYNA求解、全量回归或重型案例。原始单位制未确认，现有检测器的SI密度范围与mass_kg等字段不能据此当作材料参数或单位正确性的结论。接触关键字受支持范围、波速/时间步估算仍有限制，应区分工具能力提示和已证实的模型错误。

专项结果为66 passed、3 subtests passed。新增几何规则另对三个现有小型预设做了静态筛查：`blast_on_helmet`、`blast_on_circular_plate`、`blast_on_multiple_targets`分别有46、24、48个壳单元形状比小于0.1；最小比分别约0.05445、0.03229、0.04772。其有限坐标、零法向及原长宽比检查均通过。这些新增保守警告会使solver draft readiness变为false，需复核/改善网格；并非已用真实求解器证明它们一定失稳。本次未改动这些预设网格。

标准固定列输入格式可参照[Ansys PyDYNA字段格式说明](https://dyna.docs.pyansys.com/version/dev/api/ansys/dyna/core/lib/kwd_line_formatter/index.html)。本例具体错误代码、阈值及数量来自用户提供的R12运行日志和原模型。
