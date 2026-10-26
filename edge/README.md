# edge/

边缘端（"小脑层"），阶段 2 起启用，运行在树莓派 5 或 Jetson Orin Nano 上。

职责：

- 本地唤醒词、VAD、流式 ASR（sherpa-onnx / whisper.cpp）
- 摄像头采集、人脸 / 物体检测、简单跟踪
- 导航与避障（阶段 1 的反射逻辑上移到这里做更聪明的版本）
- 与 MCU 通过 USB-CDC 二进制协议通讯（100–200 Hz）
- 与云端通过 WebSocket 通讯，只上传事件和关键帧，不上传原始视频流
- 云端不可达时的本地降级策略

技术栈：Python 3.12 + asyncio；感知部分 ONNX Runtime / TensorRT；可选 ROS 2 Jazzy（阶段 3 再决定）。
