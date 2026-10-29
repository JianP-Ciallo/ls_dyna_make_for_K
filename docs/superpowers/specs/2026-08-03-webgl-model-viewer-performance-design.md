# WebGL 主展示窗口性能优化设计

## 背景

城市破坑 V5 模型包含 293,531 个节点和 274,856 个单元。当前浏览器预览会生成约 36,482 个可见表面和 73,062 条边。后端构建预览约需 0.9 秒，序列化数据约 2.25 MB；持续卡顿来自主窗口 Canvas 2D 渲染器在每次鼠标移动时重新投影、深度排序并逐面填充和描边。

Phase17 编辑器已经使用 Three.js/WebGL，但导入项目后的主展示窗口仍使用 Canvas 2D。两套渲染路径没有共享 GPU 能力。

## 目标

- 将导入项目后的主展示窗口迁移到 Three.js/WebGL。
- 所有预览网格边线在旋转、平移和缩放期间始终显示。
- 在 1920x1080、普通集成显卡上，V5 交互帧率不低于 30 FPS。
- V5 冷加载到可交互不超过 2 秒，缓存命中后不超过 0.5 秒。
- 保留部件选择、隐藏、隔离、风险着色、爆源、预设视角和全屏功能。
- 不修改 model.k、model.json、checks.json 或任何求解结果。

## 非目标

- 本阶段不在浏览器直接读取或渲染 d3plot。
- 不通过删边、抽稀、LOD 或交互时隐藏边线换取性能。
- 不重构 Phase17 编辑器的 TransformControls 交互。
- 不改变 LS-DYNA、LS-PrePost、导入、导出或求解证据契约。

## 架构

主页面继续从 `/api/project/preview-mesh` 获取现有预览协议。新增 `model_viewer_webgl.js`，负责 Three.js 场景、相机、OrbitControls、GPU 几何、拾取和资源生命周期。`app.js` 保留业务状态和任务面板，只通过稳定接口驱动渲染器。

每个可见部件创建一个 `THREE.Group`，包含一个表面 `THREE.Mesh` 和一个完整边线 `THREE.LineSegments`。表面使用索引化 `BufferGeometry`；边线把后端 `part.edges` 直接展开为专用顶点缓冲。禁止使用会省略共面边的 `EdgesGeometry`。

交互不再重建几何。OrbitControls 变化只使渲染器失效，并通过 `requestAnimationFrame` 将同一帧内的高频输入合并为一次渲染。静止时停止连续渲染。

## 前端接口

`createModelViewer(options)` 返回以下接口：

```javascript
{
  supported,
  loadModel(preview, state),
  setPartVisible(partId, visible),
  setSelectedParts(primaryPartId, impactPartIds),
  setDisplayMode(mode),
  setRiskColors(riskByPartId),
  setBlastSourcesVisible(visible),
  fitView(preset),
  resize(),
  dispose(),
  getMetrics(),
}
```

Viewer 通过 `onPartSelected(partId)` 回调通知 `app.js`。业务状态仍由 `app.js` 持有，避免 Three.js 对象成为业务数据源。

## 几何和材质

- `part.nodes` 转换为 `Float32BufferAttribute`。
- `part.faces` 扇形三角化后写入索引缓冲。
- `part.edges` 展平为成对索引，供 `LineSegments` 使用。
- 位置属性只在加载模型时构造。
- 表面材质使用 `MeshStandardMaterial`，边线使用 `LineBasicMaterial`。
- 网格材质启用 polygon offset，避免边线与表面闪烁。
- 显示模式仅控制 Mesh 和 LineSegments 的可见性，不删除 GPU 资源。
- 选择和风险等级仅更新颜色、透明度和 renderOrder。

## 相机和交互

- 使用 PerspectiveCamera 和 OrbitControls。
- 关闭需要持续动画的 damping，保持按需渲染。
- Raycaster 只拾取 Mesh，不拾取边线。
- 项目切换、预设视角和全屏后调用 `fitView` 或 `resize`。
- 渲染像素比为 `min(devicePixelRatio, 1.5)`；这不减少节点、面或边线。

## 后端缓存

新增有界 LRU 缓存，键包含：

- 预览协议版本。
- model.k SHA256。
- model.json SHA256，文件不存在时使用固定空值。

缓存最多保留 4 个项目，并设置总序列化体积上限 16 MiB。文件哈希变化自动形成新键。缓存只保存预览返回值，不写入项目目录，也不参与求解证据。

## 并发和生命周期

- 浏览器切换项目时使用 AbortController 取消旧预览请求。
- 只允许最新请求写入 Viewer。
- 切换模型前递归 dispose 几何和材质。
- WebGL context lost 时阻止默认销毁、暂停渲染并显示现有状态提示。
- context restored 后从内存中的当前预览数据重新构建 GPU 资源。
- 无 WebGL 时保留现有 Canvas 2D 路径作为兼容回退。

## 性能验收

- V5 完整边线数量在加载前后和交互期间保持一致。
- V5 可见部件的主要 draw calls 不超过 `2 * visible_parts + 8`。
- 5 秒连续旋转测试中，平均帧率不低于 30 FPS，95% 帧耗时不超过 50 ms。
- 冷加载不超过 2 秒，缓存加载不超过 0.5 秒。
- 连续切换 10 次后，Three.js geometry 和 material 计数不持续增长。
- 桌面和移动视口截图非空，模型不越界，控件不重叠。

## 兼容与回退

默认使用 WebGL。查询参数 `viewer=canvas` 可强制进入旧 Canvas 路径，用于诊断和紧急回退。回退路径不承担大模型性能指标。WebGL Viewer 稳定后再单独决定是否删除 Canvas 实现。

## 风险

- Windows WebGL 对线宽支持有限，因此边线固定为 1 物理像素附近，不依赖宽线扩展。
- 集成显卡性能受浏览器、电源模式和窗口分辨率影响，性能验收必须记录设备与浏览器信息。
- JSON 对未来百万级可见面模型可能成为瓶颈，但 V5 当前仅约 2.25 MB，本阶段不引入二进制协议。
