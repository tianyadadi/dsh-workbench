# DSH 工作台（dsh-workbench）

> DeepSeek Harness 的本地可视化面板 —— **零依赖、零联网、零 token**。

一个单文件 Python 服务 + 单页前端，把 DSH 的插件、技能、记忆、成本、ArtCraft 应用全部可视化出来。
打开就看不消耗任何 token，因为它只读本地文件，从不调用模型。

> 截图放在 `docs/screenshot.png`，你自己截一张放进去即可。

## 特性

- **7 个面板**：概览 / 插件 / 技能 / 记忆 / 成本 / ArtCraft / 工具开销
- **记忆银河系**：把记忆库映射成 3D 螺旋星系（three.js + 自定义着色器）
  - 核球 = 重要度最高的记忆，旋臂 = 按类型分组，亮度 = 活跃度
  - 480 个自转小星系、星云气体层、8 芒星核球
- **插件开关**：从 `profile.bundles` 摘掉/加回，自动备份
- **插件参数**：可视化表单直接改 JSON 配置（滑块、开关）
- **插件卸载**：带确认警告窗
- **ArtCraft 开关**：控制 14 个成员应用是否可用
- **4 套主题**：科技风 / 赛博朋克 / 黑客 / 清爽风，一键切换，入口按钮联动
- **零第三方依赖**：只用 Python 标准库；three.js 已本地化到 `lib/`

## 安装

```bash
git clone https://github.com/tianyadadi/dsh-workbench.git
cd dsh-workbench
```

需要 Python 3.8+，不需要 pip install 任何东西。

## 配置

复制 `config.example.json` 为 `config.json`，把路径改成你自己机器上的：

```json
{
  "modules_dir": "C:/Users/你的用户名/.dsh/node_modules",
  "memory_dir": "C:/Users/你的用户名/.dsh/memory",
  "artcraft_dir": "C:/Users/你的用户名/.dsh/artcraft",
  "runtime_dir": ""
}
```

| 字段 | 说明 | 不填会怎样 |
|---|---|---|
| `modules_dir` | DSH 插件的 node_modules 目录 | 插件面板空 |
| `memory_dir` | 记忆库目录（含 `index.sqlite`） | 记忆面板空 |
| `artcraft_dir` | ArtCraft 安装目录 | 显示未安装 |
| `runtime_dir` | DSH 运行时目录（只读版本号） | 显示 `?` |
| `dsh_home` | 默认 `~/.dsh` | 用默认值 |

也可用环境变量：`DSH_MODULES_DIR` / `DSH_MEMORY_DIR` / `DSH_ARTCRAFT_DIR` / `DSH_RUNTIME_DIR`。

## 启动

**Windows**：双击 `start.cmd`

**Linux / macOS**：

```bash
chmod +x start.sh
./start.sh          # 默认 8799 端口
./start.sh 9000     # 指定端口
```

或者直接：

```bash
python server.py --port 8799
```

打开 http://127.0.0.1:8799

## 插件参数（自动发现）

点插件行的 **⚙** 就能改配置。**不需要事先配置**，规则如下：

1. **找配置文件**（按顺序）：
   - 插件目录内的 `*.config.json` / `config.json` / `settings.json`
   - `~/.dsh/<名字>.json`、`~/.dsh/.<名字>.json`、`~/.dsh/.<名字>-config.json` 等
2. **推断表单**：读 JSON 后按值类型自动生成控件
   - `true/false` → 开关
   - 数字 → 滑块（0~1 用 0.05 步进，端口这类大数用 500）
   - 字符串 → 文本框
   - 嵌套对象 → 展开成 `a.b` 两级（比如 `bins.photocraft`、`control.filmcraft`）
3. **保存**：按路径写回嵌套结构，写前校验 JSON 并备份 `.bak-时间戳`

> 想给某个插件定制中文标签和字段顺序，在 `server.py` 的 `PLUGIN_FIELDS` 里加一张表即可（手工表优先于自动推断）。

## 面板说明

| 面板 | 内容 |
|---|---|
| 概览 | 插件数、技能数、记忆数、工具定义 token、会话花费、磁盘占用 |
| 插件 | 包名、用途、工具数、体积、启用状态、开关、参数、卸载 |
| 技能 | 技能目录、来源、描述 |
| 记忆 | 列表 + 3D 银河系 / 平面星图两种视图 |
| 成本 | 工具定义 token 明细、开销排行 |
| ArtCraft | 14 个成员应用的安装状态与启用开关 |
| 工具开销 | 每个工具的定义 token 估算 |

## 扩展面板

在 `server.py` 的 `PANELS` 里加一行：

```python
PANELS = [
    ("overview", "概览", scan_overview),
    ("my-panel", "我的面板", scan_my_panel),   # ← 加这行
]
```

再写一个返回 dict 的 `scan_my_panel()`，前端自动生成导航和页面，不用改 HTML。

## 主题

顶栏右上角切换，四套主题：

| 主题 | 风格 |
|---|---|
| 科技风 | 深蓝 + 天青 + 靛蓝，HUD 切角 |
| 赛博朋克 | 深空紫 + 霓虹青 + 品红 |
| 黑客 | 墨黑 + 荧光绿 + CRT 扫描线 |
| 清爽风 | 深蓝 + 青色 + 圆角 |

加第五套：`THEMES` 数组加一项 + 写一段 `body.theme-xxx` CSS + 给入口按钮加一组配色。

## 设计原则

- **只读本地文件**：不联网、不上传、不调用模型
- **改配置前自动备份**：`package.json.bak-时间戳`
- **卸载只改配置**：不删 node_modules 里的文件，重装可复用缓存
- **面板可插拔**：`PANELS` 注册一行即可

## 更新日志

见 [CHANGELOG.md](CHANGELOG.md)。

## License

MIT
