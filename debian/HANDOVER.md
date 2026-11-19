# 魅蓝1 (M79) 刷 Debian Linux — 交接文档
> 更新: 2026-11-19 深夜 | 上一份详版见 git 历史 + SESSION-20261119.md

## 当前状态（一句话）
boot=v14 在机内循环救援模式；**v16（救援5分钟倒计时自动重启版）已构建并上传 go，
常驻"猎手"进程 /tmp/predator.sh 正在 go 上待命，设备一出现即自动刷入**。
userdata 已是修复版 Debian（busybox 已补、WiFi 拉起脚本已注入）。

## 接手者要做的第一件事
手机按住音量键不放 → 长按电源 10 秒 → 音量再按 5 秒。
preloader 停驻 → go 上暖机中的 mtk 瞬间握手 → boot-v16 自动刷入 → 松手。
此后全自动：v16 救援 5 分钟倒计时 → reboot -f → BROM → 猎手自动接住循环。
若屏幕出现 STEP5/6（IP/SSH），去路由器找设备 ssh root@IP 密码 m79root。

## 已验证事实（勿再重复验证）
1. 内核+initramfs 链路完好：黑匣子实测 64 秒存活、cache 滚动写入成功。
2. 屏幕: 768宽×1280高 竖屏, BPP32, 字节序 RGBA(不交换), 3页缓冲。源: 原厂 dmesg
   `MTK_FB_XRES=768, MTKFB_YRES=1280`。按此渲染文字清晰。
3. cmdline 含 `printk.disable_uart=1`（串口日志被原厂禁用）。
4. 切 Debian 曾失败的根因: rootfs 缺 /bin/busybox → /sbin/init 死链。已修复。
5. v10.2 两 bug: 缺 /cache 目录致 ext4 mount 必败; fb 位图没打进 cpio。均已修。
6. USB 枚举全阻: 原厂 muic(tsu6721) probe failed; musb cmode 1=正常/2=仅充电。
   v13-v16 已加热插守护+cmode=1+acm,ecm 复合 gadget，**但 USB 至今未枚举成功**。
7. WiFi: 内核内置 wmt+wlan 驱动; 需挂原厂 system(原封未动)跑 /system/bin/wmt_loader
   (用自带 linker + LD_LIBRARY_PATH=/system/lib) 再 echo 1 > /dev/wmtWifi(c 153 0)。
   Debian 侧 wpa_supplicant/dropbear/wifi-up 齐备, SSID=yyds 已在 /etc/wifi.conf。
8. expdb 里有旧 CI 内核 panic(ddp_manager.c:1115)——自编内核黑屏元凶，勿再踩。
   内核"关机存日志到 eMMC"机制在本机损坏(ipanic scatter 找不到分区)。
9. 分区: userdata=mmcblk0p19(5.4GB), system=p17(1.5GB), cache=p18(112MB),
   boot=p7(扇区59648), para 只有充电配置。敏感: nvram/proinfo/nvdata。

## 安全红线（违反即砖）
- 永不刷写 preloader 分区
- 永不执行 da seccfg unlock（SEJ legacy 路径写坏加密块=全无反应）
- 写入任何分区前按 PARTNAME 确认，名字不符绝不写
- nvram/proinfo 是基带敏感区，不碰

## 刷机操作
- go 机: cd ~/mtkclient; 按住音量键插线 → 停驻 0e8d:2001 →
  `echo 1122 | sudo -S python3 mtk.py w boot boot-v16.img`
- 或被动等猎手: ~/predator.sh 已循环执行（注意: go 重启后需重新启动: setsid ~/predator.sh &） `mtk.py w boot boot-v16.img`
- 刷 userdata: `mtk.py w userdata /tmp/linuxroot.img`（/tmp/linuxroot.img 为最新修复版）
- 读 cache: `mtk.py r cache /tmp/x.img`；黑匣子数据在偏移 0x800000，
  v15+ 错误日志在 0x900000(mount错误)/0xA00000(WiFi诊断)。
- 回读校验: `mtk.py r boot /tmp/v.img` 后比对 md5。

## 文件地图（本仓库 debian/）
- build/boot-v16.img        最新 boot（竖屏步进页+倒计时重启）
- build/linuxroot.img       修复版 Debian rootfs（512MB）
- bulletproof_root/init_v16 最新 init（黑匣子+切Debian+救援倒计时+步进画屏）
- build/step_pages/*.raw    768x1280 RGBA 各步骤页面
- SESSION-20261119.md       今日全部发现详录
- mkboot.py                 MTK boot 重打包（保留原厂 header）
- BLACKBOX.md / AUDIT.md    黑匣子原理 / 技术审计


## 硬件诊断结论（2026-11-20，机主确认）
**充电排线损坏**——数据通道正常（尾插数据脚/主板排线完好），充电走的那条排线断了。
修复件：充电排线/尾插小板，非主板。
证据链：fastboot 全速传输 7.5MB 正常(数据脚好)；插线无充电图标、不触发开机、
不进 BROM、拆装电池无区别(电源脚坏)；软件重启后 ROM 检测不到 VBUS 会跳过 USB
初始化(所以暖机猎手接不到枚举——不是窗口问题，是 ROM 根本不开 USB)。
**后果：手机无法充电、无法进 BROM/preloader、软件层无解。**
行动：① 换充电排线（维修店常规业务）→ 修好后按原流程 10 分钟收官；
② 修复前保持关机保电（M1 电池 BT43 可拆，可万能充外充）。
v16 猎手/镜像/文档全部就绪，尾插一修即可收官。

## 开放问题
1. USB 枚举: cmode=1 后仍未通。下一刀: 检查 musb 是否停在 host 模式
   （找 /sys 内 musb mode 属性强制 peripheral），或彻底依赖 WiFi 通道。
2. wmt_loader 在 Debian/chroot 环境能否成功初始化 MT6630（从未实测成功过）。
3. boot_mode=8 的确切含义。
4. 若 STEP 页卡在 1/2: wmt_loader 失败，读 cache 0xA00000 拿 wmt.log。
