#!/bin/bash
# 魅蓝1（m79）刷 Linux：boot + userdata
# 用法: ./flash.sh [boot|rootfs|reset|check]
set -euo pipefail

MTK=${MTK:-/Users/tangshui/tools/mtkclient}
PY=${PY:-/Users/tangshui/tools/mtk-venv/bin/python}
HERE=$(cd "$(dirname "$0")" && pwd)
BOOT="$HERE/build/boot-linux.img"
ROOTFS="$HERE/build/linuxroot.img"
BOOT_STOCK="$HERE/boot-original.img"

chk() {
    for f in "$BOOT" "$ROOTFS"; do
        [ -f "$f" ] || { echo "缺少 $f"; exit 1; }
    done
    echo "boot-linux.img  $(stat -f%z "$BOOT") 字节"
    echo "linuxroot.img   $(stat -f%z "$ROOTFS") 字节"
    [ "$(stat -f%z "$BOOT")" -lt 16777216 ] || { echo "boot 超过 16M 分区"; exit 1; }
    [ "$(stat -f%z "$ROOTFS")" -lt 1237319680 ] || { echo "rootfs 超过 userdata 分区"; exit 1; }
}

case "${1:-}" in
check) chk ;;
reset)
    cd "$MTK" && "$PY" mtk.py reset
    ;;
boot)
    chk
    cd "$MTK"
    "$PY" mtk.py w boot "$BOOT"
    ;;
rootfs)
    chk
    cd "$MTK"
    echo "写 userdata（512M，约 1~3 分钟）…"
    "$PY" mtk.py w userdata "$ROOTFS"
    ;;
all)
    chk
    cd "$MTK"
    echo "== 先确认 BROM 认到了 =="
    "$PY" mtk.py printgpt | head -20
    "$PY" mtk.py w boot "$BOOT"
    "$PY" mtk.py w userdata "$ROOTFS"
    "$PY" mtk.py reset
    ;;
rollback)
    cd "$MTK"
    "$PY" mtk.py w boot "$BOOT_STOCK"
    "$PY" mtk.py reset
    ;;
*)
    echo "用法: $0 [check|boot|rootfs|all|reset|rollback]"
    echo "  一次 BROM 会话刷两个分区用 all；只想换内核用 boot；回 Android 用 rollback"
    ;;
esac
