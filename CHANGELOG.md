# 更新日志

## 2026-11-06 — 首个开源版本

从「一个本地看一眼插件列表的小脚本」长成「带 3D 记忆星系的本地控制台」，一天之内。

### 新增

**面板**
- 7 个面板：概览 / 插件 / 技能 / 记忆 / 成本 / ArtCraft / 工具开销
- `PANELS` 注册一行就多一个面板，前端自动生成导航

**记忆银河系**（最花时间的部分）
- three.js 把记忆库映射成 3D 螺旋星系：核球 = 重要度最高，旋臂 = 按类型分组，亮度 = 活跃度
- 对数螺旋 `r = 1.8·e^(0.62θ)`，旋臂内黄白（年老恒星）→ 外蓝白（年轻恒星）
- 480 个四周小星系，用单个 ShaderMaterial 实现「每个绕自身中心自转」
  （`aCenter` / `aPhase` / `aSpeed` 三个自定义属性，1 次 draw call）
- 核球四层叠加：纯白内核 + 暖橙中晕 + 淡橙外晕 + 8 芒衍射星
- 星云气体层 1100 个细颗粒，颗粒感而非糊成一片

**插件管理**
- 开关：从 `profile.bundles` 摘掉/加回，写前自动备份 `package.json.bak-时间戳`
- 参数：可视化表单直接改 JSON（滑块 / 开关 / 文本框）
- 自动发现配置文件：插件目录 `*.config.json` 或 `~/.dsh/<名字>.json` 等
- 自动推断字段：`bool→开关`、`number→滑块`、`string→文本框`、嵌套对象展开两层
- 卸载：确认警告窗 → 只改配置，不删 node_modules

**ArtCraft**
- 14 个成员应用的安装状态与启用开关（改 `artcraft.config.json` 的 bins）

**主题系统**（4 套，可扩展）
- 科技风 / 赛博朋克 / 黑客 / 清爽风
- 切换时通过 `postMessage` 联动 DSH 侧边栏的入口按钮
- 加第五套：`THEMES` 加一项 + 一段 CSS + 一组按钮配色

### 修复 / 踩过的坑

| 问题 | 原因 | 解法 |
|---|---|---|
| 星点全都不显示，只剩核球 | 自定义着色器里 `attribute vec3 color` 与 three.js 内置属性重名，编译失败 | 改用 `aColor` 前缀，并去掉 `vertexColors` |
| 下拉菜单被卡片盖住、点不到 | `header` 的 `backdrop-filter` 自建层叠上下文，还会成为内部 `fixed` 的 containing block | 菜单 DOM 直接挂 `body`，`z-index` 提到 2147483000 |
| 记忆面板卡在「读取中…」 | 重构主题时整块替换代码，把 `kindColor` / `cssVar` / `isTactical` 三个函数一起删了 | 补回函数，并给 `renderMemory` 包 `try/catch` 显示错误 |
| 银河系点星卡顿 | `mousemove` 里每次调 `getBoundingClientRect()` 强制重排 + 每帧投影全部记忆点 | rect 缓存 + 命中检测 55ms 节流 |
| 星芒不动，看着很假 | `THREE.Sprite` 永远正对相机，不参与 3D 旋转 | 用 `material.rotation` 让它缓慢自转 |
| 黑客主题侧边栏还是紫的 | 颜色映射写成了 `#10,8,30`，但 CSS 里是 `rgba(16,8,30,...)`，没匹配上 | 按 `rgba(...)` 形式重新替换 |

### 开源

- 仓库：https://github.com/tianyadadi/dsh-workbench
- MIT 协议
- 路径全部改成「config.json > 环境变量 > 自动探测」三级，别人克隆即可用
- `config.json` 和 `.gh-token` 在 `.gitignore` 里

### 数字

| 项 | 数量 |
|---|---|
| 面板 | 7 个 |
| 主题 | 4 套 |
| 银河系粒子 | 约 4 万 |
| draw call | 7 次左右 |
| 第三方依赖 | 0（three.js 已本地化） |
| 运行时 token 消耗 | 0 |
