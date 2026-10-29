# 按原设计恢复四类独立爆炸演示

本轮按用户纠正，先读取既有外观、批准图及默认布局，再构建商超、住宅小区、地铁入口和城市街道。主目录现在是原三层住宅加上述四类；此前误建的四种楼型放入“保留的额外楼型示例”，原 URL、配置和历史结果保留。

目录：<http://127.0.0.1:8917/blast_buildings.html>。四类场景各自打开、计算和导出，互不覆盖。住宅小区自身三塔和城市自身多建筑布局遵循原设计。

## 已读取的依据

- [五类场景需求](../specs/2026-10-22-scene-cpu-blast-simulator-design.md)、[详细资产设计](../specs/2026-08-09-phase18d-detailed-building-asset-library-design.md)及三个详细资产的 `asset.json`。
- [地铁批准基线](../specs/2026-08-09-phase18d-subway-entrance-approved-baseline.md)、[实际查看的批准图](../../assets/phase18d/subway_entrance_cn_generic_A_approved_2026-08-09.png)，并核对 `refined_building/asset_compiler.py` 和 `asset_templates.py`。
- [城市原布局说明](../../reviews/city-street/CITY_STREET_BLAST_SCENE.zh-CN.md)，并核对 `component_library.py`、`dyna_assembly.py`、`city_street_blast.py` 的默认几何及既有预览截图。

历史文档中的旧验收、暂停和生成流程仅作为背景；本轮没有由此启动旧求解或模型生成。

## 外观与演示结果

以下是本次真实 Edge 验收导出的 6 秒简化演示；每项181帧。破坏数量属于演示模型，与工程破坏预测无对应保证。

| 独立入口 | 恢复的外观与布局 | 构件数 | 脱落数 | 本次计算耗时 |
|---|---|---:|---:|---:|
| [商超](http://127.0.0.1:8917/blast_demo.html?building=commercial_supermarket) | 22×18×8 m，入口、雨棚、立面柱、招牌、屋顶设备间及内部销售/仓储/后勤分区 | 758 | 91 | 2.01 s |
| [住宅小区](http://127.0.0.1:8917/blast_demo.html?building=residential_community) | 3塔，每塔8×10×18 m，净距4 m；三条阳台带、低基座、屋顶机房 | 4995 | 644 | 6.85 s |
| [地铁入口](http://127.0.0.1:8917/blast_demo.html?building=subway_entrance) | 浅弧金属屋面、玻璃亭体，1组楼梯与2组并排扶梯，共用下平台→独立直通空腔通道→接口 | 230 | 109 | 1.46 s |
| [城市街道](http://127.0.0.1:8917/blast_demo.html?building=city_street) | 72×72 m，16 m十字道路；西北商超、西南两塔、东北原轻量入口、东南四车停车场，四信号灯按0/90/180/270°布置 | 3184 | 33 | 3.42 s |

独立地铁的6 m下降水平段、6.9 m亭体、8.4 m总路线及2.8 m高差取自既有代码默认值；批准外观图不提供工程尺寸。演示以上平台为地面零标高，下通道行走面为−2.8 m。地下箱体、楼梯及扶梯是固定参考结构；玻璃亭和屋面参与简化破坏，可切换地下剖视。城市入口保留原街区合同的6×4 m三面围护轻量版本，与独立批准入口分别建模。

为避免旧整块基座填满首层，低基座改为带门洞的空心周边与薄底板，保留轮廓。墙面、开口、构件分片、支承连接和材料外观均是轻量表达，不声称完整复刻原细网格或配筋。当前使用体积构件、简化冲击/连接失效、飞散运动和地面接触；未计算气流遮挡、碎片互撞或实体有限元材料响应。烟尘用于视觉表现。

## 专项验收与保存证据

- 最终 `python -m pytest tests/test_simple_blast_demo.py tests/test_web_build.py -q`：**4 passed，5.36 s**，含原三层、此前额外楼型、新四类几何与短程动力学、静态构建。新场景12组检查含门洞空腔、坡屋顶覆盖、姿态初始化、柱顶/墙顶支承、信号连接、零作用静止、有限响应。
- 四类场景真实 Edge：**30项通过**，验证实际几何预览、Worker计算、181帧结果导出、飞散及落地时刻回放、独立配置与结果、原三层兼容、窄屏和无原生API调用。另原三层 Edge专项**13项通过**。
- 独立只读复核未发现剩余阻塞问题；补充了基座前墙门洞探针后复跑上述4项专项，通过。
- 已打开可见 Edge 目录；实际桌面截图确认显示正常。采集时用户已打开地铁入口，未干预其操作。
- 未运行旧整栋自重、13单元、原生TNT、全量、ALE/FSI或其他重型测试，也未启动旧WebAppServer。

证据目录：`artifacts/original-scenes-blast-demo-20261024-01/`。`browser-final/checks.json` 保存30项检查及统计，`browser-final/downloads/` 保存四场景几何和完整历史，`browser-final/*.png` 保存初始/飞散/落地截图，`visible-catalog-desktop.png` 保存实际可见桌面（当时已切到地铁）。`pytest-reviewed.log`、`original-edge.log` 保存专项日志。此前调试失败与中间轮次的日志也保留。

`source-before/`及哈希索引保留本轮前8个静态文件快照。保护核对确认此前462个索引文件、6项既有原生修改及最近整栋运行24项证据未改变。只清理本轮退出的无界面浏览器临时配置和pytest打包临时目录；可见Edge配置、模型导出、日志、截图及历史结果均保留。最终文件索引见本轮 `evidence-manifest.json`。
