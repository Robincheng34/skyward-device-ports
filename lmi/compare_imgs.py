#!/usr/bin/env python3
import struct, hashlib, gzip

def align(x, p):
    return (x + p - 1) & ~(p - 1)

def parse_header(path):
    with open(path, "rb") as f:
        h = f.read(4096)
    def u(o):
        return struct.unpack("<I", h[o:o+4])[0]
    return {
        "kernel_size": u(8), "kernel_addr": hex(u(12)),
        "ramdisk_size": u(16), "ramdisk_addr": hex(u(20)),
        "tags_addr": hex(u(32)), "page_size": u(36),
        "header_version": u(40), "os_version": hex(u(44)),
        "dtbo_size": u(1648), "dtbo_offset": hex(u(1652)),
        "cmdline": h[80:80+512].split(b"\x00", 1)[0].decode("ascii", "replace")[:160],
    }

def read_seg(path, off, size):
    if size <= 0:
        return b""
    with open(path, "rb") as f:
        f.seek(off)
        return f.read(size)

def decompress_ramdisk(data):
    if data[:2] == b"\x1f\x8b":
        try:
            return ("gzip", gzip.decompress(data))
        except Exception:
            return ("gzip-err", None)
    if data[:4] in (b"\x02\x21\x4c\x18", b"\x18\x4c\x21\x02"):
        return ("lz4-legacy", None)
    if data[:4] == b"\x04\x22\x4d\x18":
        return ("lz4-frame", None)
    return ("raw-" + data[:4].hex(), data)

def parse_cpio(data):
    files = {}
    i = 0
    n = len(data)
    guard = 0
    while i + 110 <= n:
        if data[i:i+6] not in (b"070701", b"070702"):
            break
        try:
            def hx(o):
                return int(data[i+o:i+8], 16)
            namesize = hx(94)
            filesize = hx(54)
            name = data[i+110:i+110+namesize-1].decode("utf-8", "replace")
            content_off = align(i+110+namesize, 4)
            if name == "TRAILER!!!":
                break
            files[name] = filesize
            i = align(content_off + filesize, 4)
        except Exception:
            break
        guard += 1
        if guard > 200000:
            break
    return files

def summarize(tag, path):
    hdr = parse_header(path)
    k = read_seg(path, 4096, hdr["kernel_size"])
    r_off = align(4096 + hdr["kernel_size"], hdr["page_size"])
    r = read_seg(path, r_off, hdr["ramdisk_size"])
    d = read_seg(path, int(hdr["dtbo_offset"], 16), hdr["dtbo_size"]) if hdr["dtbo_size"] else b""
    fmt, rd = decompress_ramdisk(r)
    if rd is None:
        rf = {}; rcount = 0; rhead = "(skip)"
    else:
        rf = parse_cpio(rd); rcount = len(rf); rhead = rd[:8].hex()
    print(f"\n[{tag}] ramdisk_magic={r[:8].hex()} fmt={fmt} rd_head={rhead} size_k={hdr['ramdisk_size']//1024}")
    return hdr, {
        "kernel_sha": hashlib.sha256(k).hexdigest()[:16],
        "ramdisk_sha": hashlib.sha256(r).hexdigest()[:16],
        "dtbo_sha": hashlib.sha256(d).hexdigest()[:16] if d else "none",
        "ramdisk_files": rf, "ramdisk_count": rcount,
    }

MINE = r"H:/idmDownload/skyward-lmi.img"
OTHER = r"C:/Users/Robin/Desktop/skyward-lmi-0.1.2.img"
h1, s1 = summarize("MINE", MINE)
h2, s2 = summarize("OTHER", OTHER)

print("\n=== HEADER ===")
for k in ["kernel_addr", "ramdisk_addr", "tags_addr", "page_size", "header_version", "os_version", "dtbo_size", "dtbo_offset", "cmdline"]:
    m = " " if h1[k] == h2[k] else " *DIFF*"
    print(f"  {k:14} MINE={h1[k]!r:20} OTHER={h2[k]!r:20}{m}")

print("\n=== SEGMENT HASH ===")
for k in ["kernel_sha", "ramdisk_sha", "dtbo_sha"]:
    m = " " if s1[k] == s2[k] else " *DIFF*"
    print(f"  {k:14} MINE={s1[k]!r:20} OTHER={s2[k]!r:20}{m}")
print(f"  ramdisk_count: MINE={s1['ramdisk_count']}  OTHER={s2['ramdisk_count']}")

print("\n=== RAMDISK FILE DIFF ===")
f1, f2 = s1["ramdisk_files"], s2["ramdisk_files"]
om = [x for x in f1 if x not in f2]
oo = [x for x in f2 if x not in f1]
cs = [x for x in set(f1) & set(f2) if f1[x] != f2[x]]
print(f"  only in MINE ({len(om)}):")
for x in om[:60]:
    print(f"    - {x} ({f1[x]})")
print(f"  only in OTHER ({len(oo)}):")
for x in oo[:60]:
    print(f"    + {x} ({f2[x]})")
print(f"  both but size differs ({len(cs)}):")
for x in cs[:60]:
    print(f"    ~ {x}  MINE={f1[x]} OTHER={f2[x]}")

print("\n=== KEY FILES ===")
for f in ["init", "system/bin/init", "system/bin/recovery", "skyward/system-init",
          "skyward/system-init.d", "skyward/device.toml", "system/etc/init/skyward-mtp.rc",
          "default.prop", "prop.default"]:
    m = f1.get(f, "ABSENT")
    o = f2.get(f, "ABSENT")
    mk = " " if m == o else " *DIFF*"
    print(f"  {f:34} MINE={str(m):10} OTHER={str(o):10}{mk}")
