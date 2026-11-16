#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTK BROM 逐字节握手诊断器 v5  (2026-11-16)
=========================================
目的：只做一件事——判定 BROM 的 Bulk OUT / Bulk IN 到底通不通。
不读分区、不写分区、不加载 DA、不刷机。

为什么重写：
  v4 (fast_handshake_v4.py) 有三个致命缺陷，会导致「假失败」并自己把设备复位：
    1) except Exception: return False   ->  吞掉一切异常，分不清 EBUSY / 超时 / 端点错
    2) 从未 detach_kernel_driver / claim_interface  ->  内核驱动占着接口时 write 直接 EBUSY
    3) 整包发 4 字节 + read(64) 一次性读 + 严格比对 4 字节
       若 BROM 按标准只对 0xA0 回一个 0x5F，则只拿到 1 字节 -> 判失败 -> dispose -> 设备复位
       于是「BROM 只活 2~4 秒」很可能不是看门狗，而是我们自己在杀设备。

本脚本做法（MTK BROM 标准同步协议，逐字节等应答）：
    发 A0 -> 期望 5F
    发 0A -> 期望 F5
    发 50 -> 期望 AF
    发 05 -> 期望 FA
  每一步都打印：write() 返回值 / read() 实际内容 / 耗时毫秒 / 失败类型。

用法：
    sudo python3 brom_handshake_v5.py            # 需要 root 才能 detach kernel driver
    sudo python3 brom_handshake_v5.py --dump     # 只打印描述符树，不握手
    sudo python3 brom_handshake_v5.py --byte-by-byte   # 默认就是逐字节
    sudo python3 brom_handshake_v5.py --packet   # 对照实验：整包发 4 字节

退出码：0=握手成功  2=找到设备但握手失败  3=一直没找到设备
"""

import sys
import time
import argparse

try:
    import usb.core
    import usb.util
except ImportError:
    sys.exit("缺少 pyusb：pip install pyusb  （或改用 mtkclient 自带 venv 里的 python）")

VID = 0x0E8D
PIDS = (0x0003, 0x2000, 0x2001)   # 0003=BROM 下载模式；2000/2001=部分 preloader
SYNC = [(0xA0, 0x5F), (0x0A, 0xF5), (0x50, 0xAF), (0x05, 0xFA)]

READ_TIMEOUT = 100   # ms，单步上限。BROM 正常应答是 <10ms
WRITE_TIMEOUT = 100


def find_dev():
    for pid in PIDS:
        d = usb.core.find(idVendor=VID, idProduct=pid)
        if d is not None:
            return d, pid
    # 兜底：任意 0e8d 设备
    return usb.core.find(idVendor=VID), None


def dump_tree(dev):
    """打印完整描述符树 + 抢占情况。这段输出就是明天要看的核心证据。"""
    print("=" * 68)
    try:
        print("设备: %04x:%04x  bus=%s addr=%s  speed=%s" % (
            dev.idVendor, dev.idProduct, dev.bus, dev.address,
            getattr(dev, "speed", "?")))
    except Exception as e:
        print("读取设备基础信息失败:", e)

    try:
        cfg = dev.get_active_configuration()
    except Exception as e:
        print("!! 拿不到 active configuration:", type(e).__name__, e)
        return None, None, None, None

    if cfg is None:
        print("!! active configuration 为 None（设备可能还没配置好）")
        return None, None, None, None

    print("配置 bConfigurationValue=%s  bNumInterfaces=%s" % (
        cfg.bConfigurationValue, cfg.bNumInterfaces))

    ep_out = ep_in = None
    itf_num = None
    for itf in cfg:
        cls = itf.bInterfaceClass
        sub = itf.bInterfaceSubClass
        proto = itf.bInterfaceProtocol
        print("  interface %d  alt=%d  class=0x%02x sub=0x%02x proto=0x%02x  endpoints=%d"
              % (itf.bInterfaceNumber, itf.bAlternateSetting, cls, sub, proto, itf.bNumEndpoints))

        for ep in itf:
            direction = "OUT" if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT else "IN"
            etype = usb.util.endpoint_type(ep.bmAttributes)
            tname = {0: "control", 1: "isochronous", 2: "bulk", 3: "interrupt"}.get(etype, str(etype))
            print("      ep 0x%02x  %-3s  %-11s  maxpacket=%s" % (
                ep.bEndpointAddress, direction, tname, ep.wMaxPacketSize))
            if tname == "bulk":
                if direction == "OUT" and ep_out is None:
                    ep_out, itf_num = ep, itf.bInterfaceNumber
                elif direction == "IN" and ep_in is None:
                    ep_in = ep
                    if itf_num is None:
                        itf_num = itf.bInterfaceNumber

    # 抢占情况
    print("-" * 68)
    for itf in cfg:
        try:
            active = dev.is_kernel_driver_active(itf.bInterfaceNumber)
        except Exception as e:
            active = "? (%s)" % type(e).__name__
        print("  内核驱动占用 interface %d : %s" % (itf.bInterfaceNumber, active))

    print("选中 endpoint: OUT=%s  IN=%s  interface=%s" % (
        hex(ep_out.bEndpointAddress) if ep_out else "无",
        hex(ep_in.bEndpointAddress) if ep_in else "无",
        itf_num))
    print("=" * 68)
    return ep_out, ep_in, itf_num, cfg


def take_over(dev, cfg, itf_num):
    """先 detach 内核驱动，再 claim 接口。任何一步失败都把原因打出来。"""
    ok = True
    for itf in cfg:
        n = itf.bInterfaceNumber
        try:
            if dev.is_kernel_driver_active(n):
                dev.detach_kernel_driver(n)
                print("  detach_kernel_driver(%d) -> OK" % n)
            else:
                print("  detach_kernel_driver(%d) -> 本来就没驱动占用" % n)
        except Exception as e:
            print("  detach_kernel_driver(%d) -> 失败: %s: %s" % (n, type(e).__name__, e))
            ok = False
    try:
        usb.util.claim_interface(dev, itf_num)
        print("  claim_interface(%s) -> OK" % itf_num)
    except Exception as e:
        print("  claim_interface(%s) -> 失败: %s: %s" % (itf_num, type(e).__name__, e))
        ok = False
    return ok


def read_one(ep_in):
    """读 1 字节。返回 (bytes, 耗时ms, 错误字符串)。"""
    t0 = time.time()
    try:
        data = bytes(ep_in.read(1, timeout=READ_TIMEOUT))
        return data, (time.time() - t0) * 1000, None
    except usb.core.USBTimeoutError:
        return b"", (time.time() - t0) * 1000, "TIMEOUT(IN)"
    except Exception as e:
        return b"", (time.time() - t0) * 1000, "%s: %s" % (type(e).__name__, e)


def try_clear_halt(ep_in, ep_out):
    """上一轮内核驱动可能让端点 stall，清一下 halt 再试。"""
    for ep, name in ((ep_in, "IN"), (ep_out, "OUT")):
        if ep is None:
            continue
        try:
            ep.clear_halt()
            print("  clear_halt(%s) -> OK" % name)
        except Exception as e:
            print("  clear_halt(%s) -> %s" % (name, type(e).__name__))


def handshake_bytewise(dev, ep_out, ep_in, itf_num):
    """逐字节 A0->5F / 0A->F5 / 50->AF / 05->FA"""
    print("\n>>> 逐字节握手开始")
    for i, (tx, expect) in enumerate(SYNC, 1):
        try:
            n = ep_out.write(bytes([tx]), timeout=WRITE_TIMEOUT)
            print("  step%d  OUT 0x%02x  write 返回 %s 字节" % (i, tx, n))
        except Exception as e:
            print("  step%d  OUT 0x%02x  **写失败**: %s: %s" % (i, tx, type(e).__name__, e))
            return False, "OUT_FAIL_0x%02X" % tx

        data, ms, err = read_one(ep_in)
        if err:
            print("  step%d  IN  期望 0x%02x  实际: %s  耗时 %.0fms" % (i, expect, err, ms))
            return False, "IN_TIMEOUT_0x%02X" % tx
        got = data[0] if data else None
        print("  step%d  IN  期望 0x%02x  实际 0x%02x  %s  耗时 %.0fms" % (
            i, expect, got if got is not None else -1,
            "✓" if got == expect else "✗", ms))
        if got != expect:
            return False, "MISMATCH_0x%02X_got_%s" % (tx, "empty" if got is None else "0x%02X" % got)

    print("\n>>> ✅ 握手成功：BROM 通信层通了！")
    print(">>> 设备现在处于已同步状态（能接受后续命令），别断电。")
    return True, "OK"


def handshake_packet(ep_out, ep_in):
    """对照实验：整包发 4 字节。注意标准 BROM 只会回 1 字节，本函数用于验证这个假设。"""
    print("\n>>> 整包实验：一次写 A0 0A 50 05，然后尝试读 4 字节")
    try:
        n = ep_out.write(b"\xa0\x0a\x50\x05", timeout=WRITE_TIMEOUT)
        print("  write 返回 %s 字节" % n)
    except Exception as e:
        print("  **写失败**: %s: %s" % (type(e).__name__, e))
        return False
    t0 = time.time()
    try:
        data = bytes(ep_in.read(64, timeout=300))
        print("  读到 %d 字节: %s  耗时 %.0fms" % (len(data), data.hex(" "), (time.time() - t0) * 1000))
        if data[:1] == b"\x5f":
            print("  >>> 设备只回了 0x5F 一个字节 —— 证明它按逐字节协议工作，v4 因此判了假失败。")
    except Exception as e:
        print("  读失败: %s: %s  耗时 %.0fms" % (type(e).__name__, e, (time.time() - t0) * 1000))
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="只打印描述符树")
    ap.add_argument("--packet", action="store_true", help="整包握手（对照实验）")
    ap.add_argument("--wait", type=float, default=120, help="等设备出现的秒数")
    args = ap.parse_args()

    print("BROM 握手诊断 v5   等待设备出现（最多 %.0f 秒）…" % args.wait)
    t_start = time.time()
    dev = None
    while time.time() - t_start < args.wait:
        try:
            dev, pid = find_dev()
        except Exception as e:
            print("usb.core.find 出错:", e)
            dev = None
        if dev is not None:
            break
        time.sleep(0.05)

    if dev is None:
        print("\n✗ %.0f 秒内没有出现任何 0e8d 设备。" % args.wait)
        ida = time.time()
        print("  如果给 %s 秒能出现，说明是我们脚本杀太快；如果始终不出现，查线/查口/查电池。" % 30)
        return 3

    print("\n[%.2fs] 检测到设备 %04x:%04x" % (time.time() - t_start, dev.idVendor, dev.idProduct))

    ep_out, ep_in, itf_num, cfg = dump_tree(dev)
    if args.dump:
        return 0
    if ep_out is None or ep_in is None:
        print("\n✗ 没找到 bulk OUT/IN 端点，无法握手。把上面这棵树原样发回来。")
        return 2

    if not take_over(dev, cfg, itf_num):
        print("\n⚠ 抢占不完整（上面有失败项）。仍然尝试握手，但 EBUSY 很可能源自这里。")

    try:
        if args.packet:
            handshake_packet(ep_out, ep_in)
            return 2
        ok, reason = handshake_bytewise(dev, ep_out, ep_in, itf_num)
        if not ok and reason.startswith("IN_TIMEOUT"):
            print("\n>>> IN 超时：试一次 clear_halt 后重来（内核驱动可能让端点 stall 过）")
            try_clear_halt(ep_in, ep_out)
            time.sleep(0.02)
            ok, reason = handshake_bytewise(dev, ep_out, ep_in, itf_num)
        if ok:
            print("\n下一步（不要关这个进程之前先看 NEXT-PLAN.md）：")
            print("  · 握手已通 -> 说明 Linux 主机侧 OK，问题在 DA 阶段，走 mtkclient")
            return 0
        print("\n✗ 握手失败，分类: %s" % reason)
        print("  判读方法：")
        print("   OUT_FAIL     -> 接口被占/端点方向选错/设备已复位（EBUSY 或 NO_DEVICE）")
        print("   IN_TIMEOUT   -> OUT 通了但设备没应答：可能是设备已快超时、或主机控制器问题")
        print("   MISMATCH     -> 有应答但值不对：协议/时序问题，把实际值记下来")
        return 2
    finally:
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
