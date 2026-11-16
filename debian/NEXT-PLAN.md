# 明天先读这个 —— 魅蓝 Note (M463/m79/MT6752) 刷 Linux 续

> ⚠️ **本文已过期（写于 2026-11-16 03:30）。** 之后的实际进展全部记在 [`STATUS-20261116.md`](STATUS-20261116.md)：
> BROM **握手已成功**（旧脚本自身缺陷导致误判），真机 GPT 已读出，原厂 boot/recovery 已备份并校验，
> `boot-linux.img` 已刷入 boot 分区（sector 59648），**现在卡在内核起不来：LK logo 停住 + 周期性震动重启**。
> 本文里"卡在 BROM 握手""userdata 1.15G"等描述均已失效，仅作历史留痕。

> 写于 2026-11-16 03:30，用于上下文丢失后恢复现场。
> 一句话现状：**内核编好了、rootfs 做好了、刷机包备好了，但一个字节都没写进手机 —— 卡在 BROM 握手。**
> **明天的目标不是刷机，是证明 BROM 能不能握手。**

---

## 0. 先纠正两个叫法（别再被带偏）

| 项目 | 正确 | 之前叫错的 |
|---|---|---|
| 型号 | **M463 = 魅蓝 Note**（2014-12，2GB RAM） | "魅蓝1"（那是 M465 / MT6732） |
| SoC | **MT6752** | — |
| 构建目标 | **m79**（设备代号，不是芯片名） | — |

实证：`kernel/arch/arm/boot/dts/m79.dts` 第 3 行 = `/include/ "mt6752.dtsi"`；`m71.dts` 同样；
`build.sh` 只有 m71/m79 两个目标，全仓库无 mt6732 构建目标；
`MT6752_Android_scatter.txt` 内 `platform: MT6752`。

**所以「m79 是 MT6732、芯片对不上」的外部判断是错的，不用再核对。**
（想彻底安心就翻过来看背面印的型号，应该是 M463。）

---

## 1. 已经排除的错误归因

| 旧结论 | 现在的判断 |
|---|---|
| "BROM 有 2~4 秒看门狗，超时就断" | **大概率是我自己的脚本在杀设备**，见下 |
| "必须整包发 A0 0A 50 05，拆开发必失败" | **错**。标准 MTK BROM 是逐字节：A0→5F / 0A→F5 / 50→AF / 05→FA，每字节等应答 |
| "udev 规则 authorized=0 是元凶" | 是元凶**之一**，已删除，但删完没做过干净复测 |
| "Windows 有 VCOM 所以天然能通" | 表述不严谨。Windows 只是**换一套独立 USB 栈 + 官方 DA 做对照**，不是保证成功 |
| "fastboot 能救" | 仍然不可行，这台机 fastboot 是残缺实现（getvar/flash 卡死）|

### 核心假设（明天要验证的就是它）
旧脚本 `fast_handshake_v4.py` 有三个致命缺陷：
1. `except Exception: return False` —— 吞掉一切异常，EBUSY / 超时 / 端点错全都一个样；
2. **从未 `detach_kernel_driver`，也从未 `claim_interface`** —— 内核驱动占着接口时 write 直接 EBUSY；
3. 整包发 4 字节 + `read(64)` 一次性读 + 严格比对 4 字节 —— 如果 BROM 只回一个 `0x5F`，
   脚本只拿到 1 字节，比对失败 → 判"握手失败" → `dispose_resources()` **主动释放设备** → BROM 复位。

**推论：所谓"设备只活 2~4 秒"，很可能是这一套自己在循环杀设备，而不是看门狗。**
`brom_handshake_v5.py` 就是为验证这事写的（逐字节 + 详细日志 + 不清场先看描述符）。

---

## 2. 硬事实备份（丢了就查这里）

**源码**：`~/test/m463`（fork: `github.com/tangshui9527/m463`），内核 3.10.48，官方 GPL。
编译必须 gcc 4.9.4 + python2.7（`/opt/py27`），4 核约 4 分钟。

**分区（scatter，EMMC）**
- preloader 0x40000 / lk 0x60000 / boot 16M / recovery 16M
- system 1.31G / userdata 1.15G（rootfs 装这里）
- **没有独立 KERNEL 分区**，内核必须打进 boot.img

**产物**（全在 `~/test/m463/debian/`）
- `kernel_m79.bin` 7,347,495B，md5 `b3a9888864b453f55bccff9e6d1c2bf3`
- `boot-linux.img` 8,235,008B（原厂 header + 新内核 + initramfs 884,711B）
- `linuxroot.img` 512MiB ext4（`-O ^64bit,^metadata_csum_seed,^orphan_file`）
- `boot-original.img` 原厂 boot，**回滚唯一依靠**
- `boot-patched.img` 打过 root 的原厂 boot（ro.secure=0 等）

**Windows 包**：`~/Desktop/m79-win-flash/`（463MB）
- `firmware/` + `tools/`（SPFT v5.1924 / WinRAR7 / MTK 驱动）
- 固件要拷到 `C:\m79\`（SPFT 报 8417 = 路径含中文）

**go 访问**：`ssh tang@go`（Tailscale 100.74.43.40），sudo 密码 1122。
2026-11-16 03:16 起 SSH 超时（应该是睡了），**叫醒它**再开始。

---

## 3. 明天三步走

### 阶段 A（优先级 1，在 go 上做，30 分钟）
唯一目的：拿到 BROM 的**真实应答**。

```bash
# 1. 部署两个脚本
scp ~/test/m463/debian/brom_handshake_v5.py  tang@go:~/
scp ~/test/m463/debian/prep-usb-clean.sh     tang@go:~/

# 2. 主机侧清场（只解驱动抢占，不改内核、不加黑名单）
ssh tang@go 'sudo /home/tang/prep-usb-clean.sh'   # 密码 1122

# 3. 跑诊断（先只 dump 描述符树，看端点/占用情况）
ssh tang@go 'sudo python3 /home/tang/brom_handshake_v5.py --dump'

# 4. 真握手
ssh tang@go 'sudo python3 /home/tang/brom_handshake_v5.py --wait 120'
```

pyusb 缺的话：`sudo pacman -S python-pyusb`（go 是 Omarchy/Arch），或用 mtkclient 的 venv。

**手机操作**：完全关机 → 按住音量下（不行就两个音量键一起）→ 插 USB。

### 判定表（照这个读输出）

| 现象 | 结论 | 下一步 |
|---|---|---|
| 描述符树里 bulk OUT/IN 都在，claim OK，逐字节 4 步全 ✓ | **通信层通**，之前全是假失败 | 直接上 mtkclient 读 GPT，见阶段 C |
| `write 返回 1` 但 `IN_TIMEOUT` | OUT 通、设备不应答 | 试 `--packet` 对照；再看是否插入时机太晚（BROM 已进 preloader）|
| `OUT_FAIL` + EBUSY | 接口被占 | 复查 `lsmod`，看是不是 ModemManager 又起来了 |
| 读到 `5f` 后第 2 步超时 | 设备只接受第一字节 | 记录，可能是时序要加 delay（v5 里加 `--delay`）|
| 描述符树里**没有 bulk 端点** | 设备不是 BROM 或伪装设备 | 换线、换口（直连，别过 hub）|
| 一直不出现 0e8d | 根本没进 BROM | 查电池电量、按键组合、尾插（已知松，要顶住）|

### 阶段 B（优先级 2，只有 A 彻底不通才做）
两个子选项，二选一：

**B1 Windows + SPFT（对照实验）**
按 `~/Desktop/m79-win-flash/00-先读我.txt` 走，但**只到"看到 DA 加载、列出分区表"为止**，
**不要点 Download**。SPFT 能进 DA = 证明手机 BROM 好、Linux 主机侧有问题。

**B2 Windows + mtkclient + UsbDk**
VCOM 驱动是给 SPFT 用的；mtkclient 在 Windows 上要 **UsbDk**（libusb 后端）。
别装了 VCOM 就以为 mtkclient 也能跑。

### 阶段 C（只有 A 或 B 成功后才做，只读）
```bash
# go 上
cd ~/mtkclient
python3 mtk.py r boot boot-stock.img      # 备份原厂 boot
python3 mtk.py r recovery recovery-stock.img
python3 mtk.py printgpt                   # 拿真实分区表
```
**核对三件事再谈写入**：① GPT 里 boot 分区起止与 scatter 一致 ② boot-original.img 能读回且 md5 与备份一致 ③ 手机 HW code 确实是 6752。

### 阶段 D（写入，最早也是明天下午）
1. 只刷 boot：`python3 mtk.py w boot boot-linux.img`
2. 进系统验证：USB 串口（内核 legacy android gadget CDC-ACM）出现 `/dev/tty.usbmodem*`，
   能登进去、`dmesg` 干净 —— **这一步过了才证明内核真的适配**
3. 再刷 userdata（`linuxroot.img`）
4. 翻车回滚：`python3 mtk.py w boot boot-original.img`

---

## 4. 红线（明天不要做）

- ❌ 不要再改内核、不要再重编（内核没问题，问题在通信）
- ❌ 不要再写 udev 规则 / 黑名单（上次就是 `authorized=0` 那条坑）
- ❌ 不要在拿到 GPT 和 boot 备份之前写任何分区
- ❌ 不要在 go 上 `pkill -f` 乱杀（会连带杀 ssh 会话，用 `pgrep -af "[m]tk"`）
- ❌ 不要指望 fastboot

## 5. 相关文件索引

| 文件 | 用途 |
|---|---|
| `~/test/m463/debian/NEXT-PLAN.md` | 本文 |
| `~/test/m463/debian/brom_handshake_v5.py` | 逐字节握手诊断（新）|
| `~/test/m463/debian/prep-usb-clean.sh` | 主机侧清场（新）|
| `~/test/m463/debian/fast_handshake_v4.py` | 旧脚本，**有缺陷，别再用** |
| `~/test/m463/debian/Windows刷机清单.md` | Windows 详细步骤 + 报错对照 |
| `~/test/m463/debian/README.md` | rootfs/initramfs/mkboot 说明 |
| `~/Desktop/m79-win-flash/` | 明天要拷到 Windows 的包 |
