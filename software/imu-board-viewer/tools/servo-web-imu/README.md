# IMU → 3D 鸭子

本机 J-Link 姿态查看器，使用配套固件读取 STM32G031 的 IMU 样本，经 WebSocket 驱动浏览器中的鸭子整体旋转。包括不需要硬件的演示模式。完整安装与接线见 [工程说明](../../README.md)。

## 开发与验证

先运行 `setup.ps1` 安装本目录的锁定依赖，然后在本目录执行：

```powershell
.\.venv\Scripts\python.exe -m unittest -q test_imu_bridge test_launcher
.\.venv\Scripts\python.exe launcher.py --demo
```

`imu_bridge.py` 负责 J-Link、固件校验和样本解码；`imu_server.py` 提供仅绑定回环地址的 HTTP/WebSocket 服务；`imu.html` 负责姿态映射、归零和显示；`launcher.py` 校验个人配置并启动服务。直接运行服务器的真实模式也必须提供 `--dll` 和 `--probe-serial`，不会自动选择探针。

模型和 Three.js 随工程提供，启动显示无需外部 CDN。`build_model.py` 是上游模型转换脚本，重新生成模型还需要原仓库网格和 NumPy，正常使用无需运行。

舵机控制和协议模拟器仍使用仓库原有的 [tools/servo-web](https://github.com/fanhao375/microduck-replica/tree/master/tools/servo-web)。此目录没有舵机控制入口，也不代表飞特 15 字节总线协议已实现。

来源及许可证见 `UPSTREAM.json`、`upstream-notices/`、`model/NOTICE.md` 和 `vendor/LICENSE.three`。
