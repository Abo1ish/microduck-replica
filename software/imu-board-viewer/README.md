# Microduck 裸板姿态工程 · 队友使用说明

这个工程让你自己的 IMU 板驱动浏览器中的 3D 鸭子。电脑通过 J-Link 读取板上姿态，模型整体随板子倾斜、旋转。模型和前端资源已包含在工程里，正常显示不依赖外部 CDN。

适用硬件是本项目的 **STM32G031F8P6 + LSM6DSV16X 同款板、相同引脚连接**，以及可用的 J-Link。仅有其他型号 STM32 开发板、ST-LINK 或任意 IMU 板，不能直接套用本工程。

**本工程用于裸板的 SWD 姿态观察。** 附带固件保留早期 Dynamixel Protocol 2.0、ID 200 的调试基线，**尚未实现当前飞特方案的地址 56、15 字节总线契约**。网页直接读取 RAM，因此显示正常不代表飞特总线验收通过，也不能把此固件直接用于当前 `FeetechIo` 的整机运行。总线接口要求见仓库中的 [协议说明](https://github.com/fanhao375/microduck-replica/blob/master/hardware/imu_to_dxl/总线协议.md)。

## 1. 解压和准备软件

克隆或下载仓库后，进入 `software/imu-board-viewer` 即可使用；也可以把这个目录整体复制到自己的目录，例如 `E:\Microduck-IMU`。保持 `tools` 和 `firmware` 的相对位置，不要只复制 `imu.html` 或 `.venv`。

需要发送独立 ZIP 时，在本目录执行 `python package.py`，生成 `dist/Microduck-IMU-viewer.zip`。打包脚本只收录 `PACKAGE_FILES.txt` 列出的文件，并生成未填写的配置和 SHA-256 清单，不打包个人配置、虚拟环境或日志。队友应先完整解压，再运行以下入口。

- 安装 Windows x64 版 **Python 3.11 或更新版本**，安装时启用 Python 的命令行入口。本次开发验证使用 Python 3.12.14 x64。[Python 官方下载](https://www.python.org/downloads/windows/)
- 使用真实板卡时，安装 **SEGGER J-Link Software and Documentation Pack**，包含 USB 驱动。本项目用 J-Link 9.78、100 kHz SWD 验证过。[SEGGER 官方下载](https://www.segger.com/downloads/jlink/)
- 双击包根目录的 **01-首次安装.cmd**。它在工程内创建自己的 `.venv` 并联网安装锁定的 Python 依赖，缓存和临时目录也放在工程内；不会替你安装系统 Python 或 J-Link。
- 若自动找不到你安装的 Python，可在 `tools\servo-web-imu` 目录打开 PowerShell，给 `setup.ps1` 传入 `-PythonPath`，指定你自己的 `python.exe` 完整路径。

安装后先双击 **02-无硬件演示.cmd**：浏览器应显示鸭子和“演示模式 · 非硬件”。这一步只确认软件和模型资源正常，不需要接板子或安装 J-Link。

## 2. 填写你自己的 J-Link 配置

首次安装会从 `config.example.json` 生成 `tools\servo-web-imu\config.json`，独立 ZIP 也会提供未填写的配置。用记事本打开它，填写自己的信息；真实模式不会猜测或自动接入其他探针。个人 `config.json` 已被 Git 忽略。

- 把 DLL 路径改成自己安装目录下的 **JLink_x64.dll**，例如 `E:/SEGGER/JLink/JLink_V978/JLink_x64.dll`。JSON 中推荐用 `/`，如果用反斜杠则应写成 `\\`。
- 把 `probe_serial` 填成自己 J-Link 的数字序列号，可以从探针标签或 SEGGER J-Link Configurator 中核对。不要复制原开发者的序列号。
- 固件和 map 默认使用包内相对路径，首次使用保持不变。相对路径以配置文件所在目录为基准，整包移动盘符不需要改它们。

不要把已填写的个人配置覆盖回公共模板。`config.example.json` 可作为重新配置的起点。

## 3. 让板上固件与工程匹配

当前网页通过已知 RAM 布局读数，因此你的板上必须运行包内匹配的固件。仅芯片型号相同、但固件不同，也不能读取。

包内 `firmware\imu_to_dxl\Build\` 包含配套的 `.bin`、`.hex` 和 `.map`；需要带调试信息的 `.axf` 时，请在自己的环境中编译。BIN 长度 **11612 字节**，SHA-256：

`69bdaea7224900addd6eb5bd28001e26e07073c129383d9c1ece380d2bfce19a`

如果是尚未烧录的新板，在核对本板原理图和引脚后，使用你已有的烧录工具写入这个 `.hex`，或将 `.bin` 写入 STM32 主 Flash 起始地址 **0x08000000**，并执行读回校验。目标选择 STM32G031F8、SWD，先使用 **100 kHz**。不要把原先有用的固件无备份覆盖掉。网页启动器本身不会执行烧录。

包内也保留固件源代码和 Keil 工程，供需要开发的人使用。**首次只验证网页时，直接使用已验证的固件，不必重新编译。** 编译输出不同会被网页校验拒绝；开发新固件后，需要重新审核 RAM 结构、地址和校验值，不能只取消检查。

Keil 工程在 `firmware\imu_to_dxl\MDK-ARM\`。使用前在自己的 Keil 中选择设备包、编译器以及自己的 J-Link；不要照搬开发者的安装盘符和调试配置。Keil 与 SEGGER 工具需自行合法安装，包中不包含这些安装程序或授权。

## 4. 接自己的板子，启动真实画面

1. 按自己的同款板原理图确认供电与 SWD 接线：GND、SWCLK、SWDIO、目标电压参考 VTref。包内 `硬件资料\调试接线说明.md` 提供本板 SWD 接线表；同目录保留原理图和 PCB 图纸。本板 VTref 是 J3.6，不是旧文字中误写的 J3.4。
2. 让 Keil、J-Link Commander 等程序退出调试，释放探针。同一个 J-Link 不应同时被两个程序连接。
3. 双击 **03-接板子看姿态.cmd**，默认打开 `http://127.0.0.1:8081/`。
4. 确认页面显示“真实板卡 · J-Link”“实时跟随”，采样计数不断增长、错误计数不增长。
5. 平放板子，点“当前姿态归零”，再缓慢左右、前后倾斜或转动。方向不符合装配朝向时，用安装方向下拉框调整后重新归零。

每个人电脑上的 `127.0.0.1` 都指向自己的电脑；队友需要运行自己的这份工程。此工程包不提供远程观看原开发者板卡的功能。

## 5. 使用边界与故障处理

- 新板需要先完成自己的供电检查。网页显示的是 J-Link 参考电压，不能代替输入电流、温升或电源质量测量。
- 当前 J-Link 9.78 在开发板上实测建连会重启板上程序，即使已请求关闭连接时工作 RAM 初始化。归零只改变网页参考姿态，不写板上参数；启动和重新连接不是无扰动操作。
- “固件不一致”：检查使用的是否是包内固件。不要修改 SHA 校验来强行读取不匹配地址。
- “找不到 J-Link / 打开失败”：检查驱动、配置序列号及 DLL 路径，并让其他调试工具退出连接。
- “读取失败 / 数据中断”：先检查供电和接线，再点击“重新连接”。断流时页面停止显示有效数值，不会用假数据补上。
- 想回 Keil 调试，先点网页“断开连接”。关闭浏览器标签不会自动停止后台服务。
- 日志在 `tools\servo-web-imu\logs`。需要协助时提供报错文字和自己的配置路径；无需发送整个虚拟环境。
- 六轴 IMU 的航向会漂移；这里显示相对姿态，不测量平移，也不验证舵机动作或实物平衡。舵机滑块、姿态序列和协议模拟器使用仓库原有的 [tools/servo-web](https://github.com/fanhao375/microduck-replica/tree/master/tools/servo-web)，与此实时姿态入口独立。

原开发板于 2026-09-20 完成约 20 Hz 真板读数验证；本次公开版本另外运行软件测试和无硬件演示，未重新连接真板。测试范围及尚未验证的内容见 [VALIDATION.md](VALIDATION.md)。队友的电脑、J-Link 与新板仍需按上述步骤现场验证。

原始工具来源：[fanhao375/microduck-replica/tools/servo-web](https://github.com/fanhao375/microduck-replica/tree/912a685684d9765c54c8296d203caa6de546a0a7/tools/servo-web)。模型来源说明、第三方许可证及固件依赖说明均随包保留。
