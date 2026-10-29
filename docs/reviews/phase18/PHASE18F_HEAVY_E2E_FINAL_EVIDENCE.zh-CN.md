# Phase 18F 三项大型端到端最终 PASS 证据

日期：2026-08-20

代码 HEAD：`0dd6fb004230bfafb1b5b876615d03e5ace133a5`

三项测试均以单进程串行执行，并分别保存独立 JUnit XML。每项覆盖项目创建、保存、权威预览、验证、
警告确认、K 包生成及生成物完整性读取。测试没有启动 LS-PrePost 或 LS-DYNA。

| 测试组合 | 终态 | pytest 总耗时 | JUnit 文件 |
| --- | --- | ---: | --- |
| 商业建筑 + `explicit_ale_fsi` | PASS（1/1） | 455.94 s | `PHASE18F_HEAVY_E2E_EXPLICIT.xml` |
| 住宅建筑 + `imported_pressure_history` | PASS（1/1） | 250.24 s | `PHASE18F_HEAVY_E2E_IMPORTED.xml` |
| 地铁入口 + `lbe_segment` | PASS（1/1） | 6523.45 s | `PHASE18F_HEAVY_E2E_LBE_SUBWAY.xml` |

三份 JUnit 的 `failures/errors/skipped` 均为 `0/0/0`。文件 SHA-256：

- explicit：`f14670c66e7dc5ed8d033fb3b617c3978a4dd87fc56ba8cc088f584822db72da`
- imported：`ac858cc43a4cc47fc1f3e7e7b227bdb16a169e7e9cdff4f7855879220a917a32`
- LBE/subway：`277700ba53d10c269ff2dd0e9874895b0457f3c43cff8c74d0fd0254b2afd445`

结论：Phase 18F 的 fresh heavy 软件证据门已经满足。地铁入口链路接近 1 小时 49 分钟，仍属于明确的
性能优化事项；本证据不代表工程验证或真实求解完成，所有产物继续保持 `solver_ready=false`、
`requires_project_review=true`。
