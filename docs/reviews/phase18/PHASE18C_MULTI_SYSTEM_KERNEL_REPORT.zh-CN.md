# Phase 18C 多结构体系精细建筑内核实施报告

日期：2026-08-06
状态：首批五种标准结构体系的软件内核已实现；Phase 18C 最终工程验收尚未完成。

## 1. 本次交付

本次新增独立包 `lsprepost_mcp/refined_building/`，没有把逻辑继续写入既有大型 schema、装配或场景模块。其编译顺序为：

```text
建筑定义规范化
  -> 空间/空腔/洞口拓扑
  -> 结构体系解析
  -> 对应结构后端
  -> 可选非承重构件
  -> 流体暴露表面目录
  -> 跨模块校验
  -> 确定性 building fingerprint
```

已实现能力：

- 建筑包络、楼层、轴网、空间、洞口、非结构构件与结构体系的独立输入合同。
- 房间空腔、相邻关系以及“空间—外部”洞口连通语义。
- 洞口边界参与 Solid 网格分段，洞口区域的 Solid 和穿越洞口的钢筋段会被删除，不再只生成一个标签。
- 六种体系的注册与参数审核：`rc_frame`、`rc_frame_shear_wall`、`steel_frame`、`steel_concrete_hybrid`、`rc_box`、`custom_hybrid`。
- 五种标准体系的可执行后端：RC 框架、RC 框架—剪力墙、钢框架、钢—混凝土混合、RC 箱体。
- RC 的 `full_reinforced`、`concrete_only`、`custom` 三种模式；尺寸和轴网改变时重新生成 Solid、纵筋/箍筋/板墙筋与嵌入关系。
- 钢结构 Beam/Shell、钢节点连接，混合体系的混凝土 Solid、钢构件和组合界面。
- 非结构面板使用独立 Shell 与独立节点；未显式声明时不创建结构共节点连接。
- 外表面、内部空腔表面、洞口边界、地面接触面和用户可选面的表面目录。
- 节点/单元重复与悬空引用、Solid 正体积、Solid 空腔侵入、材料/截面角色、连接引用和表面分类互斥检查。
- 纯净发布包包含新内核与隔离测试，并排除 `__pycache__`、`.pyc`、`.pyo`。

## 2. 默认最小建筑基线

以下结果来自同一个 6 m × 6 m × 3 m 默认建筑合同、0.5 m 默认 Solid 网格目标尺寸。RC 体系使用默认 `full_reinforced`。计数仅用于软件回归，不代表具体工程的最终网格规模。

| 结构体系 | Node | Solid | Shell | Beam | 连接 | 软件校验 | 指纹 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `rc_frame` | 2,260 | 384 | 0 | 820 | 1 | 通过 | `7a0eeb6f6af2f240620447d0e93057a2fcde73b2cca38e846c98c85e041a58ca` |
| `rc_frame_shear_wall` | 3,198 | 688 | 0 | 884 | 1 | 通过 | `c3bf23fff7a7b39bf62c787cdfe4bb4d337c5d9d1a876fc72df0bb8886cefc9a` |
| `steel_frame` | 18 | 0 | 4 | 21 | 1 | 通过 | `075b926ff7f0f73243fa85000d110ec6b8bddfe819f2da8c673bfc02337f38cd` |
| `steel_concrete_hybrid` | 694 | 288 | 4 | 21 | 2 | 通过 | `46664863a2fa68baabccfbada08b6918d00cbd3716b8e6ab096711ef2a002c3d` |
| `rc_box` | 1,816 | 576 | 0 | 206 | 1 | 通过 | `b7ec7085799afe62a21d3a2a8633e07b9eba8a365b1865d0a0adda152ff563cc` |

## 3. 验证证据

专项矩阵：

```powershell
python -m unittest tests.test_phase18c_contracts tests.test_phase18c_spatial tests.test_phase18c_systems tests.test_phase18c_dependency_boundaries tests.test_phase18c_meshing tests.test_phase18c_rc_backend tests.test_phase18c_structural_backends tests.test_phase18c_surfaces tests.test_phase18c_compiler tests.test_phase18c_packaging -v
```

结果：42 项通过，0 失败，0 跳过。

全项目回归：

```powershell
python -m compileall -q lsprepost_mcp
python -m unittest discover -s tests
```

结果：Python 编译检查通过；861 项通过，0 失败，7 项环境相关跳过；单元测试耗时 445.617 秒。

依赖边界测试会遍历 `lsprepost_mcp/refined_building/` 的 Python AST，禁止导入既有场景生成、ALE 爆炸和大型装配模块。该门禁本次通过。

## 4. 尚未完成及禁止夸大的部分

- `custom_hybrid` 已具备两个以上子体系、显式区域和区域不重叠审核，但尚未提供网格编译后端；调用编译器会明确拒绝，不会输出伪模型。
- 当前材料和截面仍以稳定角色记录在制品清单中；与 Phase 18B 审核资源的资产级自动解析、版本锁定和最终 LS-DYNA 卡片装配仍需继续完成。
- RC 保护层、直径、间距和钢筋角色选择已进入软件合同；端区加密、锚固/搭接、节点核心区和各建筑的配筋设计仍需项目规范确认。
- 非结构面板已与承重结构隔离，但复杂幕墙、门窗框和 Shell 面板洞口的细分模板属于后续建筑资产工作。
- 钢节点目前是显式连接制品和可选简化模型，不等同于已完成螺栓、焊缝、接触和断裂参数标定。
- 尚未完成网格收敛、材料标定、真实 LS-PrePost 导入检查、LS-DYNA 求解和试验/文献对照。
- 所有输出继续保持 `requires_project_review=true`，本报告只证明软件合同与回归通过，不授予 `engineering_validated`。

## 5. 下一步门禁

Phase 18C 最终验收前应继续完成：

1. 把材料/截面角色解析到 Phase 18B 已审核资源及其版本哈希。
2. 实现并测试 `custom_hybrid` 分区编译与界面闭合，或经用户批准从首版可执行体系中移除。
3. 增加 RC 端区、锚固、节点区和局部网格加密合同。
4. 选取至少一个 RC、一个钢结构和一个 RC 箱体样例进行 LS-PrePost 真实导入检查。
5. 经项目规范审核后，再进入 Phase 18D 的商业超市、住宅和地铁入口资产建模。
