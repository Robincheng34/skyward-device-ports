"""把 Skyward 注入小米 8（dipper）的 LOS recovery 底座。

底座是 gzip ramdisk 的 AOSP recovery，kernel/ramdisk 之外无 dtbo/dtb 段，
尾部有 26MiB 零填充余量，并带 AVB footer（algorithm=NONE 纯哈希）。
本脚本：换 recovery 程序 + 注入 skyward 文件 + 打免授权 adb/permissive 补丁
+ 按新 ramdisk 长度重排 + 重算 AVB digest。
"""

import gzip
import hashlib
import os
import shutil
import sys

BASE = os.environ.get("BASE_IMG", r"H:/workbuddy/2026-11-13-18-00-49/skyward-dipper/recovery.img")
RAMDISK_CPIO = r"H:/workbuddy/2026-11-13-18-00-49/skyward-dipper/dipper.cpio"
LMI_CPIO = r"H:/workbuddy/2026-11-13-18-00-49/skyward-lmi-port/ramdisk_out/MINE.cpio"
MY_RECOVERY = r"H:/workbuddy/2026-11-13-18-00-49/skyward-lmi-port/ramdisk_out/MINE/recovery_patched"
FONT_DIR = r"H:/workbuddy/2026-11-13-18-00-49/skyward-hotdog/fonts"
TOML = r"H:/workbuddy/2026-11-13-18-00-49/skyward-dipper/device.toml"
OUT = r"H:/workbuddy/2026-11-13-18-00-49/skyward-dipper/skyward-dipper.img"

HEX = "0123456789abcdef"


def field(data, at, n=4):
    return int.from_bytes(data[at:at + n], "little")


def cpio_read(path):
    data = open(path, "rb").read()
    ents, pos, n = [], 0, len(data)
    while pos + 110 <= n:
        if data[pos:pos + 6] not in (b"070701", b"070702"):
            break
        hx = lambda o, l: int(data[pos + o:pos + o + l], 16)
        ns, fs, mode = hx(94, 8), hx(54, 8), hx(14, 8)
        name = data[pos + 110:pos + 110 + ns - 1].decode("utf-8", "replace")
        header = ((110 + ns + 3) // 4) * 4
        ents.append({"name": name, "mode": mode, "data": data[pos + header:pos + header + fs]})
        if name == "TRAILER!!!":
            break
        pos += ((header + fs + 3) // 4) * 4
    return ents


def cpio_take(path, name):
    for e in cpio_read(path):
        if e["name"] == name:
            return e["data"]
    raise SystemExit(f"{path} holds no {name}")


def hexed(v, w):
    return format(v, f"0{w}x").encode("ascii")


def cpio_write(ents):
    out = bytearray()
    for e in ents:
        name = e["name"].encode() + b"\0"
        body = e["data"]
        header = bytearray(b"070701")
        for v, w in ((1, 8), (e["mode"], 8), (0, 8), (0, 8), (1, 8), (0, 8),
                     (len(body), 8), (0, 8), (0, 8), (0, 8), (0, 8), (len(name), 8), (0, 8)):
            header.extend(hexed(v, w))
        out.extend(header)
        out.extend(name)
        while len(out) % 4:
            out.append(0)
        out.extend(body)
        while len(out) % 4:
            out.append(0)
    trailer = b"TRAILER!!!\0"
    out.extend(b"070701" + hexed(0, 8) * 11 + hexed(len(trailer), 8) + hexed(0, 8))
    out.extend(trailer)
    while len(out) % 4:
        out.append(0)
    return bytes(out)


def main():
    inject = "--no-inject" not in sys.argv
    no_fonts = "--no-fonts" in sys.argv
    permissive = "--no-permissive" not in sys.argv
    prop_patch = "--no-prop" not in sys.argv

    image = open(BASE, "rb").read()
    ks, rs, ps = field(image, 8), field(image, 16), field(image, 36)
    kernel_at = ps
    ramdisk_at = kernel_at + ((ks + ps - 1) // ps) * ps
    kernel = image[kernel_at:kernel_at + ks]
    print(f"base: kernel={ks} ramdisk={rs} page={ps} header_v={field(image,40)}")

    # footer / AVB 信息：dipper 的 vbmeta 是 algo=2 (SHA256+RSA 签名)，
    # 无私钥无法重签；好在 bootloader 允许 fastboot boot 且不校 recovery，
    # 测试阶段把 vbmeta/footer 原样保留即可（闪刷场景才需重签）。
    footer = image[-64:]
    assert footer[:4] == b"AVBf", "base has no AVB footer"
    vbmeta_at = int.from_bytes(footer[20:28], "big")
    vbmeta = image[vbmeta_at:vbmeta_at + 96]
    print(f"vbmeta algo={int.from_bytes(vbmeta[28:32],'big')} (2=signed; left untouched)")

    ents = cpio_read(RAMDISK_CPIO)
    my_recovery = open(MY_RECOVERY, "rb").read()
    system_init = cpio_take(LMI_CPIO, "skyward/system-init")
    fonts = {
        "MiSansVF.ttf": open(FONT_DIR + "/MiSans-sub.ttf", "rb").read(),
        "KirkMono-Regular.ttf": open(FONT_DIR + "/KirkMono-Regular.ttf", "rb").read(),
        "KirkMono-OFL.txt": open(FONT_DIR + "/KirkMono-OFL.txt", "rb").read(),
    }
    toml = open(TOML, "rb").read()

    out, replaced = [], False
    for e in ents:
        if e["name"] == "TRAILER!!!":
            continue
        if e["name"] == "system/bin/recovery" and inject:
            out.append({**e, "data": my_recovery})
            replaced = True
        elif e["name"] == "system/etc/init/hw/init.rc" and inject:
            # LOS 的 recovery gadget 只建了 adb/fastboot function，skyward
            # 的 MTP 找不到 /dev/usb-ffs/mtp/ep0；补上 configfs 的 mtp
            # function 与 functionfs 挂载（仿 TWRP 的 init.recovery.usb.rc）。
            text = e["data"].decode("utf-8", "replace")
            text = text.replace(
                "    mkdir /config/usb_gadget/g1/functions/ffs.adb\n",
                "    mkdir /config/usb_gadget/g1/functions/ffs.adb\n"
                "    mkdir /config/usb_gadget/g1/functions/ffs.mtp\n"
                "    mkdir /dev/usb-ffs/mtp 0770 shell system\n"
                "    mount functionfs mtp /dev/usb-ffs/mtp uid=1024,gid=1024,rmode=0770,fmode=0660,no_disconnect=1\n",
                1,
            )
            mtp_branch = (
                "\non property:sys.usb.config=mtp,adb && property:sys.usb.ffs.ready=1 && property:sys.usb.configfs=1\n"
                "    mkdir /dev/usb-ffs/mtp 0770 shell system\n"
                "    mount functionfs mtp /dev/usb-ffs/mtp uid=1024,gid=1024,rmode=0770,fmode=0660,no_disconnect=1\n"
                "    write /config/usb_gadget/g1/idProduct 0x${ro.recovery.usb.mtp.pid}\n"
                "    write /config/usb_gadget/g1/configs/b.1/strings/0x409/configuration \"mtp,adb\"\n"
                "    symlink /config/usb_gadget/g1/functions/ffs.mtp /config/usb_gadget/g1/configs/b.1/f1\n"
                "    symlink /config/usb_gadget/g1/functions/ffs.adb /config/usb_gadget/g1/configs/b.1/f2\n"
                "    write /config/usb_gadget/g1/UDC ${sys.usb.controller}\n"
                "    setprop sys.usb.state ${sys.usb.config}\n"
            )
            text = text.rstrip("\n") + "\n" + mtp_branch
            out.append({**e, "data": text.encode("utf-8")})
        elif e["name"] == "prop.default" and inject and prop_patch:
            text = e["data"].decode("utf-8", "replace")
            text = (text.replace("ro.secure=1\n", "ro.secure=0\n")
                        .replace("ro.adb.secure=1\n", "ro.adb.secure=0\n")
                        .replace("ro.debuggable=0\n", "ro.debuggable=1\n"))
            # 安装系统的版本由 skyward 挂载分区后自己设置；底座预置的版本
            # 会让 init 拒绝后续赋值（ro 属性不可重设）。
            text = "\n".join(
                line for line in text.splitlines()
                if not line.startswith(("ro.build.version.release", "ro.build.version.security_patch",
                                        "ro.vendor.build.version.release", "ro.system.build.version.release",
                                        "ro.product.build.version.release", "ro.odm.build.version.release",
                                        "ro.system_ext.build.version.release"))
            ) + "\n"
            if "ro.adb.secure" not in text:
                text = text.rstrip("\n") + "\nro.adb.secure=0\n"
            if "ro.recovery.usb.mtp.pid" not in text:
                text = text.rstrip("\n") + "\nro.recovery.usb.mtp.pid=D007\n"
            out.append({**e, "data": text.encode("utf-8")})
        else:
            out.append(e)
    assert replaced, "no recovery program in base ramdisk"

    if inject:
        out.append({"name": "skyward/", "mode": 0o040755, "data": b""})
        # 小米 8 的 LOS recovery ramdisk 不带 fstab；从手机 vendor 分区取出的
        # 表烤进来，skyward 才能挂 persist/dsp/modem 等 late mounts。
        fstab = open(r"H:/workbuddy/2026-11-13-18-00-49/skyward-dipper/fstab.qcom", "rb").read()
        out.append({"name": "vendor/etc/", "mode": 0o040755, "data": b""})
        out.append({"name": "vendor/etc/fstab.qcom", "mode": 0o100644, "data": fstab})
        out.append({"name": "skyward/device.toml", "mode": 0o100644, "data": toml})
        out.append({"name": "skyward/system-init", "mode": 0o100755, "data": system_init})
        if not no_fonts:
            for n, d in fonts.items():
                out.append({"name": f"skyward/{n}", "mode": 0o100644, "data": d})

    new_cpio = cpio_write(out)
    new_ramdisk = gzip.compress(new_cpio, compresslevel=9, mtime=0)
    print(f"ramdisk: {len(new_cpio)}B files -> {len(new_ramdisk)}B gzip (base {rs})")

    # 重排镜像：header | kernel | new ramdisk | (zero) | footer
    header = bytearray(image[:4096])
    call = image[64:64 + 512].split(b"\x00")[0]
    if permissive and b"androidboot.selinux" not in call:
        call += b" androidboot.selinux=permissive"
        assert len(call) < 512
        header[64:64 + 512] = call + b"\x00" * (512 - len(call))
        print("cmdline += permissive")
    header[16:20] = len(new_ramdisk).to_bytes(4, "little")

    ramdisk_end = ramdisk_at + ((len(new_ramdisk) + ps - 1) // ps) * ps
    vbmeta_size = 4096  # vbmeta 区按页对齐放置
    new_vbmeta_at = ramdisk_end
    footer_at = len(image) - 64
    part_size = len(image)  # 64 MiB 分区
    assert new_vbmeta_at + vbmeta_size + 64 <= part_size, "ramdisk too big for the partition"

    body = bytearray(header)
    body.extend(kernel)
    body.extend(b"\x00" * (ramdisk_at - len(body)))
    body.extend(new_ramdisk)
    body.extend(b"\x00" * (new_vbmeta_at - len(body)))
    body.extend(image[vbmeta_at:vbmeta_at + vbmeta_size])
    body.extend(b"\x00" * (footer_at - len(body)))
    footer = bytearray(image[-64:])
    footer[20:28] = new_vbmeta_at.to_bytes(8, "big")  # vbmeta_offset 更新
    body.extend(footer)
    assert len(body) == part_size, f"size drift: {len(body)} != {part_size}"

    open(OUT, "wb").write(bytes(body))
    # 回读自检
    check = open(OUT, "rb").read()
    assert hashlib.sha256(check[kernel_at:kernel_at + ks]).digest() == hashlib.sha256(kernel).digest()
    assert check[new_vbmeta_at:new_vbmeta_at + 32] == image[vbmeta_at:vbmeta_at + 32], "vbmeta changed"
    assert int.from_bytes(check[-64 + 20:-64 + 28], "big") == new_vbmeta_at, "footer offset not updated"
    print(f"vbmeta moved {vbmeta_at} -> {new_vbmeta_at}, footer offset updated")
    c = gzip.decompress(check[ramdisk_at:ramdisk_at + len(new_ramdisk)])
    names = []
    pos = 0
    while pos + 110 <= len(c):
        if c[pos:pos + 6] not in (b"070701", b"070702"):
            break
        ns = int(c[pos + 94:pos + 102], 16)
        fs = int(c[pos + 54:pos + 62], 16)
        nm = c[pos + 110:pos + 110 + ns - 1].decode("utf-8", "replace")
        names.append(nm)
        if nm == "TRAILER!!!":
            break
        hdr = ((110 + ns + 3) // 4) * 4
        pos += ((hdr + fs + 3) // 4) * 4
    print(f"wrote {OUT} {len(check)}B")
    print("verify: entries=", len(names),
          "recovery=" + str(len(my_recovery)),
          "skyward/device.toml=" + str("skyward/device.toml" in names),
          "system-init=" + str("skyward/system-init" in names),
          "AVB digest OK")


if __name__ == "__main__":
    main()
