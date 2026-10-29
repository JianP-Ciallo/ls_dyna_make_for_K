# 三层建筑简化爆炸演示交付

按本次用户的三张参考图，直接建简化三层住宅并跑通爆炸过程。独立于旧K模型、OpenSees材料链路和自重预平衡；旧原生修改及历史结果保留。

## 打开与操作

本机预览：<http://127.0.0.1:8917/blast_demo.html>。静态预览服务只绑定127.0.0.1，服务信息在`artifacts/simple-blast-demo-20261024-01/server-live.json`。已有场景页面新增进入演示的链接。

调整橙色爆源位置和参考当量，点击“开始爆炸模拟”；完成后自动播放。可以暂停、拖动时间轴、调整速度、切换损伤着色、隐藏屋面、保存图片、下载建筑几何和计算结果JSON。修改输入会清空旧回放，停止按钮会终止当前Worker。

如果静态预览服务已经关闭，在项目根目录启动：

```powershell
python -B -m http.server 8917 --bind 127.0.0.1 --directory lsprepost_mcp/web/static
```

静态预览用于本次独立演示，原计算与历史记录仍由原Web服务提供。

## 本次模型与计算

- 三层，主体16.8 × 12.0 m，含屋顶小间最高10.66 m；1465个有体积的盒构件，含楼板、柱、内外墙、门窗洞口、双侧阳台、楼梯及屋顶构件。
- 根据爆点距离、方向、参考强度计算简化冲击与构件失效，支承丧失可触发脱落。独立Worker以1/180秒步长积分，输出30帧/秒的实际构件位置、姿态和无量纲损伤值。
- 脱落后计算平移、转动、重力下落及简化地面碰撞。烟尘、闪光和扩散环为视觉效果；零爆源时全部关闭。
- 本版是有体积构件的简化动力学演示，尚不是实体有限元分析。未求解爆炸流场、钢筋应力、真实材料本构、构件之间的接触碰撞，也不以参考当量推导工程超压或承载结论。

## 验收证据

真实Chrome完成默认6秒过程，计算用时0.37秒，102个构件脱落；600 kg参考强度下242个构件脱落。此处参考强度用于演示参数，破坏数量不是工程预测。

1. 纯JS专项8组通过：三层几何和洞口、外部爆源校验（含屋顶禁入边界）、零作用静止、强度和距离敏感性、确定性、有限数值和姿态归一化、完整计算历程。3秒对比中5 kg近处/160 kg近处/160 kg远处分别为0/102/0个脱落构件。
2. 真实Chrome的13项检查通过：几何呈现、Worker实际计算、回放与损伤、几何/结果下载解析、重置、参数失效、取消竞态、内部爆源拒绝、零爆源无特效（画布像素一致）、配置恢复、移动宽度、无旧API调用、无浏览器异常。
3. `python -B -m pytest tests/test_simple_blast_demo.py tests/test_web_build.py -q`：2 passed。首次打包检查受沙箱Node realpath EPERM限制；同样两项在允许访问源码目录后通过，未扩大测试范围。
4. 独立只读审查无阻塞项，零当量特效、累计位移标签、屋顶爆源禁入体积三项建议均处理。屋顶回归先观察失败，再修复并通过上述纯JS及pytest专项。

日志、下载JSON及截图位于`artifacts/simple-blast-demo-20261024-01/`。关键证据：

- [初始建筑](../../../artifacts/simple-blast-demo-20261024-01/browser-final/01-building.png)
- [爆炸后构件运动](../../../artifacts/simple-blast-demo-20261024-01/browser-final/02-blast-motion.png)
- [强烈作用演示](../../../artifacts/simple-blast-demo-20261024-01/browser-final/04-strong-blast.png)
- [浏览器检查](../../../artifacts/simple-blast-demo-20261024-01/browser-final/checks.json)
- [专项pytest日志](../../../artifacts/simple-blast-demo-20261024-01/pytest-scoped-verified.log)
- [动力学专项日志](../../../artifacts/simple-blast-demo-20261024-01/runtime-verified.log)

## 保留与清理

旧材料运行时保护清单中的462个文件及上次整栋验收清单的24条记录（含报告）哈希检查通过；原有6处材料源码修改仍保留。核对脚本只读取旧证据，结果写入本轮`preservation-verified.json`。

未运行旧整栋自重、13单元、原生TNT、全量或其他重型测试。清理仅涉及本次生成的6个浏览器临时配置、1个启动探测目录和2个pytest临时目录，回收171,679,013字节；日志、截图、下载结果和旧历史均保留。清理记录在本轮`cleanup.json`。

新增代码为`blast_demo.html/css/js`、`blast_demo_model.js`、`blast_demo_worker.js`、`blast_demo_view.js`；专项入口为`web/tests/blast-demo.runtime.cjs`、`tests/browser/blast_demo.cjs`及`tests/test_simple_blast_demo.py`。未提交或合并用户工作区。
