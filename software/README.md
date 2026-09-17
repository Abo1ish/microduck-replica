# software · 软件适配

官方运行时 [`pollen-robotics/microduck`](https://github.com/pollen-robotics/microduck) 是照 Dynamixel XL330 写的，本仓库主线用飞特 HD-1910，软件要改。这个目录放的是**改之前的分析和方案**，代码在 fork 出来的分支里。

| 文件 | 内容 |
|---|---|
| [`飞特适配架构.md`](飞特适配架构.md) | 官方运行时现有架构（接缝在哪、每个 tick 干什么、开机序列）、两家舵机逐项差别、适配方案、**`imu_to_dxl` 小板固件架构（§4）**、台架验收、待查清单、构建部署 / 策略关系 / 失败模式、评审记录 |

板子怎么烧、怎么装官方运行时，在 [不打 HAT](../docs/不打HAT.md) 和 [`tools/radxa/`](../tools/radxa/)。

飞特协议和内存表的官方原文（2026 年版快照）在 [`docs/飞特资料/`](../docs/飞特资料/)。

动代码前先把舵机点通：[`tools/servo-web/`](../tools/servo-web/) 是接串口的网页调试台，拖滑块、看回读、导寄存器底账、3D 鸭子跟着动，架构文档台架清单 0–8 项都用它。
