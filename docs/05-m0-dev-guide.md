# 05 · M0 开发指南：在电脑上跑通软件鸭

> 目标：不需要任何硬件，在自己的电脑上启动云端大脑，再用终端里的软件鸭和它聊天，看到完整的工具调用和每段延迟。
> 对应里程碑见 [`04-phase0-duck.md`](04-phase0-duck.md) §4 M0。

## 1. 安装

需要 Python 3.12 或更高版本（项目开发使用 3.13）。在仓库根目录执行：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

`[dev]` 会额外安装 pytest 和 pytest-asyncio，跑测试需要它们。

之后每次开新终端都要先激活虚拟环境：`. .venv/bin/activate`。

## 2. 密钥

云端大脑调用 Claude API，启动前必须让进程能拿到密钥。二选一：

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # 方式一：环境变量
```

或者用 `ant auth login` 登录并使用对应的 profile（方式二）。两种方式都不要把密钥写进仓库里的文件。

## 3. 环境变量

所有配置都在 `embody/cloud/config.py` 里读取，这是唯一的来源。没有设置的变量使用默认值。

| 变量 | 默认值 | 含义 |
|---|---|---|
| `EMBODY_HOST` | `0.0.0.0` | 云端监听的地址 |
| `EMBODY_PORT` | `8765` | 云端监听的端口，WebSocket 路径是 `/ws` |
| `EMBODY_DEVICE_TOKEN` | 空 | 设备连接时必须出示的预共享口令；为空表示不鉴权（只适合局域网开发） |
| `EMBODY_MODEL` | `claude-opus-5-5` | 对话使用的模型 |
| `EMBODY_EFFORT` | `low` | 推理力度；聊天场景延迟优先，所以默认低 |
| `EMBODY_MAX_TOKENS` | `2048` | 单轮回复的最大 token 数 |
| `EMBODY_FALLBACKS` | `1` | 是否启用服务端的拒答降级；如果代理不支持该 beta，设为 `0` |
| `EMBODY_HISTORY_TURNS` | `20` | 每轮对话带给模型的历史条数 |
| `EMBODY_PERSONA` | `duck` | 系统提示里使用的人格名 |
| `EMBODY_DB` | `embody.sqlite3` | SQLite 数据库文件路径（记忆与对话历史） |
| `EMBODY_PING_S` | `3` | 心跳间隔（秒） |
| `EMBODY_PING_MISSES` | `3` | 连续丢失多少次心跳后判定连接断开 |
| `EMBODY_LOG` | `INFO` | 日志级别 |

软件鸭还会读取 `EMBODY_DEVICE_TOKEN`，作为 `--token` 的默认值。

## 4. 启动云端大脑

```bash
embody-cloud
```

启动后可以用 `curl http://127.0.0.1:8765/healthz` 检查服务是否正常。

云端会在当前目录下创建 `embody.sqlite3`（可以用 `EMBODY_DB` 改位置）。删掉这个文件就等于清空了记忆和对话历史。

## 5. 启动软件鸭

另开一个终端（同样先激活虚拟环境），执行：

```bash
embody-duck --url ws://127.0.0.1:8765/ws
```

常用参数：

- `--id`：设备编号，默认是 `sim-<主机名>`。
- `--token`：设备口令，要和云端的 `EMBODY_DEVICE_TOKEN` 一致。
- `--quiet`：只打印鸭子说的话和错误。

直接输入文字即可和鸭子聊天。以斜杠开头的是控制命令：

| 命令 | 作用 |
|---|---|
| `/touch [where]` | 摸鸭子，`where` 默认是 `head` |
| `/pickup` | 把鸭子拿起来（姿态变为 `picked_up`） |
| `/putdown` | 放回桌面 |
| `/tilt` | 让鸭子倾斜 |
| `/vad on` / `/vad off` | 假装开始 / 停止说话，用来测试语音活动检测的上行 |
| `/state` | 打印鸭子当前状态，并发送一帧 `state` |
| `/help` | 列出所有命令 |
| `/quit` | 退出（Ctrl-C、Ctrl-D 也可以） |

鸭子的动作不会真的发生在硬件上，而是打印在终端里。例如模型调用 `set_emotion` 时，终端会显示一行工具调用。

## 6. 跑测试

```bash
pytest -q
```

测试不调用 Claude API，不需要密钥；网关和软件鸭的测试只在本机回环地址上启动临时服务。`pyproject.toml` 已经把 `asyncio_mode` 设为 `auto`，异步测试直接写 `async def` 即可。

## 7. 读懂延迟日志

每轮对话结束时，云端会在 `embody.telemetry` 这个 logger 里打印一行 INFO 日志，形如：

```
turn device=duck-01 llm_first_token=812ms first_say=1340ms total=2210ms
```

字段含义（均为从这一轮开始计时的毫秒数）：

| 字段 | 含义 |
|---|---|
| `llm_first_token` | 模型流式输出第一个 token |
| `llm_first_tool` | 模型发出第一个工具调用 |
| `first_say` | 第一句话发给了鸭子（用户感知到的"开口"时间） |
| `total` | 本轮结束的总耗时 |

此外，大脑还会在 `utterance_end`、`asr_done`、`tts_first_audio`、`turn_end` 等环节打点（见 `embody/cloud/ports.py`）。日志行只包含本轮真正打过点的字段，`total` 总是有。

看延迟时重点关注 `first_say`：它决定鸭子"开口"有多快。M0 阶段先把数字记下来，M3 之后的"先动再说"优化都以它为基准。

在代码里可以通过 `LatencyTelemetry.summary()` 拿到最近 200 轮的 p50 / p95（`first_say` 和 `total`）。

## 8. M0 验收清单

对应 [`04-phase0-duck.md`](04-phase0-duck.md) §4 M0：

- [ ] `cloud/`：WebSocket 网关 + Claude Agent + 工具定义 + ASR/TTS 适配
- [ ] `sim/`：电脑端软件鸭，麦克风进、喇叭出，工具调用打印到终端
- [ ] 验收：和软件鸭聊 10 轮，终端能看到 `set_emotion` / `gesture` / `say` 的调用顺序和每段延迟

注意：`say` 不是工具。模型输出的文字就是鸭子说的话，大脑把它切成句子后以 `say` 帧发给鸭子。所以"调用顺序"里的 `say` 指的是这些句子出现的位置，而不是一次工具调用。
