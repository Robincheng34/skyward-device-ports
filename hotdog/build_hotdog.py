"""Put Skyward into the OnePlus 7T Pro's recovery image.

The base is LineageOS's own recovery for hotdog, which the phone's
bootloader will start without anything being written to it. Into its
ramdisk go the recovery program of ours, the starter of the phone's own
services, the fonts the pages are drawn with, and the configuration this
phone asks for. The kernel, the device trees and everything else the base
carries are kept as they are.

The ramdisk is kept as a gzip stream, which the kernel unpacks as readily
as the LZ4 one it shipped with.
"""

import gzip
import hashlib
import sys

import os
BASE = os.environ.get("BASE_IMG", r"H:/workbuddy/2026-11-13-18-00-49/skyward-hotdog/recovery.img")
RAMDISK_CPIO = r"H:/workbuddy/2026-11-13-18-00-49/skyward-hotdog/hotdog.cpio"
LMI_CPIO = r"H:/workbuddy/2026-11-13-18-00-49/skyward-lmi-port/ramdisk_out/MINE.cpio"
OTHER_CPIO = r"H:/workbuddy/2026-11-13-18-00-49/skyward-lmi-port/ramdisk_out/OTHER.cpio"
MY_RECOVERY = r"H:/workbuddy/2026-11-13-18-00-49/skyward-lmi-port/ramdisk_out/MINE/recovery_patched"
TOML = r"H:/workbuddy/2026-11-13-18-00-49/skyward-hotdog/device.toml"
OUT = r"H:/workbuddy/2026-11-13-18-00-49/skyward-hotdog/skyward-hotdog.img"

HEX = "0123456789abcdef"


def field(data, at, n=4):
    return int.from_bytes(data[at : at + n], "little")


def cpio_read(path):
    """The ramdisk's entries, in the order they were written."""
    data = open(path, "rb").read()
    ents, pos, n = [], 0, len(data)
    while pos + 110 <= n:
        if data[pos : pos + 6] not in (b"070701", b"070702"):
            break
        hx = lambda o, l: int(data[pos + o : pos + o + l], 16)
        ns, fs, mode = hx(94, 8), hx(54, 8), hx(14, 8)
        name = data[pos + 110 : pos + 110 + ns - 1].decode("utf-8", "replace")
        header = ((110 + ns + 3) // 4) * 4
        ents.append({"name": name, "mode": mode, "data": data[pos + header : pos + header + fs]})
        if name == "TRAILER!!!":
            break
        pos += ((header + fs + 3) // 4) * 4
    return ents


def cpio_take(path, name):
    for e in cpio_read(path):
        if e["name"] == name:
            return e["data"]
    raise SystemExit(f"{path} holds no {name}")


def hexed(value, width):
    return format(value, f"0{width}x").encode("ascii")


def cpio_write(ents):
    """The entries as a newc archive, each name and body on a four-byte
    boundary as the format asks."""
    out = bytearray()
    for e in ents:
        name = e["name"].encode("utf-8") + b"\0"
        body = e["data"]
        # The thirteen fields after the magic: which entry, its mode, its
        # owner, how many links, when, how long its body is, what device it
        # stands for, how long its name is, and the checksum none check.
        header = bytearray(b"070701")
        for value, width in ((1, 8), (e["mode"], 8), (0, 8), (0, 8), (1, 8), (0, 8), (len(body), 8), (0, 8), (0, 8), (0, 8), (0, 8), (len(name), 8), (0, 8)):
            header.extend(hexed(value, width))
        out.extend(header)
        out.extend(name)
        while len(out) % 4:
            out.extend(b"\0")
        out.extend(body)
        while len(out) % 4:
            out.extend(b"\0")
    out.extend(b"070701")
    trailer = b"TRAILER!!!\0"
    out.extend(hexed(0, 8) * 11 + hexed(len(trailer), 8) + hexed(0, 8))
    out.extend(trailer)
    while len(out) % 4:
        out.extend(b"\0")
    return bytes(out)


def main():
    # What is being built, for telling the attempts apart: with or without
    # our program in it, and the ramdisk as gzip or as the old LZ4 frame.
    inject = "--no-inject" not in sys.argv
    use_lz4 = "--lz4" in sys.argv
    permissive = "--no-permissive" not in sys.argv
    prop_patch = "--no-prop" not in sys.argv
    keep_recovery = "--keep-recovery" in sys.argv
    no_fonts = "--no-fonts" in sys.argv
    tag = "".join([("-l" if use_lz4 else ""), ("-noinj" if not inject else ""), ("-noperm" if not permissive else ""), ("-noprop" if not prop_patch else "")])
    out_path = OUT.replace(".img", f"{tag}.img")


    image = open(BASE, "rb").read()
    ks, rs, ps = field(image, 8), field(image, 16), field(image, 36)
    kernel_at = ps
    ramdisk_at = kernel_at + ((ks + ps - 1) // ps) * ps
    rdtbo_size, rdtbo_offset = field(image, 1632), field(image, 1636)
    dtb_size = field(image, 1648)

    kernel = image[kernel_at : kernel_at + ks]
    rdtbo = image[rdtbo_offset : rdtbo_offset + rdtbo_size]
    dtb_at = ramdisk_at + ((rs + ps - 1) // ps) * ps
    dtb_at += ((rdtbo_size + ps - 1) // ps) * ps if rdtbo_size else 0
    dtb = image[dtb_at : dtb_at + dtb_size]
    print(f"base: kernel {ks}, ramdisk {rs}, recovery_dtbo {rdtbo_size} @{rdtbo_offset}, dtb {dtb_size} @{dtb_at}")

    # The ramdisk as it ships, and what goes into it.
    ents = cpio_read(RAMDISK_CPIO)
    my_recovery = open(MY_RECOVERY, "rb").read()
    system_init = cpio_take(LMI_CPIO, "skyward/system-init")
    fonts_dir = r"H:/workbuddy/2026-11-13-18-00-49/skyward-hotdog/fonts"
    fonts = {"MiSansVF.ttf": open(fonts_dir + "/MiSans-sub.ttf", "rb").read(),
             "KirkMono-Regular.ttf": open(fonts_dir + "/KirkMono-Regular.ttf", "rb").read(),
             "KirkMono-OFL.txt": open(fonts_dir + "/KirkMono-OFL.txt", "rb").read()}
    toml = open(TOML, "rb").read()

    out, replaced = [], False
    for e in ents:
        if e["name"] == "TRAILER!!!":
            continue
        if e["name"] == "system/bin/recovery" and inject and not keep_recovery:
            out.append({**e, "data": my_recovery})
            replaced = True
        elif e["name"] == "system/bin/recovery":
            replaced = True
        elif e["name"] == "prop.default" and inject and prop_patch:
            # The recovery keeps its adb to itself, asking the screen for a
            # key the recovery has no way of answering with. A recovery that
            # is meant to be talked to opens it, the way the phone's own
            # repair recoveries do.
            text = e["data"].decode("utf-8", "replace")
            text = (
                text.replace("ro.secure=1\n", "ro.secure=0\n")
                .replace("ro.debuggable=0\n", "ro.debuggable=1\n")
                .replace("ro.adb.secure=1\n", "ro.adb.secure=0\n")
            )
            # The version of the installed system is what our program says
            # once the phone's partitions are up; the base claiming its own
            # keeps init from taking the one that matters.
            text = "\n".join(
                line
                for line in text.splitlines()
                if not line.startswith(("ro.build.version.release", "ro.build.version.security_patch", "ro.vendor.build.security_patch"))
            ) + "\n"
            if "ro.adb.secure" not in text:
                text = text.rstrip("\n") + "\nro.adb.secure=0\n"
            out.append({**e, "data": text.encode("utf-8")})
        else:
            out.append(e)
    if inject:
        assert replaced, "the base ramdisk holds no recovery program"
        # The folder our files live in has to be made before them: the
        # kernel's unpacker opens each file where its name says, and opens
        # nothing into a folder that is not there.
        out.append({"name": "skyward/", "mode": 0o040755, "data": b""})
        # Two bionic shims the phone's own key services need, which their
        # system keeps in an apex the recovery does not mount; taken from
        # the installed system's apexes for this phone.
        for shim in ("libdl_android.so", "libandroidicu.so", "libicuuc.so", "libicui18n.so"):
            out.append({"name": f"system/lib64/{shim}", "mode": 0o100644, "data": open(shim, "rb").read()})
        out.append({"name": "skyward/device.toml", "mode": 0o100644, "data": toml})
        out.append({"name": "skyward/system-init", "mode": 0o100755, "data": system_init})
        if not no_fonts:
            for name, data in fonts.items():
                out.append({"name": f"skyward/{name}", "mode": 0o100644, "data": data})

    new_cpio = cpio_write(out)
    if use_lz4:
        import lzc
        new_ramdisk = lzc.compress(new_cpio)
        assert lzc.decompress_legacy(new_ramdisk) == new_cpio, "the lz4 round trip disagrees"
    else:
        new_ramdisk = gzip.compress(new_cpio, compresslevel=9, mtime=0)
    print(f"inject={inject} lz4={use_lz4}: ramdisk {len(new_cpio)} bytes as files, {len(new_ramdisk)} compressed (base was {rs})")

    # The image is laid out again with the new ramdisk, everything after it
    # moved by however much it grew. The phone's own way of saying a
    # recovery may run without its policy is said in the call line, which
    # the base does not say; what our program does on the phone's behalf is
    # more than that policy lets a recovery do.
    header = bytearray(image[:4096])
    call = image[64 : 64 + 512].split(b"\x00")[0]
    if permissive and b"androidboot.selinux" not in call:
        call = call + b" androidboot.selinux=permissive"
        assert len(call) < 512, "the call line has no room for the word"
        header[64 : 64 + 512] = call + b"\x00" * (512 - len(call))
        print("call line:", call.decode())
    header[16:20] = len(new_ramdisk).to_bytes(4, "little")
    after = ramdisk_at + ((len(new_ramdisk) + ps - 1) // ps) * ps
    new_rdtbo_offset = after
    after += ((rdtbo_size + ps - 1) // ps) * ps
    header[1632:1636] = rdtbo_size.to_bytes(4, "little")
    header[1636:1640] = new_rdtbo_offset.to_bytes(4, "little")

    body = bytearray(header)
    body.extend(kernel)
    body.extend(b"\x00" * (ramdisk_at - len(body)))
    body.extend(new_ramdisk)
    body.extend(b"\x00" * (new_rdtbo_offset - len(body)))
    body.extend(rdtbo)
    body.extend(b"\x00" * (after - len(body)))
    body.extend(dtb)
    while len(body) % ps:
        body.extend(b"\x00")
    open(out_path, "wb").write(bytes(body))
    print(f"wrote {out_path} {len(body)} bytes (base was {len(image)})")

    # Read it back the way the bootloader would and check every claim.
    check = open(out_path, "rb").read()
    kernel_same = hashlib.sha256(check[ps : ps + ks]).hexdigest() == hashlib.sha256(kernel).hexdigest()
    dtb_new_at = new_rdtbo_offset + ((rdtbo_size + ps - 1) // ps) * ps
    rdtbo_same = hashlib.sha256(check[new_rdtbo_offset : new_rdtbo_offset + rdtbo_size]).hexdigest() == hashlib.sha256(rdtbo).hexdigest()
    dtb_same = hashlib.sha256(check[dtb_new_at : dtb_new_at + dtb_size]).hexdigest() == hashlib.sha256(dtb).hexdigest()
    gzip_ok = check[ramdisk_at : ramdisk_at + 3] == b"\x1f\x8b\x08"
    print(f"kernel unchanged: {kernel_same}")
    print(f"recovery_dtbo unchanged: {rdtbo_same}")
    print(f"dtb unchanged: {dtb_same}")
    print(f"ramdisk is gzip: {gzip_ok}")
    ok = kernel_same and rdtbo_same and dtb_same and gzip_ok and field(check, 16) == len(new_ramdisk) and field(check, 1636) == new_rdtbo_offset
    print(f"claims agree: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
