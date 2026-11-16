#!/usr/bin/env python3
# 极速握手 v4：正确实现 MTK BROM 握手协议
# 1) 整包一次发 4 字节 startcmd，收 4 字节按位取反回显
# 2) 不做 set_configuration（避免重枚举），只读已有配置找端点
# 3) 枚举后立刻抢占，不 sleep
import usb.core, usb.util, time, sys

STARTCMD = b"\xa0\x0a\x50\x05"
EXPECTED = bytes(~b & 0xFF for b in STARTCMD)   # 5f f5 af fa

def one_shot(dev):
    try:
        cfg = dev.get_active_configuration()
    except Exception:
        return False
    if cfg is None:
        return False
    ep_out = ep_in = None
    for itf in cfg:
        if ep_out is None:
            ep_out = usb.util.find_descriptor(
                itf, custom_match=lambda x: usb.util.endpoint_direction(x.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        if ep_in is None:
            ep_in = usb.util.find_descriptor(
                itf, custom_match=lambda x: usb.util.endpoint_direction(x.bEndpointAddress) == usb.util.ENDPOINT_IN)
    if ep_out is None or ep_in is None:
        return False
    try:
        ep_out.write(STARTCMD, timeout=300)
        recv = bytes(ep_in.read(64, timeout=300))
    except Exception:
        return False
    return recv[:4] == EXPECTED

print("极速握手 v4 启动 (整包协议)", flush=True)
while True:
    try:
        dev = usb.core.find(idVendor=0x0e8d)
    except Exception:
        dev = None
    if dev is None:
        time.sleep(0.01)
        continue
    print("[" + time.strftime("%H:%M:%S") + "] 检测到 0e8d 设备，立即握手", flush=True)
    ok = False
    for i in range(200):
        if one_shot(dev):
            ok = True
            break
    if ok:
        print(">>> 握手成功！设备已锁定 BROM (" + time.strftime("%H:%M:%S") + ")", flush=True)
        sys.exit(0)
    print("[" + time.strftime("%H:%M:%S") + "] 本轮失败，设备即将重启，等待下次枚举", flush=True)
    try:
        usb.util.dispose_resources(dev)
    except Exception:
        pass
    time.sleep(0.05)
