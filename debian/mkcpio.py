#!/usr/bin/env python3
"""把目录打成 cpio(newc) + gzip，供内核 initramfs 使用。
用法: mkcpio.py <目录> <输出.cpio.gz>
"""
import gzip
import os
import stat
import sys


def cpio_newc(root):
    out = bytearray()
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(dirnames) + sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            if rel == ".":
                continue
            entries.append((rel, full))
    # 保证父目录在前
    entries.sort(key=lambda x: (x[0].count("/"), x[0]))

    def add(name, full):
        st = os.lstat(full)
        data = b""
        if stat.S_ISLNK(st.st_mode):
            data = os.readlink(full).encode()
        elif stat.S_ISREG(st.st_mode):
            data = open(full, "rb").read()
        nlink = 1
        if stat.S_ISDIR(st.st_mode):
            nlink = 2
        namesize = len(name.encode()) + 1
        hdr = "070701" + "".join(
            f"{v:08x}"
            for v in (
                0,  # ino
                st.st_mode,
                st.st_uid,
                st.st_gid,
                nlink,
                int(st.st_mtime),
                len(data),
                0,  # devmajor
                0,  # devminor
                os.major(st.st_rdev) if stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode) else 0,
                os.minor(st.st_rdev) if stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode) else 0,
                namesize,
                0,  # check
            )
        )
        out.extend(hdr.encode())
        out.extend(name.encode() + b"\0")
        while len(out) % 4:
            out.append(0)
        out.extend(data)
        while len(out) % 4:
            out.append(0)

    for rel, full in entries:
        add(rel, full)
    # TRAILER
    name = "TRAILER!!!"
    hdr = "070701" + "".join(f"{v:08x}" for v in (0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(name) + 1, 0))
    out.extend(hdr.encode())
    out.extend(name.encode() + b"\0")
    while len(out) % 4:
        out.append(0)
    return bytes(out)


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    raw = cpio_newc(src)
    with gzip.GzipFile(dst, "wb", compresslevel=9, mtime=0) as f:
        f.write(raw)
    print(f"{dst}: cpio {len(raw)} -> gz {os.path.getsize(dst)}")
