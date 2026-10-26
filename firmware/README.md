# firmware/

单片机侧代码，即"脊髓层"。目标芯片：ESP32-S3（阶段 0–1），阶段 2 起作为树莓派 / Jetson 的实时协处理器继续使用。

计划结构：

```
firmware/
  duck/            阶段 0 固件（ESP-IDF 5.x）
    main/
      app_main.c
      audio/       I2S 采集 / 播放、AEC、Opus 编解码
      net/         Wi-Fi 配网、WebSocket 客户端、OTA
      body/        舵机、LED、触摸、情绪动画状态机
      proto/       与云端 / 边缘的消息编解码（见 docs/02-architecture.md）
      safety/      看门狗、断网降级、过温 / 低电保护
  common/          跨阶段共用组件
```

原则：

1. 固件只做实时和安全，不做"思考"。
2. 任何动作都有超时：云端说"点头"但 2 秒内没有后续，身体自动回中立姿态。
3. 断网 / 断云端时，固件进入"离线人格"：仍能眨眼、哼声、响应触摸，不假死。
4. 所有引脚定义集中在一个头文件，与 `hardware/phaseN/wiring.md` 一一对应。
