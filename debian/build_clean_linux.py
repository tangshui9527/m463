import gzip
import os
import stat
import struct
import subprocess
import sys

def make_cpio_entry(name, mode, uid=0, gid=0, nlink=1, mtime=0, maj=0, min=0, data=b""):
    namesize = len(name.encode()) + 1
    filesize = len(data)
    hdr = "070701" + "".join(f"{v:08x}" for v in (
        0, # ino
        mode,
        uid,
        gid,
        nlink,
        mtime,
        filesize,
        0, 0, # devmajor, devminor
        maj,
        min,
        namesize,
        0 # check
    ))
    out = bytearray(hdr.encode())
    out.extend(name.encode() + b"\0")
    while len(out) % 4: out.append(0)
    out.extend(data)
    while len(out) % 4: out.append(0)
    return out

def build_initramfs(bb_path, init_script_content):
    out = bytearray()
    
    # 1. Directories
    dirs = ["dev", "proc", "sys", "mnt", "newroot", "bin", "sbin", "etc"]
    for d in dirs:
        out.extend(make_cpio_entry(d, stat.S_IFDIR | 0o755, nlink=2))
        
    # 2. Device nodes
    # dev/console (chr 5, 1)
    out.extend(make_cpio_entry("dev/console", stat.S_IFCHR | 0o600, maj=5, min=1))
    # dev/null (chr 1, 3)
    out.extend(make_cpio_entry("dev/null", stat.S_IFCHR | 0o666, maj=1, min=3))
    # dev/zero (chr 1, 5)
    out.extend(make_cpio_entry("dev/zero", stat.S_IFCHR | 0o666, maj=1, min=5))
    # dev/tty (chr 5, 0)
    out.extend(make_cpio_entry("dev/tty", stat.S_IFCHR | 0o666, maj=5, min=0))
    # dev/tty0 (chr 4, 0)
    out.extend(make_cpio_entry("dev/tty0", stat.S_IFCHR | 0o666, maj=4, min=0))
    # dev/tty1 (chr 4, 1)
    out.extend(make_cpio_entry("dev/tty1", stat.S_IFCHR | 0o666, maj=4, min=1))
    
    # 3. /bin/busybox
    with open(bb_path, "rb") as f:
        bb_data = f.read()
    out.extend(make_cpio_entry("bin/busybox", stat.S_IFREG | 0o755, data=bb_data))
    
    # 4. /bin/sh symlink -> /bin/busybox
    out.extend(make_cpio_entry("bin/sh", stat.S_IFLNK | 0o777, data=b"/bin/busybox"))
    
    # 5. /init executable
    out.extend(make_cpio_entry("init", stat.S_IFREG | 0o755, data=init_script_content.encode()))
    
    # Trailer
    name = "TRAILER!!!"
    hdr = "070701" + "".join(f"{v:08x}" for v in (0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(name)+1, 0))
    out.extend(hdr.encode())
    out.extend(name.encode() + b"\0")
    while len(out) % 4: out.append(0)
    
    return bytes(out)

CLEAN_INIT = """#!/bin/busybox sh
# ============================================================
# Meizu M463 / m79 Debian Linux Init
# Bulletproof: PID 1 NEVER exits!
# ============================================================
export PATH=/bin:/sbin

# Install busybox applets into /bin and /sbin
/bin/busybox --install -s /bin 2>/dev/null
/bin/busybox --install -s /sbin 2>/dev/null

# Mount essential virtual filesystems
mount -t proc proc /proc 2>/dev/null
mount -t sysfs sysfs /sys 2>/dev/null
mount -t devtmpfs devtmpfs /dev 2>/dev/null || mdev -s 2>/dev/null

say() {
    echo "[Debian-Linux] $*"
    echo "[Debian-Linux] $*" > /dev/console 2>/dev/null
    echo "[Debian-Linux] $*" > /dev/tty0 2>/dev/null
}

say "======================================================="
say "   Meizu M463 (m79) Linux Initramfs Started!          "
say "======================================================="

# Configure USB CDC-ACM Serial Console
setup_usb_acm() {
    A=/sys/class/android_usb/android0
    [ -d "$A" ] || return 1
    echo 0 > "$A/enable" 2>/dev/null
    echo 18d1 > "$A/idVendor" 2>/dev/null
    echo d00d > "$A/idProduct" 2>/dev/null
    echo "Meizu" > "$A/iManufacturer" 2>/dev/null
    echo "M463 Linux Console" > "$A/iProduct" 2>/dev/null
    echo "acm" > "$A/functions" 2>/dev/null
    echo 1 > "$A/enable" 2>/dev/null
    
    for i in $(seq 1 20); do
        if [ -e /dev/ttyGS0 ]; then
            return 0
        fi
        for g in 0 1 2 3; do
            D=/sys/class/tty/ttyGS$g/dev
            if [ -f "$D" ]; then
                MM=$(cat "$D")
                mknod -m 666 /dev/ttyGS$g c ${MM%%:*} ${MM##*:} 2>/dev/null
            fi
        done
        [ -e /dev/ttyGS0 ] && return 0
        sleep 0.2
    done
    return 1
}

if setup_usb_acm; then
    say "USB CDC-ACM serial console ready on /dev/ttyGS0 (18d1:d00d)!"
else
    say "USB CDC-ACM setup timed out, continuing..."
fi

# Try to find rootfs
find_rootfs() {
    for p in /dev/mmcblk0p* /dev/mmcblk1p*; do
        [ -b "$p" ] || continue
        if mount -t ext4 -o ro "$p" /newroot 2>/dev/null; then
            if [ -f /newroot/etc/wbm1-release ] || [ -f /newroot/bin/sh ] || [ -f /newroot/sbin/init ]; then
                say "Found root filesystem on $p!"
                return 0
            fi
            umount /newroot 2>/dev/null
        fi
    done
    return 1
}

say "Scanning eMMC partitions for Debian root filesystem..."
ROOT_FOUND=0
for try in 1 2 3 4 5; do
    if find_rootfs; then
        ROOT_FOUND=1
        break
    fi
    sleep 1
done

if [ "$ROOT_FOUND" -eq 1 ]; then
    say "Switching root to Debian (/newroot)..."
    mount -o remount,rw /newroot 2>/dev/null
    mkdir -p /newroot/dev /newroot/proc /newroot/sys /newroot/run /newroot/tmp
    mount --move /proc /newroot/proc 2>/dev/null
    mount --move /sys /newroot/sys 2>/dev/null
    mount --move /dev /newroot/dev 2>/dev/null
    exec switch_root /newroot /sbin/init
fi

say "No Debian rootfs found on eMMC; entering FOREGROUND Rescue Shell..."
say "Connect USB to computer: /dev/ttyACM0 (115200 baud) or look at screen."

# PID 1 MUST NEVER DIE! Run interactive shell forever!
while true; do
    if [ -e /dev/ttyGS0 ]; then
        say "Starting shell on /dev/ttyGS0..."
        setsid /bin/sh -i </dev/ttyGS0 >/dev/ttyGS0 2>&1
    elif [ -e /dev/console ]; then
        setsid /bin/sh -i </dev/console >/dev/console 2>&1
    else
        /bin/sh -i
    fi
    sleep 1
done
"""

bb_path = "/Users/tangshui/test/m463/debian/build/initramfs/bin/busybox"
cpio_raw = build_initramfs(bb_path, CLEAN_INIT)
cpio_gz_path = "/Users/tangshui/test/m463/debian/initramfs-clean.cpio.gz"
with gzip.GzipFile(cpio_gz_path, "wb", compresslevel=9, mtime=0) as f:
    f.write(cpio_raw)

print(f"Created {cpio_gz_path}: cpio {len(cpio_raw)} -> gz {os.path.getsize(cpio_gz_path)}")
