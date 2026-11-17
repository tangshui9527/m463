# 技术审计报告：黑匣子方案五项审查（2026-11-18）

> 📬 应外部协助者要求，对黑匣子方案做**先审计后实施**的技术审查。
> 五项审计全部基于本仓库内的源码、二进制、配置文件完成——**未做任何臆测**。
> 审计结论：**原方案的两级架构成立，但第一级不需要新建——平台已经内置，直接用它即可。**

---

## 审计项 1：M79 内核的 MTK RAM Console 实现及内存地址

### 结论：✅ 内核已内置完整实现，地址 0x43F00000（64KB），热复位设计为保留

**配置证据**（status-20261116/kernel.config.m79-20261116，自编内核实测抽取）：
```
CONFIG_MTK_RAM_CONSOLE=y
CONFIG_MTK_RAM_CONSOLE_USING_DRAM=y      ← 使用 DRAM 而非 SRAM
CONFIG_MTK_RAM_CONSOLE_DRAM_ADDR=0x43F00000
CONFIG_MTK_RAM_CONSOLE_DRAM_SIZE=0x10000 (64KB)
CONFIG_MTK_RAM_CONSOLE_ADDR=0xF912C000   (SRAM 变体, 未启用)
CONFIG_MTK_RAM_CONSOLE_SIZE=0x4000
```

**原厂内核二进制证据**（stock vmlinux 反字符串）：
```
ram_console_early_init                                    ← 驱动存在且早初始化
show last_kmsg2 sig %d, size %d, hw_status %u, reboot_mode %u!
read_poweroff_log
3ram_console: failed to allocate buffer for header buffer.
3ram_console: failed to allocate buffer for old log
```

**重要发现**：
1. 驱动源码在 GPL 放出中**缺失**（ram_console.c 不在树内，只有 platform-data 头）——
   但编译产物证明魅族编译了它，且**做了魅族定制**：proc 节点改名为 **last_kmsg2**，
   缓冲区头含 `sig / size / hw_status / reboot_mode` 四字段。
2. `reboot_mode` 字段的存在证明：**该机制设计上就是跨热复位工作的**——
   驱动启动时校验上一轮缓冲区的签名和复位原因（这是它的核心功能，不是附加功能）。
3. 自编 v2 内核配置 `CONFIG_MTK_RAM_CONSOLE=y` ✓——**自编内核同样内置捕获**。

### 对方案的意义
**不需要新建任何内核级捕获机制。** panic 时刻的完整内核日志会由平台自带的
ram_console 自动写入 0x43F00000。我们要做的只有"第二级"：把它读出来搬运到 eMMC。

---

## 审计项 2：是否能够增加 ramoops/pstore

### 结论：✅ 技术上可行但**不建议**——平台原生机制已覆盖，增加是纯风险

**事实**：
- 原厂/自编内核配置 `# CONFIG_PSTORE is not set`——当前内核无 pstore；
- 3.10 内核支持 pstore/ramoops（主线代码在树内），启用需：
  1. 重编内核（CONFIG_PSTORE + CONFIG_PSTORE_RAM，管线已验证可行）；
  2. 一块保留 DRAM 区域——需要 DTB 修改或 cmdline mem= 限制；
  3. **风险**：LK 传递的 cmdline 会覆盖我们的设置（CONFIG_CMDLINE_FROM_BOOTLOADER=y），
     DTB 内存节点与 LK 的内存报告的交互在 MTK 平台上不确定；
  4. **风险**：pstore 的保留区与 preloader 的 DDR 训练草稿区可能冲突（0x43F00000 区域
     在关机路径已被刷写的实测证明 preloader 会使用低地址区）。

**裁定**：MTK ram_console 已经完成"内核 panic → 保留内存 → 下次启动读出"的
全部第一级功能。**增加 pstore 是重复建设，收益为零、风险为正。否决。**

---

## 审计项 3：Panic 自动重启时 DRAM 保留情况

### 结论：设计上应保留（强证据），实测一次定案

**支持保留的证据**：
1. ram_console 驱动的 `reboot_mode` 字段——设计上就是"上一轮复位的模式"跨启动传递；
2. `last_kmsg2` 的 proc 入口在魅族原厂 init 中被引用（魅族自家固件依赖此机制）；
3. MTK 平台的 last_kmsg 机制的行业实现：WDT/panic 复位不断 DRAM 电，
   preloader 检测热复位标志后跳过 DDR 全训练、保留内容。

**反对保留的证据**：
1. 关机→BROM 路径实测 0x43F00000 被刷成 `<<<RAM_RW>>>` 训练标记——
   但这是**冷启动路径**（关机后 DDR 完全断电再训练），不代表热复位路径。

**定案实验（黑匣子方案自动完成）**：
v2 panic 循环运行时，手机每 ~11 秒热复位一轮。循环的每轮 BROM 窗口
用 mtkclient 直接 peek 0x43F00000（64KB）——
**若读到内核文本（"Booting Linux"/"Linux version"）= 热复位保留 ✓ 定案**。

⚠️ 技术难点：panic 循环中 preloader 阶段仅 ~1 秒/轮，mtkclient 连接需要
竞速命中。失败多轮 = 改用第二级的 cache 中转（panic 文本先写 cache 再说）。

---

## 审计项 4：mtkclient DA 对 cache 或独立分区的读回能力

### 结论：✅ 完全可用（实测证据充分）

| 能力 | 状态 | 证据 |
|---|---|---|
| 分区读取（按名字） | ✅ | mtkclient 标准备份流程；今晚 0x43F00000 读/写会话均成功 |
| 内存读取（DA peek） | ✅ | SRAM 131KB 实测读取成功 |
| 速度 | ~8MB/s | 刷写实测 |
| 从 preloader 停驻态连接 | ✅ | 8.6MB 刷写即从此状态完成 |
| 从充电挂起态连接 | ✅ | 同上（充电挂起的 USB 枚举就是 0e8d:2001） |

**读取 cache 全分区（112MB）约 15 秒；读取 expdb（10MB）约 2 秒。**

---

## 审计项 5：不破坏原厂 GPT 的诊断存储设计

### 结论：✅ 有两个现成位置，均不需要动 GPT

**分区表全貌**（MT6752_Android_scatter.txt，与真机 GPT 一致）：

```
preloader  0x0          0x40000    ⛔ 红线
proinfo    0x80000      0x300000   (3MB, 基带信息-敏感)
nvram      0x380000     0x500000   (5MB, 敏感)
protect1/2 0x880000     20MB       (保护分区)
seccfg     0x1c80000    0x40000    (已备份 ✓)
lk         0x1cc0000    0x60000    (已备份 ✓)
boot       0x1d20000    16MB       (目标分区)
recovery   0x2d20000    16MB       (已备份 ✓)
secro      0x3d20000    6MB
para       0x4320000    0.5MB
logo       0x43a0000    8MB
custom     0x4ba0000    55MB
expdb      0x82a0000    10MB       ← ★ MTK 原生异常调试分区
tee1/tee2  0x8ca0000    10MB
metadata   0x96a0000    34MB
system     0xb800000    1.3GB
cache      0x5d800000   112MB      ← 备选（ext4）
userdata   0x64800000   5.03GB     (Debian rootfs 目标)
flashinfo/sgpt                                    ⛔ 红线
```

### 候选裁定

| 候选 | 裁定 | 理由 |
|---|---|---|
| **expdb（10MB）** | **★ 首选** | MTK 原生异常调试分区——设计用途就是崩溃数据；我们写入不影响任何功能；raw 写入无文件系统顾虑；10MB 绰绰有余 |
| cache 尾部 | 备选 | 112MB ext4——写 offset ≥8MB 处避开头部元数据；缺点=写入需绕文件系统 |
| proinfo/nvram | ⛔ | 敏感（基带/校准数据） |
| 新增独立分区 | ⛔ | 需改 GPT——违反红线 |

**写入规范**：无论选哪个，写入前必须 `cat uevent` 确认 PARTNAME；
写入尺寸 ≤1MB；写入后立即回读校验。

---

## 审计总结：修正后的最终架构

```
第一级（平台内置, 零开发）:
  内核 panic/日志 → MTK ram_console @ 0x43F00000 (64KB DRAM) → 热复位保留

第二级（initramfs /init, PID 1 全流程, 零 devmem）:
  1. 挂载 + mdev
  2. 读 /proc/last_kmsg2 (上轮遗言) + /proc/last_kmsg + 本轮 dmesg/cmdline/boot_mode/CID
  3. 按 PARTNAME 找 expdb → 诊断写入 expdb 开头 64KB (raw, fsync)
  4. ACM gadget + ttyGS0 getty (USB 可枚举时的交互 shell)
  5. 心跳循环: 每 5 秒重收集+重写 expdb (12 轮)
  6. poweroff -f (手机断电)

回读（mtkclient, 停驻 preloader 态）:
  mtk.py r expdb expdb-dump.img   (~2 秒, 10MB)
  → 本地 grep: "Kernel panic" / "Booting Linux" / boot_mode → 死点定案
```

**相比 v8.5 的三个升级**：
1. 新增 last_kmsg2 收集（上轮遗言——panic 原文的正式通道）；
2. 写入目标从 cache 改为 **expdb**（原生调试分区，无 ext4 元数据顾虑）；
3. 心跳循环延长至 60 秒+（挂死后 cache 停在最后状态，回读即知死亡时刻）。

---

## 审计后仍需实测的三件事（诚实列出）

1. **热复位后 0x43F00000 的保留性**——设计上应保留，魅蓝1 实测一次定案
   （v10.1 黑匣子的 last_kmsg2.txt 内容即答案）；
2. **poweroff -f 在 MT6732 上的可靠性**——若失灵，手机保持开机状态
   （不影响 expdb 数据，回读照常，只是手机不会自己断电）；
3. **MTK ram_console 的缓冲区签名值**——用于原始 dump 的精确定位
   （非必需：日志文本本身即可识别）。

---

*审计结束。建议按 §"修正后的最终架构" 构建 v10.1 黑匣子并执行实测。*
