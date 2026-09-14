# 不打 HAT · 用 ¥70 的模块飞线替代

**简体中文**

> 官方 HAT 是 4 层板、双面贴装、110 个器件 —— 打样贴片一次上千块，**很多人觉得划不来**。
> 这份就是替代方案：一个降压模块 + 一个半双工转接板，剩下的飞线。**功能上只少了板载音频和关机检测信号。**

先看 [硬件入门](硬件入门.md) 知道 HAT 本来干什么，再看这份知道怎么不用它。

[![不打 HAT 接线图](../assets/hw/不打HAT-接线图.png)](不打HAT-接线图.html)

> **图的源文件是 [`不打HAT-接线图.html`](不打HAT-接线图.html)** —— 内联 SVG，下载后浏览器打开，能缩放、能选字、能打印 A3。
> 换模块、换脚位直接改它。上面这张 PNG 只是 GitHub 里的预览。

**目标**：主控从电池取电、经转接板跟舵机总线通信、ToF 挂上 I²C —— **不打 HAT 板**，¥70 的模块顶替上千块的打样。

> ⚠️ **这一章是计划，还没做过。** 接线部分来自规格书和官方原理图，软件部分来自官方 `setup-board.sh` 的源码。
> 做的时候哪步不对就改这里。做完把「没做过、要验证的」那节清掉。

## 要买什么

淘宝链接会失效，**搜索词和要看的数不会**。每行按「搜索词」搜，按「买之前看」挑。找到合适的把链接贴到 [电控采购清单](电控采购清单.md) 里。

| 东西 | 搜索词 | 买之前看 | 约价 |
|---|---|---|---|
| **降压模块** | 「UBEC 5V 3A 2S」 | **输入下限 ≤ 6 V**（很多标 2–6S 的实际 7 V 起，2S 快没电先掉出稳压）· 输出 ≥ 2 A 连续 · 同步降压，**别买 LM2596** | ¥10–15 |
| **半双工转接板** | 「串口总线舵机驱动板 ST SC」 | TTL 版或 USB 版都行。**逻辑供电范围含 3.3 V**（有的只吃 5 V，那就不能接主控）· 舵机侧电源能过 8.4 V。**已有 FE-URT-2 的话它就是 USB 版，可先不买**（见第 4 步） | ¥22 |
| 2×20 排针 | 「树莓派 彩色排针 2x20」 | 2.54 mm · 立式 · 彩色的好数脚 | ¥1 |
| 高耐久 microSD ×2 | 「SanDisk 高耐久 64G」或「海康 PLUS 64G」 | **京东自营** · 标 High Endurance / 监控专用 · **不是** Ultra / EVO 那种普通卡 | ¥90×2 |
| 读卡器 | 「USB3.0 读卡器 TF」 | USB 3.0 | ¥15 |
| 硅胶线 | 「18AWG 硅胶线 红黑」 | 18 或 20 AWG · 硅胶皮（软，耐温）· 红黑各 1 m | ¥10 |
| 保险丝座 + 管 | 「5x20 保险丝座 带线」+「5A 保险丝 5x20」 | 座子带线的省焊 · 快熔 5 A | ¥5 |
| 电源开关 | 「船型开关 KCD1」 | 额定 ≥ 6 A · 单刀单掷就行 | ¥3 |
| PH2.0 3P 端子线 ×5 | 「PH2.0 3P 端子线 单头」 | 2.0 mm 间距 · 3 针 · 单头带线（另一头裸线） | ¥5 |
| 杜邦线 | 「杜邦线 母对母 20cm」 | 母对母 · 20 cm · 一排 40 根 | ¥5 |
| 470 µF 电解 | 「470uF 16V 电解电容」 | 16 V 或以上 · 105 ℃ | ¥1 |
| *（可选）USB 声卡* | 「USB 声卡 免驱 3.5mm」 | **免驱**（Linux 认 UAC 标准）· 带麦克风口 | ¥15 |
| *（可选）小喇叭* | 「3W 4欧 小喇叭」 | 4 Ω 3 W · 接声卡的 3.5 mm 口要经功放，或直接买带功放的 USB 小音箱 | ¥5 |

不打 HAT 会失去：**关机检测信号**（LM5050-1 IO_06）、板载 BMI088（官方软件本就不用）、**板载音频** —— 音频可以用 USB 声卡补回来，见第 8 步。
没有关机信号 + microSD = 硬断电伤卡，**先软件关机再断电**。

## 第 1 步 · 主控点亮，什么都别接

**镜像**：Armbian **Debian 13 (trixie) · minimal · vendor 内核 6.1.115** —— 官方 `install.sh` 要的就是这个内核。
国内镜像站直链（Armbian 官方 dl 会自动跳到这儿）：

```
https://mirrors.bfsu.edu.cn/armbian-releases/radxa-zero3/archive/Armbian_26.8.1_Radxa-zero3_trixie_vendor_6.1.115_minimal.img.xz
```

376 MB。别选 `current_6.18` 那个（主线内核，官方没验证过），别选桌面版（用不上）。版本号 26.8.1 比官方文档写的 26.2.x 新，内核一样，`setup-board.sh` 是幂等的，有问题它会报。

```
1  焊排针 —— 先焊对角两针，翻过来看立直了没，再焊其余 38 个
2  balenaEtcher（Windows 免装）：选 .img.xz → 选 microSD → Flash，会自动校验
3  插卡，充电头 5V/2A 插 USB 2.0 OTG 口（电源口），别用电脑 USB
```

**第一次开机要设 root 密码、建用户、连 WiFi**。Armbian 的向导同时出现在 HDMI 和串口上，三条路任选：

| 路 | 要什么 | 怎么做 |
|---|---|---|
| **A · 串口**（硬件工程师首选） | 任意 USB 转 TTL 模块（CH340 / CH343 / FT232，**CP2102 不行**，跑不到 1.5 M） | 模块 TX → pin 10，RX → pin 8，GND → pin 6，**3.3 V 电平**。电脑串口终端 **1500000 8N1**。上电就看到向导 |
| B · 屏幕 | micro-HDMI 线 + USB 键盘（经 Type-C 转接插 HOST 口） | 插上开机，向导在屏幕上 |
| C · 预设文件 | 能写 ext4 的环境（WSL / Linux） | 烧完卡在根分区写 `/root/.not_logged_in_yet`，开机全自动。内容见下 |

向导里：设 root 密码 → 建普通用户（比如 `duck`）→ 选 WiFi 连上。完了 `ip a` 看 IP，以后都 ssh。

**C 那个文件**（[Armbian 文档](https://docs.armbian.com/user-guide/autoconfig/)）：

```bash
PRESET_NET_CHANGE_DEFAULTS=1
PRESET_NET_WIFI_ENABLED=1
PRESET_NET_WIFI_SSID='你的WiFi名'
PRESET_NET_WIFI_KEY='你的WiFi密码'
PRESET_NET_WIFI_COUNTRYCODE='CN'
PRESET_ROOT_PASSWORD='root密码'
PRESET_USER_NAME='duck'
PRESET_USER_PASSWORD='用户密码'
PRESET_LOCALE='en_US.UTF-8'
PRESET_TIMEZONE='Asia/Shanghai'
```

⚠️ 密码明文存在卡上，跑通后删掉这个文件。

**A 路用的就是 UART2 = 舵机总线那两个脚。** 首次开机借它当控制台没问题，第 2 步做完它就归舵机了 —— 走 USB 版转接板的话第 2 步可以不做，串口留着当控制台反而方便。

点亮了、能 ssh 了再往下。**点不亮的问题别跟接线的问题混在一起。**

## 第 2 步 · 让 `/dev/ttyS2` 出现

**这是不打 HAT 最容易卡住的地方。** Armbian 出厂设置下 `/dev/ttyS2` 根本不存在，板子却一切正常，你会以为是线接错了。

官方 `setup-board.sh` 做四件事，你可以直接跑它，也可以手工做：

```bash
# ① overlay 前缀 —— Armbian 出厂写的是 rk35xx，但 RK3566 的 overlay 文件叫 rk3568-*.dtbo
#    前缀错了加载器什么都找不到，静默失败
sudo sed -i 's/^overlay_prefix=rk35xx$/overlay_prefix=rk3568/' /boot/armbianEnv.txt

# ② 开 uart2 的 M0 引脚复用 —— 这就是 40 针的 pin 8 / pin 10
echo 'overlays=uart2-m0' | sudo tee -a /boot/armbianEnv.txt

# ③ 内核 console 默认占着 ttyS2（它是 RK3566 的调试串口）—— 从 /boot/armbianEnv.txt 的
#    extraargs 里把 console=ttyS2,1500000 拿掉，不然内核往舵机总线上打日志

# ④ 登录控制台也占着它
sudo systemctl mask serial-getty@ttyS2

sudo reboot
ls -l /dev/ttyS2          # 出现了才算过
fuser -v /dev/ttyS2       # 应该什么都不占
```

⚠️ **`apt upgrade` 换内核后可能把 ① 打回原形。** 舵机突然全不动了，先看这条。

直接跑官方脚本的话（上游仓库是公开的，不用 token）：

```bash
git clone https://github.com/pollen-robotics/microduck
sudo sh microduck/scripts/setup-board.sh    # 幂等，不自动重启
sudo reboot
```

## 第 3 步 · 电源，每接一段量一次

```
NP-F550 ──► 开关 ──► 保险丝 5A ──┬──► 降压模块 ──► 5 V ──► Radxa pin 2（或 4）
                                 │        │
                                 │        └── 输入端并 470 µF
                                 │
                                 └──► 舵机总线 VDD（原压，18 AWG）
共地：电池负极 · 降压输出地 · Radxa pin 6 · 舵机总线 GND
```

```
1  接开关、保险丝，量：开关闭合时保险丝两端应导通
2  接降压模块，先别接 Radxa，量输出：5.0 V ±0.2，极性对
3  ⚠️ 确认极性再插 Radxa —— pin 2/4 是无保护的，接反烧板
4  Radxa 拔掉 USB-C，靠 pin 2 的 5 V 点亮，ssh 能进
5  再接舵机总线的 VDD
```

## 第 4 步 · 舵机总线接主控

```
Radxa 40 针                     转接板 MCU 侧
pin 1   3.3 V    ──────────►   VCC       ⚠️ 只能 3.3 V，接 5 V 它的 TX 会打坏主控 RX
pin 8   UART2_TX ──────────►   RX        ← 交叉
pin 10  UART2_RX ◄──────────   TX        ← 交叉
pin 6   GND      ──────────►   GND

转接板舵机侧
DATA  ──► 舵机总线 S
V     ◄── 舵机总线 VDD（电池原压，第 3 步接的）
G     ──► 共地
```

**USB 版转接板**：不用接 pin 1/8/10，插 Radxa 的 USB 口，串口变成 `/dev/ttyUSB0` 或 `/dev/ttyACM0`，
之后 `robotd.toml` 里 `port` 改成那个。省事，但第 2 步的 uart2-m0 overlay 就用不上了（agetty 照样 mask，无害）。

> 💡 **飞特 FE-URT-2 调试板就是 USB 版转接板** —— 配完 ID 直接挪到机器人上：USB-C 插 Radxa host 口，TTL 口 S 接总线，G 接总线地。
> **电池原压直接给舵机总线，不进 URT-2 的 V1 端子** —— V1 可能跟 USB 5 V 直通，灌 7.4 V 会反灌进 Radxa。
> 板上拨码是信号电平（3.3 / 5 V），拨 5 V。转接板可以先不买。
> 先验 Radxa 认不认 CH343：`dmesg | tail` 看有没有 `ttyACM0`；没有的话 WCH 官网有 Linux 驱动源码。
> 它是唯一的调试板，装进去就不能在电脑上配舵机了 —— **15 颗 ID 全配完再挪**。

**总线怎么分支** —— 头、左腿、右腿在躯干分三路。半双工单线总线是**并联**不是链，星形树形都通，菊花链只是走线方便：

```
转接板 TTL ──┬──► 头颈   30 → 31 → 32 → 33 → 34
             ├──► 左腿   20 → 21 → 22 → 23 → 24
             └──► 右腿   10 → 11 → 12 → 13 → 14
             （imu_to_dxl 200 挂躯干里任一路）
```

分法：URT-2 自带两个 TTL 口各出一路、第三路从舵机再分；或买「舵机总线分线板 3P」一进四出（¥5）；或三根线并焊。
**V 和 G 用 18 AWG 单独走到三个支路**，S 随便走。⚠️ **别把三路电流全走 `imu_to_dxl` 板** —— 它四个座子虽是并联，但 2 层板直通铜皮没按几安培设计，会烧。它挂一路的末端或中间。

## 第 5 步 · 一颗舵机验证通信

只挂**一颗**配好 ID 的舵机（比如左膝 23），主控上：

```bash
# 官方运行时带的总线基准工具（第 7 步装完才有），或先用 Python 快速 ping：
pip install feetech-servo-sdk    # 或 scservo_sdk
# 1 Mbps，ping ID 23 —— 回了就通了
```

不通按顺序查：`ls /dev/ttyS2` 有没有 → `fuser` 有没有人占 → TX/RX 是不是交叉 → 转接板 VCC 是不是 3.3 V → S 线接触。

## 第 6 步 · ToF

```
VL53L8CX          Radxa 40 针
SDA      ◄──►    pin 3
SCL      ◄──►    pin 5
3V3      ◄───    pin 17     （pin 1 给转接板了，分开用）
GND      ────►   pin 6
```

pin 3/5 板载带上拉，不用外加。

⚠️ **I²C 还要一个 overlay。** 官方是 `i2c3` 重 mux 到 M0（就是 pin 3/5），代价是失去 USB-C PD 协商。
官方的 overlay 在 `deploy/audio/i2c3-pihat.dts`，是给 HAT 写的，**不打 HAT 能不能直接用，待验证**。

## 第 7 步 · 跑官方运行时

```bash
curl -fsSL https://raw.githubusercontent.com/pollen-robotics/microduck/main/scripts/provision.sh -o /tmp/provision.sh
sudo sh /tmp/provision.sh
# = setup-board.sh → migrate-network.sh → 重启 → install.sh，全自动
robotctl health
```

`robotd.toml` 在 `/etc/robot/`，串口默认 `/dev/ttyS2`，USB 版转接板改成 `/dev/ttyUSB0`。

## 第 8 步 · 想要声音（可选）

不打 HAT 就没有 codec，官方的叫声、摸头识别、ToF 电子琴、多鸭合唱都用不了 —— **但机器人走路不受影响**，官方注释原话「没有 codec 的板子走路完全一样，只是不出声」。

想要回来，插个 **USB 声卡**（免驱那种，Linux 直接认）：

```bash
aplay -l                          # 看到 USB Audio 那张卡的名字，比如 card 1: Device
sudo nano /etc/robot/robotd.toml
```

```toml
[audio]
enabled = true
device = "plughw:CARD=Device"     # 换成 aplay -l 看到的名字，官方默认是 plughw:aic3104
```

```bash
sudo systemctl restart robotd
```

喇叭接声卡的 3.5 mm 口（小喇叭要功放，直接买带功放的 USB 小音箱最省事），麦克风接声卡的 mic 口。

⚠️ **没验证过**：官方 `sounds` 和 `pet_detect` 是按 aic3104 的采样率和通道数写的，USB 声卡不一定对得上。跑通了把这条改掉。

## 没做过、要验证的

| 项 | 疑问 | 怎么验 |
|---|---|---|
| 第三方转接板 @ 1 Mbps | 官方 HAT 的方向电路是 `1G08+1G125+1G126`，¥22 的板子方向切换够不够快 | 第 5 步通了、`bench_dynamixel_bus` 错误计数为 0 |
| `i2c3-pihat.dts` 不打 HAT 能不能用 | 那个 overlay 是给 HAT 写的 | 第 6 步 `i2cdetect -y 3` 看到 0x29 |
| 降压模块扛不扛得住舵机启动压降 | 15 颗同时动电池会跌 | 走路时主控不重启；不行就加大输入电容 |
| Armbian 具体哪个镜像 | 官方说 26.2.x，没说 minimal 还是 desktop | 第 1 步能 ssh 进去就行 |
| USB 声卡能不能替代 aic3104 | 官方音频代码按 codec 的采样率写的 | 第 8 步 `robotctl health` 音频那行不报错、开机有叫声 |

接线图见文首，源文件是同目录的 `不打HAT-接线图.html`。

