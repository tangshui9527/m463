# 魅蓝1 刷 Linux —— 总交接文档（2026-11-18，供次日接手人使用）

> 📌 **本文是项目唯一现行文档**，由 2026-11-16~18 三天会话整合而成。
> 旧文档（HANDOVER-FINAL/STATUS/RECOVER/NEXT-PLAN 等）已删除，有效信息全部并入本文，
> 错误记载已在 §10 勘误归档。**读本文即可接手，无需任何历史文档。**
>
> **一句话现状**：刷机链路全通；boot 分区当前为 v8.5 探针（**未测试**）；
> 正在诊断两个内核失败模式（原厂内核静默挂死 / 自编内核 5 秒 panic）；
> 下一步 = 刷 v8.5 + TTL 串口抓取第一份内核日志。
>
> **给接手人的第一件事**：读完 §1~§5，然后按 §6 执行（全程约 30 分钟，需要 USB-TTL 适配器）。

---

## 1. 环境与资产（接手人必读）

### 1.1 两台主机

| 主机 | 角色 | 访问方式 |
|---|---|---|
| **Mac mini**（本机） | 构建/分析/文档 | 本地路径 `/Users/tangshui/test/m463/` |
| **go**（Pixelbook，Ubuntu/Omarchy） | 刷机宿主机（mtkclient） | `ssh tang@192.168.31.90`，sudo 密码 `1122` |

### 1.2 go 上的关键路径

| 路径 | 内容 |
|---|---|
| `~/mtkclient/` | mtkclient 本体 + 全部镜像 + 脚本 |
| `~/mtkclient/autoflash_server.py` | **刷机面板**（端口 8080） |
| `~/mtkclient/uart_capture.sh` | 串口双波特率轮替抓取器（921600/115200 每 20 秒切换） |
| `~/mtkclient/uart_view.py` | 串口日志实时监控页（端口 8081） |
| `/tmp/uart_cap.log` | 串口抓取日志（uart_capture.sh 自动写入） |
| `/tmp/ram_console_dump.bin` | ram_console 抓取产物 |

### 1.3 两个网页监控（浏览器打开）

| 地址 | 页面 | 用途 |
|---|---|---|
| `http://192.168.31.90:8080` | **刷机面板**（4 个目标按钮 + 刷机日志终端 + USB 模式横幅） | 刷机操作与观察 |
| `http://192.168.31.90:8081` | **串口日志实时监控**（2 秒刷新，panic 标红） | TTL 串口抓取时看日志 |

### 1.4 面板操作要点

- 面板**每次重启后目标会被重置**为代码内默认值（当前=linux_v2_reboot）——**每次重启面板后必须用按钮或 API 重新选择目标**；
- 面板的刷机循环线程**必须存活**才会刷机（网页正常 ≠ 循环存活，见 §7 陷阱 P1）；
- 验证循环存活：`ps aux | grep "mtk\.py" | grep -v grep | wc -l` ≥ 1（mtkclient 在等待设备）；
- 面板重启命令：
  ```bash
  ssh tang@192.168.31.90 'pkill -f "autoflash_serve[r].py"; sleep 1'
  ssh tang@192.168.31.90 'cd ~/mtkclient && setsid nohup python3 autoflash_server.py > ~/autoflash_server.log 2>&1 < /dev/null &'
  # 然后必须重新选目标:
  curl -s -X POST "http://127.0.0.1:8080/api/set_target?target=<目标键>"
  ```

### 1.5 硬件清单（需要采购/确认）

| 物品 | 用途 | 状态 |
|---|---|---|
| USB-TTL 适配器（CH340/CP2102，3.3V） | 串口日志抓取 | **机主已有**（CH340 模块，带 3.3V/1.8V 跳线） |
| 剪开的 micro-USB 线（引出 D+/D-/GND/VBUS） | 串口连接手机 | 机主自制中 |
| 杜邦线/1kΩ 电阻 | 接线与保护 | 待确认 |

---

## 2. 设备身份（2026-11-17 定案，勿再混淆）

| 项 | 值 | 证据 |
|---|---|---|
| 机型 | **魅蓝1**（Meizu M1，M463 系列 **m79** 项目） | IMEI TAC 86743602 = MEIZU M1（fccid.io）+ 机主实物 |
| 芯片 | **MT6732**（MT6752 同 die 四核版，bootrom 报家族码 0x6752） | mtkclient 实时输出 + brom_config.py 无 0x6732 条目 |
| RAM | **1GB**（0x40000000） | DA 实测 |
| eMMC | **8GB**（7.28GB 可用） | DA 实测 |
| 屏幕 | 5.0" **1280×768**（面板 hx8394d_hd_dsi_vdo_truly） | m79 ProjectConfig.mk |
| 电池 | BT43（机主已换新，可能副厂——电量计可信度待验证） | 机主 |
| 固件 | Flyme 4.2.1.3C（CMCC），Android 4.4.4，基带 MOLY.LR9.W1423.MD.LWTG.CMCC | 机主照片 |
| 系统型号字符串 | `m1`（**不要**据此当作魅蓝1/Note 的区分依据——两台机都显示 m1） | 机主照片 |
| 序号 / IMEI | 79AEALJJ33L3E / 867436022519241 | 机主照片 |
| 源码仓库 | [meizuosc/m463](https://github.com/meizuosc/m463)（覆盖 M1 Note / M1 两台机；**m79=魅蓝1，m71=魅蓝 Note**） | ProjectConfig 实测 diff |

⚠️ **易混警示**：芯片 bootrom 报 0x6752（家族码）≠ MT6752 机型；Flyme 型号 "m1" ≠ 魅蓝1 专属。
**锚点永远是：RAM 1GB + eMMC 8GB + TAC 86743602 + 面板 hx8394d。**

---

## 3. 已验证机制与定案（全部有实测/源码证据）

| # | 结论 | 证据 |
|---|---|---|
| 1 | **devmem 访问 RGU 寄存器（0x10007000x）会挂死内核**——MPU 保护，访问即总线冻结（非 oops/panic）。v8.2/v8.3 黑屏不重启的根因 | 实测：v8.3 rcS 的 `rst_status=$(devmem 0x10007000C)` 一行导致一切输出前挂死。**任何脚本绝不可 devmem 触碰 0x10007000x** |
| 2 | **内核 panic → 5 秒自动复位**（CONFIG_PANIC_TIMEOUT=5）可靠可用 | v2 内核两次实机 5 秒 panic 循环实证。无限重启的正确实现 = 触发 panic（sysrq 'c'），不是 devmem 写 WDT |
| 3 | **boot 头 id 字段 = 标准 mkbootimg SHA-1**，非魅族私有 | 原厂值逐字节复现成功（sha1(kernel+len+ramdisk+len+0)） |
| 4 | **USB 连接器可软件切 UART 模式**：`echo 1 > /sys/devices/platform/mt_usb/portmode` → D+/D- 变为 ttyMT0 的 RX/TX（源码 usb20.c/usb20_phy.c 全链验证，`mtk_uart_usb_rx_sel(1,1)` 操作 port0） | 源码 + 原厂 vmlinux 字符串 |
| 5 | **BROM 窗口 = 4.6 秒固定超时**：手机进 BROM 后等 4.6 秒，无握手则自动退出继续启动（进充电模式）。dmesg 时间线 5 次实测精确 4.6 秒 | go dmesg 时间线 |
| 6 | **关机插线 → 手机停在 preloader/META 模式（0e8d:2001）无限期稳定**，mtkclient 可从该状态直接漏洞利用刷写（实测 8.6MB @ 8MB/s）——**无需抢 BROM 窗口** | 2026-11-17 实测 |
| 7 | **关机插线（不按键）= 充电模式 = LK 层挂起（充电图标）**，不会启动内核——MTK_KERNEL_POWER_OFF_CHARGING 的行为。**充电插入不能用于自动开机进探针** | 机主观察 + 配置 |
| 8 | **legacy DA 的 reset/FINISH = 断电语义**（参数 0/1 实测均不重启），finish(2) 未验证。**不能依赖 DA 复位实现自动重启** | 源码（finish(bootmode)→0xD9+value）+ 实测 |
| 9 | **initramfs 打包必须用 `gen_init_cpio`**（条目名无前导斜杠——校验脚本注意）；手写 cpio（ino=0）曾致 3 秒重启，已删除 | 历史 + 源码 |
| 10 | **内核 console 波特率**：DTB bootargs 写 921600，但 LK 的 cmdline 会覆盖（CONFIG_CMDLINE_FROM_BOOTLOADER=y）——实际波特率未定，**串口抓取必须双波特率轮替**（921600/115200） | 源码 + 实测乱码分析 |
| 11 | **preloader/LK 阶段的日志不走 USB 连接器**（走内部 UART 焊盘）——USB 连接器上的串口输出始于内核 rcS 切换 portmode 之后（~1.5 秒） | 分析 + 实测 |
| 12 | **PDLOG/0e8d:2001+ACM = preloader/META 日志通道**，不是内核输出 | dmesg 分析 |
| 13 | **MTK_KERNEL_POWER_OFF_CHARGING=yes**：关机插线的充电图标与充电模式行为出自此配置 | m79 ProjectConfig.mk |
| 14 | 魅族 GPL 源码**不完整**：mach 头（GPIO 表/DCT）、mtprintk 驱动缺失——UART 焊点号无法从源码获得 | 全树搜索 |

---

## 4. 当前卡点：两个失败模式（等你抓到日志定案）

**boot 分区当前 = v8.5**（原厂内核 + 早期串口 initramfs + panic 循环，**未测试**）。

| 失败模式 | 现象 | 已排除的原因 |
|---|---|---|
| **A. 原厂内核静默挂死**（v6.x 系列） | Logo → 黑屏背光常亮，不重启、无 USB、无串口输出 | 不是 panic（无 5 秒重启）；~~充电模式~~（充电模式有充电图标）；~~电池~~（机主确认有电）|
| **B. 自编内核 5 秒 panic**（v2/v7 系列） | Logo 3~5 秒 → 自动重启循环 | panic 原因未知——**v2 内核配置=本机配置，理论上不该 panic** |

两个模式的共同点：**死在所有输出通道建立之前**（串口未初始化/未切换、fb 未点亮、USB 未枚举）。唯一能看见它们的窗口 = 串口（v8.5 的 portmode 早期切换）或 UART 飞线。

**嫌疑排序**（A 模式）：① 显示/面板初始化路径死等（DSI 握手卡住）② Meizu 启动链校验（sbchk 类）③ 内存/时钟差异。
**嫌疑排序**（B 模式）：① 编译器差异（gcc 4.9.4 重编 2014 年内核的经典雷区）② 面板 probe panic。

---

## 5. 立即执行：v8.5 串口抓取测试（接手人第一件事）

### 5.1 前置检查

```bash
# go 上确认三件事:
lsusb | grep -E "0e8d|1a86"        # 手机或 CH340 是否在总线
ls -l /dev/ttyUSB0 2>/dev/null     # CH340 是否就绪
ps aux | grep autoflash | grep -v grep | wc -l   # 面板是否运行(应为1)
```

### 5.2 接线（CH340 模块 ↔ 手机剪线）

| 手机线 | CH340 排针 |
|---|---|
| 万用表量出高电平/跳变的那根（手机 TX） | **RXD** |
| 另一根数据线（手机 RX） | **TXD**（串 1kΩ 保护电阻） |
| GND（外壳金属可用，先用万用表量与电池负极通断确认） | **GND** |
| VBUS（红线） | **不接**（接了会进充电模式挂起，内核起不来）|

⚠️ CH340 电压跳线：**3.3V**（1.8V 档会杀死芯片——实测 CH340 从总线上消失）。如怀疑手机串口是 1.8V：万用表量 TX 空闲电压，若 ~1.8V 需 TXB0104 电平转换（2 元）。

### 5.3 执行序列

```
① 刷入: 手机彻底关机(长按电源10秒) → 直接插上普通USB线(不用按键)
        → 手机停进 preloader(0e8d:2001) → 面板自动直刷(8MB/s, ~1秒)
        → 面板出现 Wrote ... [100%] → 拔掉刷机USB线
② 换接: 接上 CH340 串口线(手机此时关机) → CH340 插 go
        → 自动抓取器立即以 921600/115200 轮替开始记录(/tmp/uart_cap.log + 8081 页面)
③ 开机: 短按一次电源
        → ~0.3秒 /init 切 UART 模式 → ~1秒 rcS 心跳块滚动
        → 3~5秒 原厂内核行为显现(挂死=日志停住 / 正常=继续)
④ 记录: 观察 1~2 分钟(panic 会自动重启循环反复抓取)
```

### 5.4 结果判读（四种结局，每种都有明确下一步）

| 监控页现象 | 结论 | 下一步 |
|---|---|---|
| 心跳块滚动 + 停在某行 | **死点定位**——最后可见行之后即死因区间 | 按死点位置修（告诉我内容）|
| `Kernel panic - not syncing: ...` 红字 | panic 原文到手 | 按原文修复 |
| 状态页出现在手机屏幕 | 显示链路 ✓ + rcS 存活 | 转 v7.2 抓自编内核 panic |
| 全程零数据（两种波特率都试过、极性换过） | 内核死在 0.3 秒前 或 电平/接线问题 | 万用表量 D+/D-（§5.2 判读表）→ 若确认无信号 = **转 UART 飞线（§8）** |

---

## 6. 数据窗口收割（v2 panic 循环运行时的旁路通道）

若 v2 内核的 5 秒 panic 循环在跑（面板目标 linux_v2_reboot），每轮循环产生一个 BROM 窗口。
面板目标「📋 数据窗口收割」会在每个窗口自动读取 64KB ram_console（0x43F00000）。

- v2 内核 `CONFIG_MTK_RAM_CONSOLE=y` ✓，panic 原文会写入；
- **未验证风险**：热复位（panic→WDT复位）是否保留 ram_console——多轮收割自动验证；
- 判读：抓到的 dump 含 `Kernel panic`/`Booting Linux` 可读文本 = 命中；全是 `<<<RAM_RW>>>` = 不保留。

面板目标键：`dump_console_plain`（纯 peek，不带 --crash，不干扰循环）。

---

## 7. 陷阱清单（每个都真实踩过，逐条防）

| # | 陷阱 | 防范 |
|---|---|---|
| P1 | **面板刷机循环线程静默死亡**：目标键失效(KeyError)或作用域错误(UnboundLocalError)都会杀死线程，网页照常但永不刷机 | 重启面板后必须验证 `ps aux | grep "mtk\.py" | wc -l` ≥ 1；代码已有防御性回退+global 声明 |
| P2 | **远程命令 pkill 自匹配**：`pkill -f uart_capture` 会杀掉含同串的远程 shell 自己 | 模式用 `uart_captur[e]`；或拆分命令；注意远程 shell 是 zsh，`[e]` 在参数里会被 zsh 当 glob（"no matches found"）——放引号内 |
| P3 | **BROM 4.6 秒窗口**：面板监听退化时抓不到 → 全部"USB 秒断"的真相 | 重启面板恢复监听；或改用 preloader 停驻直刷（§5.3①） |
| P4 | **关机插线 = 充电模式挂起**（充电图标，不启动内核） | 刷机必须音量减插线；充电模式不能用于开机 |
| P5 | **devmem 触碰 RGU = 内核挂死** | 脚本绝不写 0x10007000x（§3.1）|
| P6 | **legacy DA reset = 断电语义**（不是重启） | 刷完不复位时用电源键开机一次；finish(2) 待验证 |
| P7 | **CH340 的 1.8V 档位杀芯片** | 跳线固定 3.3V；1.8V 信号用电平转换 |
| P8 | **gen_init_cpio 条目名无前导斜杠**（校验脚本按 `/init` 找会误报缺失） | 校验时用无斜杠名 |
| P9 | **go 的 dmesg 需要 sudo**；`dmesg` 直接读会报错 | `echo 1122 \| sudo -S sh -c "dmesg > /tmp/d.txt"` 后 grep |
| P10 | **USB 接触不良（手机尾插）**：需特定角度提线才连通；失败随机 | 刷机全程固定角度；失败零成本重试（无永久损坏——写一半的 boot 会被下次成功覆盖）|
| P11 | **关机插线后手机会停进 preloader 而不是消失**——0e8d:2001 是稳定驻留态，可直刷 | 见 §6/§5.3 |
| P12 | **面板重启后目标重置** | 重启后必须重新 set_target |

---

## 8. 紧急救援

**恢复原厂 Flyme**（手机变砖/开不了机时；前提=USB 链路可用）：
```bash
ssh tang@192.168.31.90
cd ~/mtkclient
echo 1122 | sudo -S python3 -u mtk.py multi "w seccfg seccfg-read.img; w lk lk-stock.img; w boot boot-stock.img; w recovery recovery-stock.img; reset"
```
- 手机关机状态**直接插线**（不用按键）→ 停进 preloader → mtkclient 从 preloader 模式直刷（实测可用）；
- 备份齐全：boot-stock-20261116.img（真机 16MB dump）、lk-stock.img、seccfg-read-20261116.img、recovery-stock-20261116.img；
- **红线：永不刷 preloader 分区 / 永不跑 `da seccfg unlock`**（SEJ legacy 路径会写坏加密块，见历史事故：设备曾因此全无反应）。

---

## 9. 文件清单

### 9.1 现行（debian/ 本地 = go:~/mtkclient/ 镜像同步）

| 文件 | 说明 |
|---|---|
| `boot-linux-v8.img` | **v8.5 探针**（原厂内核 + 早期串口 initramfs + panic 循环）——当前武装 |
| `boot-linux-v7.img` | v7.2（自编内核 v2 + 原厂 DTB + portmode rcS）——panic 循环 + 串口抓取版 |
| `boot-linux-v6.img` | v6.4（原厂内核 + portmode rcS）——串口抓挂死点版（与 v8 同构但无自编内核） |
| `boot-linux-v2.img` | **原版 v2**（GitHub Actions 内核 + 自带 DTB + 最小 initramfs）——已验证 5 秒 panic 循环 |
| `initramfs-v8.cpio.gz` / `cpio_bulletproof.list` / `bulletproof_root/`（init_early + rcS + inittab + fb 页） | initramfs 源 |
| `build/stock-kernel-mtk-seg.img` / `build/zImage-v2-stockdtb-plain.bin` / `build/zImage-v2-stockdtb-plain.bin` | 内核段源 |
| `mkboot.py`（--ramdisk-name 支持）/ `gen_init_cpio` | 打包工具 |
| `autoflash_server.py` | 面板（已修复循环崩溃 bug + 目标精简为 4 个 + 准确标题） |
| `uart_capture.sh`（双波特率轮替）/ `uart_view.py`（8081 监控页） | 串口抓取 |
| `MT6752_Android_scatter.txt` / `Windows刷机清单.md` / `README.md` | 参考 |

### 9.2 已删除（危险/被取代）
`mkcpio.py`、`build_clean_linux.py`（ino=0 缺陷）；`fast_handshake_v4.py`（杀设备）；
六份旧交接文档（并入本文）。

### 9.3 保留勿刷（历史对照）
`boot-linux-v3/v4/v5.img`、`boot-patched.img`、`boot-root.img`、`build/boot-mix*.img`、`build/boot-idzero.img`、`kernel_m79.bin`（v1 内核）。

---

## 10. 勘误归档（已删除文档中的错误结论，防再犯）

- ~~"魅蓝 Note / M1 Note"~~ → **魅蓝1**（Meizu M1；IMEI TAC + 1GB RAM + 8GB eMMC + 实物观察定案）；
- ~~"2GB RAM / 16GB eMMC / 1080p"~~ → 1GB / 8GB / 1280×768（DA 实测 + m79 面板配置）；
- ~~"MT6752 八核"~~ → MT6732 四核（同 die 家族，bootrom 报 0x6752）；
- ~~"Flyme 4.2.1.3Y YunOS"~~ → 实机 4.2.1.3C CMCC（机主照片）；
- ~~"boot 头 id 是魅族私有签名，需逆向 LK"~~ → 标准 mkbootimg SHA-1；
- ~~"wm size 1080x1920"~~ → 该记载未复核，与魅蓝1 规格矛盾；
- ~~"M1 Note 拆机图可作为本机主板参考"~~ → 本机为魅蓝1 主板，布局不同；
- ~~"m71.dts==m79.dts 说明无法区分机型"~~ → m71=魅蓝 Note(FHD 面板)、m79=魅蓝1(HD 面板)，ProjectConfig 可区分。

---

## 11. 未验证事项清单（诚实列出）

1. **v8.5 探针从未开机测试**（刚构建推送）——rcS 的 portmode 写、心跳、panic 循环全部待验证；
2. **finish(2)**（FASTBOOT 复位路径）未验证——若有效则解决自动开机；
3. **panic 热复位是否保留 ram_console** 未验证——v2 循环 + 收割模式自动验证；
4. **内核 console 是否绑定 ttyMT0** 未验证（LK cmdline 盲区）——串口测试自动回答；
5. **手机串口电平**（1.8V/2.8V/3.3V）未实测——万用表一次测量定案；
6. **BT43 新电池的电量计可信度**未验证——电池对照实验可做；
7. **MTK UART 线（USB 口串口模式硬件级）**未尝试——若 portmode 软切换无效，UART 线是硬件级替代。

---

*文档结束。接手人从 §5 开始执行；任何结果对照 §5.4 判读表行动；卡住时查 §7 陷阱清单。*
