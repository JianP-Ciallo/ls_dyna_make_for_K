# 能力驱动校验框架

项目校验不再仅根据 `model_type` 写死规则。每个生成器通过
`metadata.validation_capabilities` 声明实际使用的能力，旧项目则由
`model_type` 回退映射补齐。

当前已覆盖：

- 三维与二维轴对称 MM-ALE；
- TNT/JWL 体积分数初始化和起爆；
- ALE-Lagrange FSI，包括二维复合线段集；
- K&C 混凝土和受控钢材塑性；
- 三维/二维非反射边界；
- 城市场景可移动部件接触；
- ALE 压力、节点历史和壳单元历史输出。

校验分为两层：

1. **能力卡片门禁**：按 token 精确检查必需 keyword，支持受控替代卡片，
   不再用普通字符串包含判断。
2. **引用图校验**：检查 Part、Element、Node Set、Part Set、Solid Set、
   Segment Set、接触、FSI、边界、起爆、体积分数和数据库输出之间的引用。

新增场景必须先声明能力，再补代表性的成功与故障回归测试。静态检查通过只说明
keyword 结构和引用关系满足当前受控规则，不代表材料标定、数值收敛或工程精度已验证。

## 基座工具保障

`validate_model` 和 `read_project` 共用同一个 `validate_project_files()` 检查器。
每份 `checks.json` 必须记录：

- `checker_version`
- 当前 `model.k` 的 SHA-256
- 当前 `model.json` 的 SHA-256

`read_project` 不再直接信任磁盘上的旧检查。发生以下任一情况时会重新执行完整静态检查并覆写 `checks.json`：

- K 文件或模型 JSON 已被修改。
- 检查器版本升级。
- `checks.json` 缺失。
- `checks.json` 损坏或无法解析。

因此，新场景增加的能力规则会反向作用于旧项目。旧项目若缺少当前要求的 FSI 段集、K&C 输出卡或引用关系，将被重新判定，而不会继续沿用历史 `ok: true`。
