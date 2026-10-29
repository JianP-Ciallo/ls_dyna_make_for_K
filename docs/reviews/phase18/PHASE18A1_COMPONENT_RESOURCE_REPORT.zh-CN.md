# Phase 18A-1 构件级模型资源实施与审计报告

日期：2026-08-04
结论：Phase 18A-1 已完成代码实施、资源生成和回归验证。四个资源可独立校验、导出为普通 `.k` 文件，也可通过统一 `model_resources[]` 合同附加到现有模型生成入口。资源仍保持 `source_reference`，不代表已经完成 LS-DYNA 工程验证或求解验证。

## 1. 来源与边界

- 规范模型名：双层钢筋混凝土框架爆炸参考模型（`two_storey_rc_frame_blast_reference`）
- 来源文件：`2.k`
- 来源 SHA-256：`c1c02a9e832852854b47cd3720bc9348cf48989484d25e1a54036836d0697a22`
- 来源单位制：`tonne_mm_s_N_MPa`
- 资源单位制：`SI_m_s_kg_N_Pa`
- 纳入范围：PID 201–203、301–303、401–402、501–502 对应的混凝土 Solid、钢筋 Beam、Beam N3 方向节点及其 Part/Section/Material/Curve/Set/耦合依赖。
- 排除范围：PID 1001、1002 及控制卡、输出卡和其他非构件数据。

## 2. 已生成资源

| 规范资源 ID | 旧兼容别名 | Node | Solid | Beam | 压缩载荷字节数 | `component.k.gz` SHA-256 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `two_storey_rc_frame_beam_reference` | `2k_rc_beam_reference` | 32,014 | 6,600 | 11,540 | 349,981 | `bd55c8c9c483e24a9a0aff0f8ea45eec081d0af916a51f34838e9590141dc722` |
| `two_storey_rc_frame_column_reference` | `2k_rc_column_reference` | 32,357 | 6,000 | 12,546 | 343,287 | `c8e0d80476ac77fcdb7c7a2a123fad7d4db7cb8a8241b40478ddcdca5aad4033` |
| `two_storey_rc_frame_slab_reference` | `2k_rc_slab_reference` | 163,301 | 91,245 | 25,725 | 2,631,984 | `30f76bae69440bcbb70feeef44ef46132cdf34046e3dea75d44cf8580656c912` |
| `two_storey_rc_frame_foundation_reference` | `2k_rc_base_reference` | 52,224 | 22,445 | 12,150 | 743,768 | `ba0187f6a44a6a1733edea659003cd6bfe183f011558cbfb7d807d56c26098e0` |

四个资源合计精确覆盖 126,290 个 Solid 和 61,961 个 Beam。节点按构件依赖闭包分别保存，因此构件交界的源节点会在不同独立载荷中重复出现；其源 ID 被保留并写入审计信息，用于可追溯重组。

每个资源目录包含：

```text
manifest.json
component.k.gz
audit.json
```

## 3. 依赖闭包审核

| 资源 | Part | Section | Material | Set/耦合 |
| --- | --- | --- | --- | --- |
| 梁 | 201/202/203 | 4/3/1 | 5/14/8 | Set 1，1→201 |
| 柱 | 301/302/303 | 4/2/1 | 5/12/8 | Set 2，2→301 |
| 楼板 | 401/402 | 4/2 | 5/12 | Part 402→401 |
| 基础 | 501/502 | 4/6 | 5/8 | Set 6，6→501 |

拆分时过滤了原始跨构件 Part Set 成员，使每个独立资源只保留自身钢筋与混凝土的闭合关系。Curve 1、混凝土侵蚀卡和所需钢筋材料卡随依赖闭包写入；未使用材料不混入构件载荷。

## 4. 全源重组证明

自动审计逐条读取 `2.k` 和四个独立载荷，结果如下：

- 四个构件的 `(单元类型, EID)` 集合两两不相交。
- 四集合并集与来源 PID 201–502 的全部 188,251 个结构单元完全相等。
- 每个 Solid/Beam 的 EID、PID 和节点连通性与来源逐条相等。
- 所有载荷节点均能在来源中找到；坐标经 `mm × 0.001 → m` 后逐节点一致。
- Part—Section—Material 角色绑定与四组耦合身份一致。
- 每个资源内缺失节点引用为 0；Beam N3 方向节点被完整保留。
- 使用同一审计输入连续生成两次，四组 `manifest.json`、`audit.json` 和 `component.k.gz` 均字节一致。

各资源结构单元行审计 SHA-256：

| 资源 | 单元行 SHA-256 |
| --- | --- |
| 梁 | `cfa444cc54cbaef9a3fc3960f65303946debf7e4d9a0c9e5b95a288b756fcaed` |
| 柱 | `eb8e0cf7790f95759e19053b6d91f0e5675404716733d9797da35b5c61b28c50` |
| 楼板 | `2316e2582130f1b6340c3e361ac443b85ade26372599a9263b58dfcd36063931` |
| 基础 | `b9419ad970057b8b72834293bba543d133aa111d576dc237d18305e18111a450` |

## 5. 调用与兼容实现

公共输入新增可选字段：

```json
{
  "model_resources": [
    {
      "id": "column_1",
      "model_resource_id": "two_storey_rc_frame_column_reference",
      "transform": {
        "translation_m": [1.0, 2.0, 0.0],
        "rotation_deg": [0.0, 0.0, 0.0]
      },
      "material_binding": "source_reference"
    }
  ]
}
```

实现保证：

- 未提供 `model_resources` 时规范化为 `[]`，原生成路径及原关键字输出不附加任何资源元数据。
- 实例化只接受有限刚体平移与旋转；不接受缩放、非有限数或材料降级。
- Node、Element、Part、Section、Material、Set、Curve 全部独立分配不冲突的 ID 命名空间，并同步改写引用。
- 多个相同资源实例能够自动获得两两不相交的 ID 区间。
- 资源片段统一插入最终 `*END` 之前，最终文件只保留一个 `*END`。
- 十节点实体保持 `*ELEMENT_SOLID (ten nodes format)` 关键字和 EID/PID＋10 节点的两行记录；验证、实例化及 ID 扫描均按同一布局处理。
- 已用三个代表性既有模型类型验证同一公共入口；未引用资源时的回归基线保持不变。

已注册四个资源工具：`list_model_resources`、`get_model_resource`、`validate_model_resource`、`export_model_resource`。导出工具会先复核载荷哈希、网格计数和节点引用闭包，再生成可单独打开的普通 `.k` 文件，并拒绝覆盖已有文件。

规范列表只显示新的描述性 ID；原 `2k_rc_*` ID 继续作为兼容别名解析到同一份规范资源，不产生重复列表项或资源副本。

## 6. 验证证据

最终相关回归矩阵：185 项测试通过，0 失败，包含：

- Phase 18A-1 构件合同、流式生成、独立闭包、全源重组、确定性生成、刚体变换、全 ID 重映射和公共入口兼容测试。
- Phase 18 资源库、关键字拆解、材料库、配置解析、工具协议和代表性既有生成路径测试。
- `python -m compileall -q lsprepost_mcp scripts`：通过。
- `git diff --check`（本阶段相关目录）：通过。
- 仓库全量 Python 回归：790 项通过、0 失败、7 项按环境条件跳过。

## 7. 已知限制与审核状态

- 四个构件资源均为 `validation_status=source_reference`、`requires_project_review=true`、`solver_ready=false`。
- 材料卡完成来源保真转写和显式 SI 规范化，但其适用工况、失效参数、应变率参数和网格敏感性仍需项目审核。
- 当前材料绑定固定为 `source_reference`；角色化材料替换属于后续审核工作，不在 18A-1 中静默实施。
- 当前实现证明关键字结构闭合、来源一致和软件兼容，不声称求解收敛、结果正确或工程适用。
