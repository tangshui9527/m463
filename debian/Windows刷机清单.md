# 魅蓝1（MT6752/M79）刷 Debian —— Windows SP Flash Tool 操作清单

> 日期：2026-11-16
> 结论：Linux（go/mtkclient + 自写握手脚本）折腾一晚卡在 BROM 握手，转 Windows + SP Flash Tool（MT6752 老芯片官方工具，成功率最高）。

## 一、为什么今晚失败了（一句话版）

MT6752（2014 年老芯片）的 BROM 握手用 mtkclient / 自写脚本都不稳。官方正确工具是 **SP Flash Tool v5.x**（对 MT6752 兼容性最好，新版工具反而因 DA 太新握手失败）。

## 二、要准备的东西

### 1. Windows 电脑上需要装/下载
- **SP Flash Tool v5.2124**（经典稳定版，专治 MT6752 老平台）
- **MediaTek USB VCOM / PreLoader 驱动**（必需！装不上就关闭驱动签名强制）
- **DA 文件**：MTK_AllInOne_DA.bin 或 MT6752 专用 DA（放英文路径）

### 2. 要拷到 Windows 电脑的文件（从 Mac `~/test/m463/debian/`）
| 文件 | 作用 |
|------|------|
| `MT6752_Android_scatter.txt` | 分区表（SP Flash Tool 加载它） |
| `build/boot-linux.img` (8,235,008B) | 要刷入 boot 分区的 Linux 内核镜像 |
| `build/linuxroot.img` (512MiB) | 要刷入 userdata 分区的 Debian rootfs |
| `boot-original.img` | 原厂 boot（救砖回滚用） |

> 说明：boot 16M / userdata 1.15G，内核打进 boot.img，rootfs 放 userdata，**不动 system 分区**（留 MT6625 固件）。

## 三、操作步骤

1. **装驱动**：手机关机插 USB，设备管理器出现「未知设备/MediaTek USB Port」时手动装 VCOM 驱动。
2. **开 SP Flash Tool** → 点「Scatter-loading」选 `MT6752_Android_scatter.txt`。
3. 分区列表自动加载，**只勾选 boot 和 userdata**（nvram/proinfo/preloader 千万别勾，乱写丢 IMEI）。
4. 模式选 **「Download Only」**（不要 Format All）。
5. 点顶部 **「Download」** 按钮，进入等待状态。
6. **连接时序（关键）**：
   - 手机完全关机、拔线
   - **按住「音量减」不放** → 插 USB 线（先按后插）
   - 插线后继续按住 10~15 秒，屏幕全程黑屏
7. 工具识别到设备自动开始刷写，进度条走完弹绿色对勾 = 完成。
8. 刷完拔线，长按电源开机。

## 四、可能遇到的报错

| 报错 | 原因 | 解决 |
|------|------|------|
| 一直不认设备 | 驱动没装对 | 重装 VCOM，关驱动签名强制 |
| S_FT_ENABLE_DRAM_FAIL (4032) | DA/固件不匹配 | 换 MTK_AllInOne_DA.bin，用 v5.x 工具 |
| 下载 DA 卡 100% | DA 版本太新 | 换旧版 DA，用 v5.2124 |
| 进度条中途断 | USB 供电不稳 | 换原装数据线、直插主板 USB 2.0 口 |

## 五、救命回滚

刷坏 boot 导致开不了机，用同样方法刷回 `boot-original.img`（原厂 Android 4.2.1.3C）即可恢复。

## 六、刷完 Debian 后的验证

- 拔线 → 长按电源开机 → 观察 USB 是否出 CDC-ACM 串口（Mac 上 `/dev/tty.usbmodem*`）
- 内核已内置 WiFi（yyds / goodnight），进系统后 `nmcli` 或 `wpa_supplicant` 连
- 首次进系统把 `/system/etc/firmware/mt6625l_*` 拷进 rootfs（system 没动，固件还在）
