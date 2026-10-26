# 02 · 软件架构

## 1. 三层身体

```
┌──────────────────────────────────────────────────────────────┐
│  大脑  Cloud Brain（云端 / 家里的电脑）                          │
│  Claude Agent · 对话 · 规划 · 记忆 · 性格                       │
│  节拍：秒级   接口：Body API（tool use）                         │
└───────────────▲───────────────────────────────┬──────────────┘
                │ 事件 / 音频 / 关键帧            │ 工具调用（动作、语音）
                │ WebSocket (TLS)                │
┌───────────────┴───────────────────────────────▼──────────────┐
│  小脑  Edge Cerebellum（树莓派 / Jetson，阶段 2 起）             │
│  唤醒词 · VAD · ASR · 视觉 · 跟随 · 避障规划 · 本地降级            │
│  节拍：10–100 ms   接口：边缘-MCU 二进制协议                     │
└───────────────▲───────────────────────────────┬──────────────┘
                │ 传感器状态 100–200 Hz           │ 动作目标
                │ USB-CDC / UART                 │
┌───────────────┴───────────────────────────────▼──────────────┐
│  脊髓  MCU Spine（ESP32-S3）                                   │
│  电机 PID · 舵机动画 · LED · 触摸 · IMU · 反射 · 看门狗 · 安全      │
│  节拍：1–10 ms   接口：GPIO / I2S / I2C / PWM                   │
└──────────────────────────────────────────────────────────────┘
```

**阶段 0 和 1 没有小脑层**：ESP32 直接连云端，小脑的"反射"部分（避障、急停）暂时放在 MCU 里。阶段 2 加入边缘板后，MCU 只保留实时和安全职责。

分层的硬性原则：

1. **越往下，越不信任上面**。MCU 对任何来自上层的指令做范围检查和超时处理；云端说"全速前进"，MCU 会先问 ToF 前面有没有东西。
2. **闭环控制不跨网络**。轮速 PID 在 MCU，跟随在边缘，云端只说"跟着他"。
3. **每层都有"没有上层时的行为"**。断云 → 小脑维持基本互动；断边缘 → MCU 进入离线人格并停止运动。

## 2. Body API：LLM 怎么"用"身体

身体对 LLM 暴露为一组工具（Claude tool use）。工具是**高层意图**，不是电机指令。

```jsonc
// 阶段 0 的工具集
say        (text, emotion?)          // 流式 TTS 播放；可与动作并行
set_emotion(emotion, intensity?)     // happy | curious | sleepy | surprised | sad | annoyed | neutral
gesture    (name)                    // nod | shake | wiggle | look_up | look_down | flap
look_at    (direction)               // left | right | center | user（阶段 1 起为 sound_source / person）
sleep      ()                        // 进入低功耗待机
get_state  ()                        // 返回触摸 / 姿态 / 电量 / 网络质量，供模型决策

// 阶段 1 新增
move       (distance_cm, speed)      // 带超时与最大值，MCU 校验
turn       (degrees)
follow_sound()
stop       ()

// 阶段 2 新增
look_at    (person_id | object)      // 由边缘视觉解析
capture    ()                        // 返回一帧图给模型看
remember   (key, value) / recall(key)

// 阶段 3 新增
pick(object) / place(location) / push(object, direction)
```

关键设计：

- **动作与语音并行**。模型先调 `set_emotion`+`gesture`，再调 `say`。鸭子在 TTS 还没回来时已经开始动——这是掩盖延迟最有效的手段。
- **工具返回要快**。`gesture` 立即返回"已开始"，不等动作做完。
- **模型不需要知道舵机角度**。情绪 → 动画由 MCU 的状态机负责；换一个身体（鸭子 → 轮式机器人）只换状态机，工具定义不变。

## 3. 协议

### 3.1 设备 ↔ 云端（WebSocket over TLS）

一条长连接，混合二进制帧（音频）和 JSON 文本帧（控制）：

```
二进制帧：  [1B type][2B seq][payload]
  type 0x01 = 上行 Opus 音频（16 kHz 单声道，20 ms 一帧，~32 kbps）
  type 0x02 = 下行 Opus 音频（TTS）
  type 0x03 = 上行 JPEG 关键帧（阶段 1+）

文本帧（JSON）：
  ↑ {"t":"hello","dev":"duck-01","fw":"0.3.1","caps":[...]}
  ↑ {"t":"event","name":"touch","where":"head"}
  ↑ {"t":"state","batt":87,"rssi":-61,"pose":"upright"}
  ↑ {"t":"vad","on":true}
  ↓ {"t":"tool","id":"c1","name":"gesture","args":{"name":"nod"}}
  ↓ {"t":"tts","state":"start|end"}
  ↑ {"t":"tool_result","id":"c1","ok":true}
  ↓ {"t":"ota","url":"...","sha256":"...","ver":"0.4.0"}
  ↔ {"t":"ping"} / {"t":"pong"}（3 s 一次，连续 3 次丢失判定断线）
```

为什么选 WebSocket 而不是 MQTT：音频需要有序、低开销的流，一条连接就够；MQTT 更适合多设备 / 多订阅，阶段 4 再考虑。

为什么 Opus：16 kHz 语音 32 kbps 比 PCM 省 8 倍带宽，ESP32-S3 软编解码一帧 20 ms 音频约 2–4 ms，够用。

### 3.2 边缘 ↔ MCU（阶段 2 起，USB-CDC，二进制）

```
帧：[0xAA 0x55][len][msg_id][payload...][crc16]
MCU → 边缘  @200 Hz：编码器计数、IMU、ToF ×3、触摸、电量、舵机当前角
边缘 → MCU  @≤100 Hz：轮速目标 (vL, vR)、舵机目标角、LED 帧、情绪 id、心跳
```

MCU 100 ms 收不到心跳 → 电机停、舵机回中。

## 4. 语音链路与延迟预算

目标：说完话到鸭子开口 **P50 < 1.5 s**。

| 环节 | 典型耗时 | 手段 |
|---|---|---|
| 端点检测（判断你说完了） | 300–600 ms | 设备端 VAD（阶段 0 用 WebRTC VAD / ESP-SR），尾部静音阈值可调 |
| 音频上行 | 20–100 ms | Opus 分帧边说边传，不等说完 |
| ASR | 200–600 ms | 流式 ASR，说话过程中已出中间结果 |
| LLM 首 token | 400–1200 ms | 流式；system prompt 用 prompt cache；先出工具调用再出文本 |
| TTS 首音频块 | 150–400 ms | 流式 TTS，按句切分，首句短 |
| 音频下行 + 播放缓冲 | 100–200 ms | 200 ms 抖动缓冲 |
| **合计** | **1.2–3.1 s** | 用动作填充前 0.5–1 s，主观感受减半 |

打断（barge-in）：鸭子说话时你开口，它要停。这要求麦克风听到的喇叭声被消掉——**硬件 AEC**（ESP32-S3-BOX-3 的 ES7210 + 参考通道）比软件 AEC 省心很多，这是选它的核心原因。

## 5. 云端大脑内部

```
cloud/
  gateway/     WebSocket 接入、设备认证（预共享 token → 阶段 2 换 mTLS）、会话管理
  voice/       ASR 适配层（可换：云 ASR / 本地 sherpa-onnx）、TTS 适配层
  brain/       Claude Agent：system prompt（性格）、工具注册、流式解析、并行动作调度
  memory/      短期对话窗口 + 长期事实（SQLite 起步）
  telemetry/   每轮延迟分解、错误、设备状态
```

Agent 循环（每一轮）：

1. 收到 ASR 最终文本 + 当前 `get_state` 快照 → 组装消息
2. 流式调用 Claude；解析到工具调用立即下发（不等整段回复）
3. 文本 token 按句子边界切给 TTS；TTS 音频块直接转发给设备
4. 结束后写记忆、记延迟

## 6. 固件内部（阶段 0）

```
FreeRTOS 任务：
  audio_in   (core1, 高优先级)  I2S 读 → AEC → VAD → Opus 编码 → 发送队列
  audio_out  (core1, 高优先级)  接收队列 → Opus 解码 → 抖动缓冲 → I2S 写
  net        (core0)            WebSocket 收发、重连、心跳
  body       (core0, 50 Hz)     情绪状态机 → 舵机缓动 + LED 动画；处理 gesture 队列
  sense      (core0, 20 Hz)     触摸、IMU、电量采样 → 事件
  supervisor (core0, 1 Hz)      看门狗喂狗、断网判定、离线人格切换、过温检查
```

离线人格：没有云端时 `body` 任务按本地脚本循环（眨眼、偶尔左右看、被摸发出预录的"嘎"），让它看起来"在"。

## 7. 没有硬件时怎么开发：软件鸭

`sim/` 里的软件鸭实现与真鸭完全相同的 WebSocket 协议：电脑麦克风 → Opus → 云端；云端下来的工具调用打印在终端 / 画在网页上。
云端代码对二者无感。阶段 0 的 M0 就是让软件鸭和云端先聊起来。

## 8. 技术选型小结

| 层 | 选择 | 备选 | 理由 |
|---|---|---|---|
| MCU 框架 | ESP-IDF 5.x (C) | Arduino / PlatformIO | 需要 ESP-SR（AEC/VAD/唤醒）、精细控制 FreeRTOS 任务 |
| 音频编码 | Opus 16 kHz | PCM / ADPCM | 带宽与质量平衡，生态成熟 |
| 传输 | WebSocket + TLS | MQTT、WebRTC | 一条连接搞定音频与控制；WebRTC 对 MCU 太重 |
| 云端语言 | Python 3.12 + FastAPI | Node / Go | 语音、模型生态都在 Python |
| LLM | Claude（tool use + streaming） | — | 工具调用稳定、流式好 |
| 边缘 | Python + ONNX Runtime | ROS 2 | 阶段 2 先轻量，阶段 3 评估 ROS 2 |
| CAD | FreeCAD / Onshape 导出 STEP + STL | Fusion 360 | 开放格式便于协作 |
