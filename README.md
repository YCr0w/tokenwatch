# tokwatch

跨宿主 AI coding CLI 的 **token 用量 / 配额查看器**。一个零依赖 Python 核心，自动适配 **Claude Code / OpenAI Codex / omp** 三个宿主。参考 `oh-my-claude`（状态栏框架）与 `ccusage`（多宿主归一化），只保留「用量 + 余量」这一件事。

```text
tokwatch/                    # 纯 Python 3.9+ 标准库，零第三方依赖
  tokwatch/core.py           # 统一数据模型 + 格式化
  tokwatch/render.py         # 状态栏单行 / CLI 报表 / 配额渲染
  tokwatch/cli.py            # 统一 CLI + statusline 入口
  tokwatch/sources/          # 三宿主适配器
    claude.py  codex.py  omp.py
  bin/tokwatch               # CLI（可 symlink 到 PATH）
  bin/tokwatch-claude-statusline  # Claude Code 状态栏入口
  install.py                 # 自动探测三宿主并安装
```

## 安装

一条命令，自动识别你机器上装了哪个 CLI，装到对应位置：

```bash
git clone https://github.com/YCr0w/tokenwatch && ./tokenwatch/install.py
```

`install.py` 会：

1. **自动探测** 三个宿主（按 CLI 二进制是否在 PATH、或配置/数据目录是否存在）；
2. **分宿主安装到各自真实位置**（幂等、不覆盖你现有配置）：

| 宿主 | 探测依据 | 安装位置 |
|---|---|---|
| Claude Code | `claude` 在 PATH，或 `~/.claude/` 存在 | `~/.claude/settings.json` → `statusLine.command` |
| omp | `omp` 在 PATH，或 `~/.omp/` 存在 | `~/.omp/agent/config.yml` → `statusLine`（原生 `usage` 段） |
| Codex | `codex` 在 PATH，或 `~/.codex/` 存在 | 无钩子可注册 → 用 `codex /status` + `tokwatch codex` |

3. 把 `tokwatch` CLI symlink 到 PATH 上的 bin 目录（优先 `~/.local/bin`）。

未检测到的宿主自动跳过，不报错。

```bash
python3 install.py --dry-run      # 只看会改什么，不写入
python3 install.py --only claude,omp   # 只装指定宿主
python3 install.py --uninstall    # 撤销注册
```

> 装完重启对应 CLI（或新开一个窗口），状态栏即可生效。装好后**别移动仓库**（statusline 命令用绝对路径指向 `bin/`）。

## 使用

```bash
tokwatch claude          # 聚合 ~/.claude 全部会话（token/成本/模型拆分）
tokwatch omp             # 聚合 ~/.omp 全部会话
tokwatch codex           # 聚合 ~/.codex 的 tokens_used（成本为估算）
tokwatch all             # 三宿主一起
tokwatch claude --json   # 机器可读
tokwatch codex --watch 5 # 每 5s 轮询（Codex/omp 这类无推送的宿主）
tokwatch omp --limits    # 原生配额窗口（5h/月，进度条 + 重置倒计时）
```

状态栏（Claude Code，每轮自动刷新）：

```
Opus ctx ▓▓▓▓░░░░░░ 42% (85k/200k) $4.56
```

实测输出（`tokwatch all`）：

```
[claude]
  tokens  in 17,944,636  out 414,970  cache_r 14,640,504  cache_w 0
  total   33,000,110 tokens  ·  $107.50  ·  sessions 41
  models:
    anthropic/Claude Sonnet 5.5  15,717,552   92,604        0        0     $80.90
    anthropic/DeepSeek-V4-Pro      432,762  208,926 10,586,752        0     $12.68
    ...

[omp]
  tokens  in 1,928,137  out 630,888  cache_r 120,256,119  cache_w 0
  total   122,815,144 tokens  ·  $12.16  ·  sessions 14
```

## 三宿主的「实时」机制差异

| 宿主 | 实时路径 | 数据源 |
|---|---|---|
| Claude Code | 每轮 `statusLine` 灌 stdin JSON（`context_window`/`cost`/`model`） | `~/.claude/projects/**/*.jsonl` 的 `cost-state` 行 |
| Codex | 无状态栏/hook → `--watch` 轮询 | `~/.codex/state_5.sqlite`（`threads.tokens_used`，input+output 合并不拆分） |
| omp | 内置 `usage` 段 + 原生 `omp usage` | `~/.omp/agent/sessions/**/*.jsonl` 的 `message.usage` 行 |

关键事实：**「token 用量」和「配额余量」是两个数据源**。

- 用量 → 本地 transcript（JSONL/SQLite）。
- 余量 → 宿主原生配额接口（Claude 订阅 5h/7d、Codex `/status`、omp `usage`），CLI 本地拿不到。

## 配置

| 环境变量 | 作用 |
|---|---|
| `TOKWATCH_CLAUDE_DIR` | Claude projects 目录（默认 `~/.claude/projects`） |
| `TOKWATCH_CODEX_DB` | Codex SQLite（默认 `~/.codex/state_5.sqlite`） |
| `TOKWATCH_OMP_DIR` | omp sessions 目录（默认 `~/.omp/agent/sessions`） |
| `TOKWATCH_BIN_DIR` | install 的 symlink 目标（默认 PATH 上的 `~/.local/bin`） |
| `TOKWATCH_COLOR=1` | 状态栏/报表开 ANSI 颜色 |

## 已知局限

- **Codex**：未真机验证（`threads.tokens_used` 为 input+output 合并，成本用 70/30 拆分 + 内置价表**估算**，未知模型记 $0）。配额依赖原生 `codex /status`。
- **成本口径**：Claude 成本来自 `cost-state.totalCostUSD`（走本地代理时是代理记账）；omp 成本来自 `message.usage.cost.total`。provider 账单始终是权威。
- **`usage` 段跟随激活 provider**：omp 的内置 `usage` 段只显示「当前激活 provider」的配额；若激活模型是本地代理（如 oneapi），该段为空。切到有配额的 provider（如 kimi-code）即显示。
- **余量**：订阅配额不在 CLI 本地文件里，不模拟 `oh-my-claude` 的 Chrome-cookie 方案；用宿主原生 `/status`、`omp usage` 或 provider 官方 quota 接口。

## License

[MIT](LICENSE)
