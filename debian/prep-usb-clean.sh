#!/bin/bash
# prep-usb-clean.sh —— MTK BROM 测试前的主机侧清理（Linux / go）
# 只动 USB 主机侧，不碰内核、不碰刷机、不写任何分区。
# 用法：sudo ./prep-usb-clean.sh
#
# 注意：本脚本只解除「驱动抢占」，它不是握手失败的原因本身。
# 跑完后请立刻执行：sudo python3 brom_handshake_v5.py

set -u
echo "=== 1. 停掉会抢 USB 的服务 ==="
for svc in ModemManager; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        systemctl stop "$svc" && echo "  $svc: 已停"
    else
        echo "  $svc: 本来就没跑"
    fi
    systemctl mask --runtime "$svc" 2>/dev/null && echo "  $svc: 本次开机内屏蔽（重启自动恢复）"
done

echo
echo "=== 2. 卸掉会抢占 0e8d:0003 的模块 ==="
for mod in cdc_acm option usb_wwan qcserial; do
    if lsmod | grep -q "^${mod} "; then
        if modprobe -r "$mod" 2>/dev/null; then
            echo "  $mod: 已卸载"
        else
            echo "  $mod: 卸载失败（正被占用，先拔掉手机再试）"
        fi
    else
        echo "  $mod: 未加载"
    fi
done

echo
echo "=== 3. 复查 ==="
left=$(lsmod | grep -E '^(cdc_acm|option|usb_wwan|qcserial|usbserial) ' || true)
if [ -z "$left" ]; then
    echo "  ✓ 无抢占驱动残留"
else
    echo "  ⚠ 仍有残留："
    echo "$left" | sed 's/^/    /'
fi
echo
echo "=== 4. 当前 USB 上的 MTK 设备 ==="
lsusb 2>/dev/null | grep -iE '0e8d|MediaTek' || echo "  暂无（正常，手机还没进 BROM）"
echo
echo "=== 5. 录音/串口节点占用 ==="
echo "  /dev/ttyACM*: $(ls /dev/ttyACM* 2>/dev/null || echo 无)"

echo
echo "清理完成。下一步（必须带 root）："
echo "  sudo python3 brom_handshake_v5.py --wait 120"
echo
echo "手机操作：完全关机 -> 按住音量下（部分机器要按住两个音量键）-> 插 USB"
