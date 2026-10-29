# Phase 15 FSI Wave Transfer Design

## Goal

修复 Phase 15 二维轴对称 MM-ALE 爆炸模型，使 TNT/空气域中的爆炸冲击波通过有效 FSI 接口传入混凝土，并用真实 LS-DYNA 输出证明传递确实发生。

## Current Failure

当前 `*CONSTRAINED_LAGRANGE_IN_SOLID` 以混凝土 part 作为 slave。现有真实求解的 `d3hsp` 明确报告：

```text
number of slave segments for coupling = 0
```

因此，正常终止、非空 `dbfsi`、静态关键字检查通过均不能证明冲击波传入混凝土。

## Modeling Decision

保留现有二维轴对称 MM-ALE/K&C 模型，不改成三维模型，也不采用 ALE/结构共节点替代方案。

从混凝土四边形单元拓扑中提取只属于一个混凝土单元的外边，并按几何位置分类为：

1. `charge_bottom`: 装药底面，位于装药下方的水平混凝土表面。
2. `borehole_wall`: 水泥孔壁，位于装药和孔内空气外侧的竖直混凝土表面。
3. `concrete_top`: 水泥顶面，位于上方空气域下侧的水平混凝土表面。

三组线段必须显式写为 `*SET_SEGMENT_TITLE`。线段节点顺序必须使法向朝向相邻 ALE 域。

FSI 使用显式 segment set：

- `SSTYP=2`
- `NQUAD=4`
- `DIREC=2`
- 未启用混凝土侵蚀时 `CTYPE=4`
- 启用混凝土侵蚀时 `CTYPE=5`

ALE master 继续引用受控的空气/TNT ALE part set。

## Static Gates

生成关键字前必须满足：

- 三个命名线段集都存在且数量大于 0。
- 每条线段由两个不同的有效混凝土节点组成。
- 每条线段确实是混凝土外边界，不允许内部边。
- 三个集合之间不得存在重复线段；共享端点允许。
- 每个集合连续，且坐标位于对应的几何边界容差内。
- 法向朝向对应 ALE 区域。
- FSI 卡引用 segment set，不再引用混凝土 part 作为 slave。

任一门禁失败时不生成可求解项目。

## Solver Acceptance Gates

真实求解完成后，验收器必须同时检查：

1. LS-DYNA 正常终止。
2. `d3hsp` 中 FSI slave segment 总数大于 0。
3. `d3hsp` 中各受控 FSI 接口均未报告空 slave surface。
4. 混凝土探针应力张量全部为有限数。
5. 从轴对称应力张量计算的静水压力出现超过数值噪声的非零响应。
6. 从轴对称应力张量计算的主应力出现超过数值噪声的非零响应。
7. K&C `*MAT_CONCRETE_DAMAGE_REL3` 明确设置 `NOUT=2`，并且 `elout`
   中对应的 scaled damage measure 通道存在、可读取且数值有限。

`scaled_damage > 0` 作为独立物理结果报告，不作为“冲击波已经传入混凝土”的必要条件。

以下结果不得替代上述门禁：

- 仅静态关键字校验通过。
- 仅 LS-DYNA 正常结束。
- 仅 `dbfsi` 文件存在或非空。
- 仅 ALE 域出现压力。

## Response Calculations

对每个混凝土探针和每个有效时刻，按轴对称应力分量构造应力张量：

```text
[ sigma_r    tau_rz       0     ]
[ tau_rz     sigma_z      0     ]
[   0          0       sigma_t  ]
```

静水压力定义为：

```text
p = -(sigma_r + sigma_z + sigma_t) / 3
```

主应力为该张量的三个特征值。验收使用相对初始状态的响应幅值，并设置明确的绝对噪声下限，避免把浮点抖动判为载荷传递。

## Output Contract

每次 Phase 15 真实求解产生机器可读验收报告，至少包含：

- 三个生成线段集的数量和坐标范围。
- `d3hsp` 报告的 slave segment 数量。
- 混凝土峰值静水压力及其探针和时刻。
- 混凝土三个主应力峰值及其探针和时刻。
- K&C scaled damage 通道是否可读、峰值及其探针和时刻。
- `wave_transfer_verified` 布尔结果。
- 每个失败门禁的稳定错误 ID 和证据文件路径。

只有所有必要门禁通过时，`wave_transfer_verified` 才能为 `true`。

## Testing Strategy

1. 单元测试验证外边提取、三类几何分类、连续性、去重和法向。
2. 关键字测试验证三个 `*SET_SEGMENT_TITLE` 和 `SSTYP=2` FSI 引用。
3. 解析器夹具验证 `d3hsp` 的零线段、正线段和缺失接口情况。
4. 响应计算测试覆盖有限值、零响应、非零响应和异常应力数据。
5. K&C 测试覆盖第 6 历史变量存在、缺失、非有限值和零值可读。
6. 最终以真实 LS-DYNA 回归作为验收，生成新项目和新求解目录，不覆盖历史结果。

## Non-Goals

- 不把自动 K&C 参数称为经试验标定的 CF120 材料。
- 不以本次修复校准材料参数或爆炸载荷。
- 不要求混凝土必然发生损伤。
- 不修改其他四个场景或通用项目存储逻辑。
