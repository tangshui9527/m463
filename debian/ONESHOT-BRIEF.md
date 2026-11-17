# 魅蓝1 刷 Linux：当前问题定案 + 一次刷成功方案（外部协助者简报）

> 📬 **本文写给被请来重新构思方案的技术协助者。**
> 机主目标：**一次刷机成功，手机直接启动完整 Linux（Debian），全程不需要串口调试/TTL 硬件。**
> 本文包含：设备身份、已验证事实、核心谜团、完整实验矩阵、仓库资源、机主意向。
> 请基于 §3 的已验证事实和 §4 的未解谜团重新构思方案——**前人踩过的坑不必再踩**。
> 配套总文档：[`HANDOVER.md`](HANDOVER.md)（环境/面板/刷写方法/陷阱清单/救援命令）。

---

## 1. 设备（已定案，勿再混淆）

| 项 | 值 |
|---|---|
| 机型 | **魅蓝1**（Meizu M1，2015-01，699 元版） |
| 销售系列 | M463（魅族官方源码仓库 [meizuosc/m463](https://github.com/meizuosc/m463) 描述 "M1 Note / M1 series"——同仓库覆盖两台机） |
| 项目代号 | **m79**（ProjectConfig 面板 = hx8394d HD 1280×768 = 本机面板，实测吻合） |
| 芯片 | **MT6732** 四核（bootrom 报家族码 **0x6752**，与 MT6752 同 die——mtkclient 会把它当 MT6752，家族软件全兼容） |
| RAM / eMMC | **1GB / 8GB**（DA 实测） |
| 屏幕 | 5.0" **1280×768** |
| 电池 | BT43（机主已换新，可能副厂——**电量计可信度未知，可能是变量之一**） |
| 固件 | Flyme 4.2.1.3C（CMCC），Android 4.4.4 |
| 系统 "型号" 字符串 | `m1`（魅蓝 Note 和魅蓝1 都显示 m1，不能作为区分依据） |
| IMEI | 867436022519241（TAC 86743602 = MEIZU M1，[fccid.io](https://fccid.io/TAC/86743602)） |

⚠️ 前人文档曾误判为"魅蓝 Note / MT6752 八核 / 2GB+16GB / 1080p"——已勘误。

## 2. 项目目标与现状

**目标**：这台手机跑完整 Linux（Debian 12 armhf rootfs 已构建并预配置），
通过 USB 口登录（CDC-ACM 串口 或 USB 网络），全程**一次刷机成功、不需要串口调试硬件**。

**现状**：
- mtkclient 刷写链路全通（多次真实刷写成功，preloader 从未触碰，安全备份齐全）；
- boot 分区当前 = v8.5 探针（原厂内核 + 早期串口 initramfs + panic 循环——**刚构建未测试**）；
- **两个失败模式未解**（见 §3）——这是请你来重新构思的原因。

## 3. 已验证事实（全部有实测/源码证据，不要重复验证）

1. **刷写**：mtkclient 从手机"preloader 停驻态"（0e8d:2001，关机插线后手机自己会停在这个状态）
   直接漏洞利用刷写，**8MB/s，512MB 也行，无窗口竞争，无需音量键**——刷写不是瓶颈；
2. **boot 头 id 字段 = 标准 mkbootimg SHA-1**（原厂值逐字节复现），无私有签名；
3. **原厂内核能启动**：boot 分区刷回原厂镜像 → Flyme 正常运行 → **硬件和原厂内核没问题**；
4. **USB 连接器可软件切 UART**：`echo 1 > /sys/devices/platform/mt_usb/portmode`
   → D+/D- 变为 ttyMT0 的 RX/TX（内核驱动源码 usb20.c/usb20_phy.c 全链验证）；
5. **BROM 窗口 = 4.6 秒固定超时**（dmesg 5 次实测精确周期），超时自动进充电模式；
6. **关机插线 = 充电模式挂起**（LK 层画充电图标，不启动内核）——MTK_KERNEL_POWER_OFF_CHARGING 行为；
7. **legacy DA 的 reset/FINISH = 断电**（不是重启），参数 0/1 实测，2 未验证；
8. **devmem 访问 RGU 寄存器（0x10007000x）会挂死内核**（MPU 保护）——initramfs 脚本禁用；
9. **MTK_KERNEL_POWER_OFF_CHARGING=yes**、**MTK_UART_USB_SWITCH**（USB↔UART 切换）等特性在配置中；
10. 魅族 GPL 源码不完整（mach 头/GPIO 表/mtprintk 缺失）——UART 焊点号无法从源码获得。

## 4. 核心谜团：两个失败模式（请重新构思的主对象）

**实验矩阵**（boot 镜像 → 实机现象）：

| # | 内核 | ramdisk/initramfs | 现象 |
|---|---|---|---|
| 1 | 原厂（m79） | 原厂完整（Android init + sbchk + 属性，1MB） | **Flyme 正常运行** ✅ |
| 2 | 原厂 | 原厂 ramdisk 重打包 + 改 default.prop（历史 boot-root 实验） | **5 秒 panic 循环** |
| 3 | 原厂（逐字节同 #1） | **我们的 minimal busybox initramfs**（0.9~1.9MB，多轮变体） | **静默挂死**：Logo→黑屏背光常亮，无 panic、不重启、无 USB 枚举、串口零输出 |
| 4 | 自编 v2（m79 配置 + VT/FBCON/DEVTMPFS，gcc 4.9.4） | 我们的 minimal initramfs | **3~5 秒 panic 循环**（屏幕无文字） |
| 5 | 自编 v2 + **原厂 DTB 拼接** | 我们的 minimal initramfs（含 portmode 切换） | 同 #4（未抓到日志） |

**谜团 A（模式 3）**：原厂内核 + 我们的最小 initramfs = **静默挂死**（不 panic——否则会 5 秒重启）。
- 它可能真挂死了，也可能**活着但不可见**（救援 shell 空转）——无法区分（无输出通道）；
- #2 证明：原厂内核 + 修改过的 ramdisk **能到达用户态**（panic = 到了 init）；
- 那我们的 minimal initramfs 差在**哪个具体内容**导致挂死而非 panic？
  候选：尺寸（1.9MB vs 1MB）/ gzip 参数 / cpio 结构细节 / 缺 sbchk / 缺属性 / 缺 Android init 的某个副作用 / **initrd 尺寸上限（LK cmdline initrd=0x44000000,0x200000=2MB，我们 1.9MB 贴着上限）**……

**谜团 B（模式 4）**：自编内核（同源码、同 m79 配置、gcc 4.9.4）+ 原厂 DTB 拼接 = 3~5 秒 panic 循环。
- 原厂内核同源不 panic，自编内核必 panic——**编译器/构建差异**是头号嫌疑（gcc 4.9.4 重编 2014 年内核的经典雷区）；
- 屏幕无文字：死在 console_init/fb probe 之前（VT/FBCON 已开却无字）。

**共同盲区**：两个模式都死在**任何输出通道建立之前**（串口未初始化/绑定未知、fb 未点亮、USB 未枚举）——
至今没有一行内核日志。**这是需要你重新构思的核心问题：如何在不依赖串口硬件的前提下，
拿到这两个失败模式的第一行内核日志（或让一次刷入直接成功）。**

## 5. 已排除的方向（别再走）

1. **[待黑匣子验证，原结论无日志证据]** "关机插线 = LK 层挂起不进内核"——
   充电图标同样符合 KPOC 解释（MTK_KERNEL_POWER_OFF_CHARGING=yes：LK 启动内核
   boot_mode=8/androidboot.mode=charger，充电动画由用户态画；我们的内核在充电模式下
   也会跑 initramfs，但当时状态页分辨率错误画不出来，充电图标可能是 LK logo 的残留显示）。
   **黑匣子测试：关机插线等一分钟读 cache——boot_mode=8 + 有日志 = 插线即跑 initramfs，
   电源键问题消失，/init 不区分启动模式照常进 Debian。**
2. ~~devmem 写 WDT/SWRST 寄存器复位~~ → MPU 保护，访问即挂死内核（v8.2/v8.3 实测）；
3. ~~legacy DA 的 reset 实现自动重启~~ → FINISH 语义 = 断电（0/1 实测）；
4. ~~ModemManager/brltty 抢串口~~ → go 上不存在；
5. ~~boot 头 id 私有签名~~ → 标准 SHA-1；
6. ~~电池没电~~ → 机主确认有电（但副厂电量计可信度仍是开放变量）。

## 6. 仓库资源（你可以直接用）

| 路径 | 内容 |
|---|---|
| `debian/HANDOVER.md` | 总交接文档（环境/面板/刷写方法/12 条陷阱清单/救援命令） |
| `debian/boot-linux-v8.img` | v8.5 探针镜像（原厂内核 + 早期串口 initramfs + panic 循环）|
| `debian/boot-linux-v2.img` | 自编 v2 内核镜像（实测 panic 循环）|
| `debian/boot-stock-20261116.img` | 原厂 boot 分区 16MB 完整备份（真机 dump） |
| `debian/bulletproof_root/` + `cpio_bulletproof.list` + `gen_init_cpio`（源码在 `kernel/usr/gen_init_cpio.c`） | initramfs 构建系统 |
| `debian/build/linuxroot.img` | Debian 12 armhf rootfs（512MB ext4，**超 GitHub 限制，由机主单独提供**；预配置 ttyGS0 getty + dropbear + resize2fs 首启扩容 + root 密码 m79root） |
| `debian/configure-rootfs.sh` | rootfs 的完整配置脚本（inittab/rcS/网络/SSH 全部可读——Debian 侧行为以此为准） |
| `debian/autoflash_server.py` | 刷机面板（端口 8080，含修复史） |
| `status-20261116/kernel.config.m79-20261116` | 自编内核的完整 .config（3060 行） |
| `kernel/` | 魅族 GPL 内核源码 3.10.48（m463，覆盖 M1 Note/M1；**mach 头/GPIO 表缺失**——UART 焊点号不可考） |

⚠️ 大文件不在 git：`build/linuxroot.img`（512MB）与部分 img 由机主单独提供；git 内的 img 见 `debian/.gitignore` 的 force-add 清单（boot-linux-v8/v2、boot-stock）。

## 7. 刷写方法（已实测，机主零按键即可完成刷写）

手机关机状态**直接插 USB 线**（不用按任何键）→ 手机自己停在 preloader/META（0e8d:2001，稳定驻留）
→ mtkclient 从该状态直接漏洞利用刷写（8MB/s）：

```bash
# go 上（ssh tang@192.168.31.90，sudo 密码 1122）
cd ~/mtkclient
echo 1122 | sudo -S python3 -u mtk.py multi "w boot boot-linux-v8.img;reset"
# 或面板（http://192.168.31.90:8080）目标按钮自动执行
```

- BROM 窗口（4.6 秒）竞速**不再需要**——这是 2026-11-18 的重大流程改进；
- 写入失败的代价 = 那次没刷上（可重试，无永久损坏）；
- 红线：**永不刷 preloader 分区 / 永不 `da seccfg unlock`**。

## 8. 机主意向与约束

1. **一次刷成功**：不想多轮"刷-失败-再刷"的试错（但客观上重试零成本、无永久损坏）；
2. **不需要串口调试/TTL 硬件**：机主没有屏幕/键盘之外的输入输出手段（手机屏幕是唯一显示器）；
3. **直接进 Linux**：目标是 Debian rootfs（已构建预配置）；
4. 电源键按压困难（手机拆解状态）——**刷完后的开机依赖：插入充电器（LK 充电挂起）或一次电源键**；
5. 机主对外部协助者的期待：**重新构思"如何拿到第一行内核日志"或"如何一次刷成直接进 Debian"**。

## 9. 供重新构思的开放问题清单

1. 原厂内核 + minimal initramfs 的静默挂死，与 原厂内核 + 修改版原厂 ramdisk 的 5 秒 panic——
   **两者的差异到底是 ramdisk 的哪个内容/属性**？能否设计一个"最小差异对照"实验系列？
2. initrd=0x44000000,0x200000（2MB 上限）与 1.9MB initramfs 的贴线关系——
   **LK 实际传递的 initrd 尺寸**能否通过 mtkclient 的 DA 内存读取验证（DA 阶段读 0x44000000 头部）？
3. 自编内核的 3~5 秒 panic：**ram_console（CONFIG_MTK_RAM_CONSOLE=y，0x43F00000）在 panic 循环中
   是否每轮可被抓取**（热复位保留性未验证——循环提供无限次尝试）？
4. 魅蓝1 的面板（hx8394d）在 m79 内核配置中编译——**自编内核 3~5 秒 panic 是否正是面板 probe**？
   （fbcon 无字 + mtkfb probe 时序吻合）——若是，静默挂死（模式3）可能是面板等待的另一面？
5. 魅族 LK 实际传递的 cmdline（console=?、initrd=?）——能否通过 mtkclient 的 DA 阶段读 ATAG/DTB
   内存（0x44000000 附近 / LK 的 cmdline 缓冲）来获取？
6. MTK_UART_USB_SWITCH / portmode 的 PHY 级 UART 模式——**LK/preloader 阶段**能否同样切换
   （preloader 源码不在手，但 PHY 寄存器写可以通过 DA poke 完成）——若能，preloader/LK 日志
   也能从 USB 口读出（DA poke 0x10007000x 之外的 PHY 寄存器）？

## 10. 联系与交接

- 机主持有：全部镜像的原始文件（含 linuxroot.img 512MB）、两台主机、本仓库；
- 刷写/观察的全部工具已就绪（面板 8080 / 串口监控 8081 / 自动抓取器）；
- 本文 + 仓库 = 全部上下文。**有新构思请直接改仓库或联系机主。**
