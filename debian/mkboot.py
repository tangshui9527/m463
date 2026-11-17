#!/usr/bin/env python3
"""MTK boot.img 重新打包：换 kernel + ramdisk，保留原厂 header 其余字段。

用法:
  mkboot.py --base boot-original.img --kernel kernel_m79.bin \
            --ramdisk initramfs.cpio.gz --out boot-linux.img

结构（MTK，page=2048）:
  [0]      ANDROID! header (1 page)
  [page]   KERNEL  段: 512B MTK 头(magic 0x88168858) + zImage
  [align]  ROOTFS  段: 512B MTK 头 + gzip(cpio)
"""
import argparse
import hashlib
import struct
import sys

MTK_MAGIC = b"\x88\x16\x88\x58"  # 文件里的实际字节序: 88 16 88 58


def align(x, a=2048):
    return (x + a - 1) // a * a


def mtk_seg(payload: bytes, name: bytes) -> bytes:
    hdr = MTK_MAGIC + struct.pack("<I", len(payload)) + name.ljust(32, b"\0")[:32] + b"\xff" * (512 - 8 - 32)
    assert len(hdr) == 512
    return hdr + payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--ramdisk", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--partition-size", type=int, default=16 * 1024 * 1024)
    ap.add_argument("--ramdisk-name", default="ROOTFS",
                    help="MTK ramdisk 段头名字：boot 用 ROOTFS，recovery 必须用 RECOVERY")
    a = ap.parse_args()

    base = open(a.base, "rb").read()
    if base[:8] != b"ANDROID!":
        sys.exit("base 不是 ANDROID! 镜像")
    ks_old, rs_old = struct.unpack("<I", base[8:12])[0], struct.unpack("<I", base[16:20])[0]
    page = struct.unpack("<I", base[36:40])[0]
    print(f"base: kernel={ks_old} ramdisk={rs_old} page={page}")

    kseg = open(a.kernel, "rb").read()
    if kseg[:4] != MTK_MAGIC:
        # 传入的是裸 zImage，补 MTK 头
        kseg = mtk_seg(kseg, b"KERNEL")
    else:
        payload = struct.unpack("<I", kseg[4:8])[0]
        if payload != len(kseg) - 512:
            print(f"!! kernel MTK 头里写的长度 {payload} 与实际 {len(kseg)-512} 不一致，按实际重写")
            kseg = mtk_seg(kseg[512:], kseg[8:40].split(b"\0")[0])

    rpayload = open(a.ramdisk, "rb").read()
    if rpayload[:4] != MTK_MAGIC:
        rseg = mtk_seg(rpayload, a.ramdisk_name.encode())
    else:
        payload = struct.unpack("<I", rpayload[4:8])[0]
        if payload != len(rpayload) - 512:
            print(f"!! ramdisk MTK 头里写的长度 {payload} 与实际 {len(rpayload)-512} 不一致，按实际重写")
            rseg = mtk_seg(rpayload[512:], rpayload[8:40].split(b"\0")[0])
        else:
            rseg = rpayload

    hdr = bytearray(base[:page])
    struct.pack_into("<I", hdr, 8, len(kseg))
    struct.pack_into("<I", hdr, 16, len(rseg))
    struct.pack_into("<I", hdr, 24, 0)  # second 段清空

    # 计算标准 Android SHA-1 校验和并写入 hdr[576:608] (id 字段)
    # Android mkbootimg 计算方式:
    # sha1(kernel_data + pack(kernel_size) + ramdisk_data + pack(ramdisk_size) + pack(second_size=0))
    sha = hashlib.sha1()
    sha.update(kseg)
    sha.update(struct.pack("<I", len(kseg)))
    sha.update(rseg)
    sha.update(struct.pack("<I", len(rseg)))
    sha.update(b"")
    sha.update(struct.pack("<I", 0))
    digest = sha.digest()
    hdr[576:576+len(digest)] = digest
    hdr[576+len(digest):608] = b"\x00" * (32 - len(digest))
    print(f"计算 boot header SHA-1 id: {digest.hex()}")

    img = bytearray(hdr)
    img.extend(kseg)
    while len(img) % page:
        img.append(0)
    img.extend(rseg)
    while len(img) % page:
        img.append(0)

    if len(img) > a.partition_size:
        sys.exit(f"镜像 {len(img)} 超过分区 {a.partition_size}")

    open(a.out, "wb").write(img)
    print(f"写出 {a.out}: {len(img)} 字节（分区可用 {a.partition_size}，余 {a.partition_size-len(img)}）")
    print(f"  kernel 段 {len(kseg)}  ramdisk 段 {len(rseg)}")


if __name__ == "__main__":
    main()
