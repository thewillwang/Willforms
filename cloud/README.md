# cloud/

云端"大脑层"。

职责：

- LLM Agent：把身体暴露成一组工具（`say`、`look_at`、`move`、`set_emotion`、`gesture`…），模型通过 tool use 驱动身体
- 语音编排：ASR → LLM（流式）→ TTS（流式），尽量把首个音频块压到 1 秒内
- 记忆：对话记忆、对人 / 环境的长期记忆
- 设备接入：WebSocket 网关、设备认证、OTA 固件分发
- 观测：每轮对话的端到端延迟分解（ASR / TTFT / TTS / 网络）落日志

技术栈：Python 3.12 + FastAPI + WebSocket；LLM 使用 Claude API（tool use + streaming）。
部署形态阶段 0 先跑在家里的一台电脑 / 小主机上，不急着上公有云。
