# 魅蓝1（M463 / m79 / MT6752）刷 Debian 无头 Linux

> 🔴 **先读 [`STATUS-20261116.md`](STATUS-20261116.md)** —— 2026-11-16 的最新现状：BROM 已打通、boot 已刷入我们的内核、开机 panic 重启循环，卡点与下一步实验都写在那份里。本文档是更早的设计说明，分区/容量等细节已被真机 GPT 数据覆盖（userdata 实际 5.03GB，不是 1180M）。

目标：把这台手机变成一台能 SSH 进去的 Debian 小服务器。**屏幕不是必需品，串口是退路**。

## 一、整体架构（为什么这么设计）

```
boot 分区(16M)                          userdata 分区(1180M)
┌──────────────────────────┐        ┌────────────────────────────┐
│ ANDROID! 头               │        │ ext4, LABEL=linuxroot      │
│ KERNEL 段: 魅族官方 3.10.48│  ───▶  │ Debian 12 armhf (bookworm) │
│ ROOTFS 段: 自制 initramfs │        │ /sbin/init → busybox init  │
└──────────────────────────┘        └────────────────────────────┘
        │                                        ▲
        └── ①开 USB 串口控制台 ②扫描分区找 linuxroot 标签 ③ switch_root
```

三个关键决定：

1. **根文件系统放 `userdata`，不动 `system`。**
   `system` 里是 Android 原厂固件，MT6625 的 WiFi 补丁固件（`/system/etc/firmware/mt6625l_*`）就在那儿。
   留着它，进 Debian 后可以直接挂起来把固件拷过来，不用另外找 ROM 包；万一要回滚 Android 也只差 boot 一个分区。

2. **initramfs 里自带救援 shell。**
   内核没有编 `devtmpfs`、也没有真正的串口线，所以 initramfs 第一件事就是用内核自带的
   legacy android gadget（`/sys/class/android_usb/android0`）开 **CDC-ACM 串口**，
   Mac 上就是 `/dev/tty.usbmodem*`。rootfs 挂不上也不会瞎：直接掉进救援 shell。

3. **rootfs 只做 512M，首次开机自动 `resize2fs` 撑满 1180M。**
   这样传输体积小、刷写快，分区又不会被浪费。

## 二、通信通道

| 通道 | 设备节点 | 说明 |
|---|---|---|
| USB 串口（主） | Mac: `/dev/tty.usbmodem*` 设备上: `/dev/ttyGS0` | 115200 8N1，插根数据线就有 |
| WiFi + SSH（次） | `root@<ip>:22` | 需要 MT6625 固件到位才起得来，第一批不一定有 |
| UART（可选） | `ttyMT0` 921600 | 拆机焊线才有，现在不需要 |

登录：`root` / 默认密码 `m79root`（`/etc/shadow` 里是 SHA-512 hash，进系统后 `passwd` 改）。

## 三、产物

| 文件 | 大小 | 刷到哪个分区 |
|---|---|---|
| `build/boot-linux.img` | 8,235,008 B | `boot` |
| `build/linuxroot.img` | 536,870,912 B | **`userdata`** |
| `build/linuxroot.img.xz` | 82,022,852 B | 上面那个的压缩版 |
| `build/initramfs.cpio.gz` | 884,199 B | （已打进 boot-linux.img） |

回滚用的原厂镜像：`../m1-boot/boot-original.img`。

## 四、刷写（Mac，mtkclient + BROM）

```bash
cd /Users/tangshui/tools/mtkclient
PY=/Users/tangshui/tools/mtk-venv/bin/python      # mtkclient 装在 venv 里，别用系统 python

# 1. 手机断电，进 BROM（MTK 的 VCOM 口），先看能不能认到
$PY mtk.py printgpt

# 2. 写两个分区（一次 BROM 会话里连着写）
$PY mtk.py w boot     ~/test/m463/debian/build/boot-linux.img
$PY mtk.py w userdata ~/test/m463/debian/build/linuxroot.img

# 3. 重启
$PY mtk.py reset
```

也可以直接用 `./flash.sh`（包装了上面三步 + 校验文件大小）。

**回滚 Android**：

```bash
cd /Users/tangshui/tools/mtkclient
/Users/tangshui/tools/mtk-venv/bin/python mtk.py w boot \
  ~/test/m463/debian/boot-original.img
```

（`system` 一直没动，所以回滚 boot 就回到 Android。）

## 五、刷完怎么连

```bash
ls /dev/tty.usbmodem*          # 插着数据线应该能看到
screen /dev/tty.usbmodemXXXX 115200
# 或  cu -l /dev/tty.usbmodemXXXX -s 115200
```

开机顺序（串口上能看到）：

```
[initramfs] USB 串口控制台就绪: /dev/ttyGS0
[initramfs] 根文件系统: /dev/mmcblk0p20
[initramfs] 切根到 Debian…
wb-m1-debian login:
```

## 六、进系统后第一件事

```sh
# 1. 挂上 Android 的 system 分区，把 WiFi 固件捞出来
mkdir -p /mnt/android && mount -o ro /dev/mmcblk0p18 /mnt/android
ls /mnt/android/etc/firmware/          # mt6625l_* 这些
cp /mnt/android/etc/firmware/* /lib/firmware/ 2>/dev/null

# 2. 起 WiFi（SSID/密码已预置在 /etc/wifi.conf，固件到位后开机自动连）
cat /etc/wifi.conf                       # SSID=yyds，已内置
wifi-up                                  # 或手动跑一次
ip a show wlan0

# 3. 稳定下来后改密码 + 装东西
passwd
apt update
```

> `mmcblk0p18` 是 `system` 的推测编号（scatter 里 SYS18），实际编号进系统看 `ls /dev/mmcblk0p*` 或 `/proc/partitions`。

## 七、已知不确定项（第一批刷完要验的）

1. **USB 串口能不能起来** —— 取决于内核 legacy android gadget 在非 Android 环境下能否正常 enable。
   起不来就没法交互，只能看屏幕/重刷，所以这是第一个要验的。
2. **MT6625 WiFi** —— 驱动编进内核了（`CONFIG_MTK_COMBO_WIFI=y`），SSID/密码已写进 `/etc/wifi.conf`（`yyds`/`goodnight`），固件一到位就自动连；但固件要从 system 分区拷，第一批大概没网。
3. **`resize2fs` 首次自动扩容** —— 失败也不影响使用，只是白剩 600M。
4. **macOS 会不会认这个 CDC-ACM** —— 认不出就换台 Linux（`.230`）插线，`dmesg | grep cdc_acm`。

## 八、仓库里的脚本

| 脚本 | 跑在哪 | 作用 |
|---|---|---|
| `configure-rootfs.sh` | 云电脑(box) root | 把 Debian armhf rootfs 配置成可无头启动（inittab/rcS/gadget/wifi/ssh） |
| `initramfs/init` | 设备 | initramfs 的 PID1：开串口 → 找根分区 → switch_root |
| `mkcpio.py` | 任意 | 目录 → cpio(newc)+gzip |
| `mkboot.py` | 任意 | 重打 MTK boot.img（换 kernel + ramdisk，保留原厂 header 其余字段） |
| `flash.sh` | Mac | mtkclient 刷写包装 |
