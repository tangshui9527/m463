#!/bin/bash
# ============================================================
# configure-rootfs.sh —— 在 box（x86 Ubuntu）上以 root 运行
# 把 Debian 12 armhf rootfs 配置成可无头启动的魅蓝1(M79)系统
#   用法: sudo ROOT=/workspace/rfs/root bash configure-rootfs.sh
# ============================================================
set -euo pipefail
ROOT=${ROOT:-/workspace/rfs/root}
[ -d "$ROOT/usr/bin" ] || { echo "rootfs 不存在: $ROOT"; exit 1; }

SSH_PUB="${SSH_PUB:-}"
ROOT_PASS_HASH='$6$DfhsDPHCDtwx9z3k$5OAjYBDUrEAsj91W7lBgZoImpdQW7rLTe9VKxGT08NjBro.tybDXgL1kreQcbEeS2PjT0/SwGR/9iL/aN7m6r1'  # 明文 m79root

echo "== 1. init = busybox"
rm -f "$ROOT/sbin/init"
ln -sf /bin/busybox "$ROOT/sbin/init"
chmod 755 "$ROOT/bin/busybox"

echo "== 2. /etc/inittab"
install -D -m 644 /dev/stdin "$ROOT/etc/inittab" <<'EOF'
# 魅蓝1 Linux inittab（busybox init）
::sysinit:/etc/init.d/rcS
ttyGS0::respawn:/bin/busybox getty -L 115200 ttyGS0 vt100
ttyMT0::respawn:/bin/busybox getty -L 921600 ttyMT0 vt100
tty1::respawn:/bin/busybox getty -L 38400 tty1 vt100
::ctrlaltdel:/bin/busybox reboot
::shutdown:/bin/busybox umount -a -r
::restart:/bin/busybox reboot
EOF

echo "== 3. /etc/init.d/rcS"
install -D -m 755 /dev/stdin "$ROOT/etc/init.d/rcS" <<'EOF'
#!/bin/sh
PATH=/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/bin
export PATH
BB=/bin/busybox

$BB mount -t proc proc /proc 2>/dev/null
$BB mount -t sysfs sysfs /sys 2>/dev/null
mkdir -p /dev/pts /dev/shm /run /tmp /var/run
$BB mount -t tmpfs tmpfs /run 2>/dev/null
$BB mount -t tmpfs tmpfs /dev/shm 2>/dev/null
$BB mount -t devpts devpts /dev/pts 2>/dev/null
[ -e /dev/console ] || $BB mknod -m 600 /dev/console c 5 1
[ -e /dev/null ]    || $BB mknod -m 666 /dev/null c 1 3
[ -e /dev/zero ]    || $BB mknod -m 666 /dev/zero c 1 5
[ -e /dev/tty ]     || $BB mknod -m 666 /dev/tty c 5 0
[ -e /dev/urandom ] || { $BB mknod -m 666 /dev/random c 1 8; $BB mknod -m 666 /dev/urandom c 1 9; }
# 内核没有 devtmpfs，全靠 mdev 从 sysfs 造节点
$BB mdev -s
[ -e /dev/mdev.log ] || true
echo /etc/mdev-hotplug > /proc/sys/kernel/hotplug 2>/dev/null || true

echo "wb-m1-debian" > /etc/hostname
$BB hostname wb-m1 2>/dev/null || true

# 动态库缓存（新装的 armhf 库需要）
/sbin/ldconfig 2>/dev/null || true

# USB CDC-ACM 串口控制台
/usr/local/bin/usb-console

# 首次开机把根分区撑满（镜像是缩小版，刷进去后自动长大）
if [ ! -f /etc/.rootfs-resized ]; then
  RD=$(awk '$2=="/"{print $1}' /proc/mounts)
  if [ -n "$RD" ] && [ -b "$RD" ]; then
    /sbin/resize2fs "$RD" >/dev/null 2>&1 && touch /etc/.rootfs-resized
  fi
fi

# 之前崩过就 fsck（尽力而为）
[ -f /forcefsck ] && { rm -f /forcefsck; }

# 网络（如有配置 WiFi 就自动连）
if [ -s /etc/wifi.conf ] && grep -q '^SSID=' /etc/wifi.conf; then
    /usr/local/sbin/wifi-up &
fi

# SSH
/etc/init.d/dropbear start

echo 0 > /proc/sys/kernel/printk_ratelimit 2>/dev/null || true
EOF

echo "== 4. mdev/hotplug + 基础文件"
install -D -m 755 /dev/stdin "$ROOT/etc/mdev-hotplug" <<'EOF'
#!/bin/sh
exec /bin/busybox mdev "$@"
EOF

install -D -m 644 /dev/stdin "$ROOT/etc/fstab" <<'EOF'
proc     /proc     proc     defaults        0 0
sysfs    /sys      sysfs    defaults        0 0
devpts   /dev/pts  devpts   defaults        0 0
tmpfs    /run      tmpfs    defaults        0 0
tmpfs    /dev/shm  tmpfs    defaults        0 0
tmpfs    /tmp      tmpfs    defaults        0 0
EOF

printf 'wb-m1-debian\n' > "$ROOT/etc/hostname"
install -D -m 644 /dev/stdin "$ROOT/etc/hosts" <<'EOF'
127.0.0.1   localhost wb-m1 localhost.localdomain
::1         localhost ip6-localhost
EOF
install -D -m 644 /dev/stdin "$ROOT/etc/resolv.conf" <<'EOF'
nameserver 192.168.31.1
nameserver 223.5.5.5
EOF
install -D -m 644 /dev/stdin "$ROOT/etc/issue" <<'EOF'

  Debian GNU/Linux 12 (bookworm) - 魅蓝1 / MT6752 / m79
  root 默认密码: m79root     串口: ttyGS0(USB) / ttyMT0(UART)

EOF

echo "== 5. root 账号"
if grep -q '^root:' "$ROOT/etc/shadow"; then
  awk -v h="$ROOT_PASS_HASH" 'BEGIN{FS=OFS=":"} $1=="root"{$2=h; $3=19000} {print}' \
      "$ROOT/etc/shadow" > "$ROOT/etc/shadow.new" && mv "$ROOT/etc/shadow.new" "$ROOT/etc/shadow"
  chmod 640 "$ROOT/etc/shadow"; chown 0:42 "$ROOT/etc/shadow"
fi
sed -i 's|^root:x:0:0:root:/root:/bin/sh$|root:x:0:0:root:/root:/bin/bash|' "$ROOT/etc/passwd"

if [ -n "$SSH_PUB" ]; then
  echo "== 5b. authorized_keys"
  install -d -m 700 "$ROOT/root/.ssh"
  printf '%s\n' "$SSH_PUB" > "$ROOT/root/.ssh/authorized_keys"
  chmod 600 "$ROOT/root/.ssh/authorized_keys"
fi

echo "== 6. dropbear"
install -d -m 700 "$ROOT/etc/dropbear"
install -D -m 755 /dev/stdin "$ROOT/etc/init.d/dropbear" <<'EOF'
#!/bin/sh
KEYDIR=/etc/dropbear
PID=/run/dropbear.pid
mkdir -p $KEYDIR /run
chmod 700 $KEYDIR
[ -f $KEYDIR/dropbear_rsa_host_key ] || /usr/bin/dropbearkey -t rsa -s 2048 -f $KEYDIR/dropbear_rsa_host_key >/dev/null 2>&1
[ -f $KEYDIR/dropbear_ed25519_host_key ] || /usr/bin/dropbearkey -t ed25519 -f $KEYDIR/dropbear_ed25519_host_key >/dev/null 2>&1
case "$1" in
  start)
    pgrep -f "dropbear -p 22" >/dev/null 2>&1 && exit 0
    /usr/sbin/dropbear -p 22 -P $PID
    ;;
  stop)
    [ -f $PID ] && kill "$(cat $PID)" 2>/dev/null
    ;;
  restart) "$0" stop; sleep 1; "$0" start ;;
esac
EOF

echo "== 7. USB 串口控制台"
install -D -m 755 /dev/stdin "$ROOT/usr/local/bin/usb-console" <<'EOF'
#!/bin/sh
# 用内核 legacy android gadget 开 CDC-ACM → 本机 /dev/ttyGS0，Mac 上是 /dev/tty.usbmodem*
A=/sys/class/android_usb/android0
[ -d "$A" ] || exit 0
n=0
while [ $n -lt 20 ]; do
  if echo 0 > "$A/enable" 2>/dev/null; then break; fi
  n=$((n+1)); sleep 0.5
done
echo 18d1 > "$A/idVendor" 2>/dev/null
echo d00d > "$A/idProduct" 2>/dev/null
echo "wb-m1" > "$A/iManufacturer" 2>/dev/null
echo "Meizu M1 Debian" > "$A/iProduct" 2>/dev/null
echo "acm" > "$A/functions" 2>/dev/null
echo 1 > "$A/enable" 2>/dev/null
# 造 ttyGSx 设备节点（内核无 devtmpfs）
i=0
while [ $i -lt 4 ]; do
  D=/sys/class/tty/ttyGS$i/dev
  if [ -f "$D" ]; then
    MM=$(cat "$D"); MAJ=${MM%%:*}; MIN=${MM##*:}
    [ -e /dev/ttyGS$i ] || /bin/busybox mknod -m 666 /dev/ttyGS$i c "$MAJ" "$MIN"
  fi
  i=$((i+1))
done
EOF

echo "== 8. WiFi"
install -d -m 755 "$ROOT/etc/wpa_supplicant"
install -D -m 600 /dev/stdin "$ROOT/etc/wpa_supplicant/wpa_supplicant.conf" <<'EOF'
ctrl_interface=/run/wpa_supplicant
update_config=1
EOF
install -D -m 600 /dev/stdin "$ROOT/etc/wifi.conf" <<'EOF'
# 填好 SSID/PSK 后开机自动连；也可以命令行 wifi-up 手动跑
SSID="yyds"
PSK="goodnight"
EOF

install -D -m 755 /dev/stdin "$ROOT/usr/local/lib/udhcpc.script" <<'EOF'
#!/bin/sh
case "$1" in
  deconfig)
    ip addr flush dev "$IFACE" 2>/dev/null
    ip link set "$IFACE" up ;;
  bound|renew)
    ip addr flush dev "$IFACE" 2>/dev/null
    ip addr add "$ip/${mask:-24}" dev "$IFACE"
    ip route add default via "$router" dev "$IFACE" 2>/dev/null
    : > /etc/resolv.conf
    [ -n "${dns:-}" ] || dns="$router"
    for s in $dns; do echo "nameserver $s" >> /etc/resolv.conf; done
    echo "wifi: $IFACE $ip gw $router" > /dev/console 2>/dev/null
    ;;
esac
exit 0
EOF

install -D -m 755 /dev/stdin "$ROOT/usr/local/sbin/wifi-up" <<'EOF'
#!/bin/sh
# 用法: wifi-up [ssid psk]   不带参数则读 /etc/wifi.conf
PATH=/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/bin
BB=/bin/busybox
[ -f /etc/wifi.conf ] && . /etc/wifi.conf
[ $# -ge 2 ] && { SSID="$1"; PSK="$2"; }

[ -n "$SSID" ] || { echo "没有 SSID"; exit 1; }

IFACE=""
n=0
while [ $n -lt 20 ]; do
  for cand in wlan0 wlan1; do
    [ -e "/sys/class/net/$cand" ] && { IFACE=$cand; break; }
  done
  [ -n "$IFACE" ] && break
  n=$((n+1)); sleep 1
done
[ -n "$IFACE" ] || { echo "没找到无线网卡（WiFi 驱动没起来）"; exit 1; }

if [ -n "$PSK" ]; then
  wpa_passphrase "$SSID" "$PSK" > /etc/wpa_supplicant/wpa_supplicant.conf
  echo "ctrl_interface=/run/wss" >> /etc/wpa_supplicant/wpa_supplicant.conf
  chmod 600 /etc/wpa_supplicant/wpa_supplicant.conf
fi
mkdir -p /run/wpa_supplicant
pkill -f wpa_supplicant 2>/dev/null
wpa_supplicant -B -i "$IFACE" -c /etc/wpa_supplicant/wpa_supplicant.conf -D nl80211 || \
  wpa_supplicant -B -i "$IFACE" -c /etc/wpa_supplicant/wpa_supplicant.conf -D wext
sleep 3
$BB udhcpc -i "$IFACE" -b -s /usr/local/lib/udhcpc.script -t 6
EOF
ln -sf /usr/local/sbin/wifi-up "$ROOT/usr/local/bin/wifi"

echo "== 9. 关掉 udev（内核无 devtmpfs）"
chmod -x "$ROOT/etc/init.d/udev" 2>/dev/null || true

echo "== 10. 动态库缓存（必须跑 armhf 自己的 ldconfig；宿主 ldconfig 扫不了 arm 库）"
if [ -x "$ROOT/usr/bin/qemu-arm-static" ]; then
  if chroot "$ROOT" /usr/bin/qemu-arm-static /sbin/ldconfig; then
    echo "ld.so.cache 已重建: $(strings "$ROOT/etc/ld.so.cache" | wc -l) 条"
  else
    echo "!! qemu ldconfig 失败，靠开机 rcS 里的 ldconfig 兜底"
  fi
else
  echo "!! 没有 qemu-arm-static，靠开机 rcS 里的 ldconfig 兜底"
fi

echo "== 11. 清理"
rm -f "$ROOT/etc/mtab"; ln -sf /proc/mounts "$ROOT/etc/mtab"
rm -rf "$ROOT/var/cache/apt/archives/"*.deb 2>/dev/null || true
rm -rf "$ROOT/var/lib/apt/lists/partial"/* 2>/dev/null || true
: > "$ROOT/etc/motd" 2>/dev/null || true

echo "== 完成"
du -sh "$ROOT" 2>/dev/null | tail -1
