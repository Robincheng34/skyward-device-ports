# skyward-device-ports

Porting notes, build pipelines and patches for running
[Skyward](https://github.com/kirklin/skyward) (a Rust-based Android recovery) on devices
the upstream does not target.

Two devices are fully documented, both verified on real hardware:

| Device | Codename | Slot | Base | Result |
|---|---|---|---|---|
| Xiaomi Redmi K30 Pro | `lmi` | A-only | TWRP 3.7.1 ramdisk (sekaiacg) + fuzhi MIUI-era kernel | fully running: mounts, mount page, MTP, raw `/data` backup |
| OnePlus 7T Pro | `hotdog` | A/B | LineageOS recovery ramdisk + OxygenOS 11 stock kernel | fully running incl. touch |

## Why the lmi base is TWRP-line, not LineageOS

The K30 Pro is a MIUI-era device, and the kernel↔dtbo↔ramdisk trio must come
from one consistent world. Tested on the real phone:

| Base line | Outcome |
|---|---|
| MIUI stock | boots (the phone's daily ROM), recovery ramdisk is MIUI's own |
| LineageOS official kernel + dtbo + stock recovery ramdisk | **panics before init** — our first attempt, documented in `lmi/RE-DIFF-1.2-vs-mine.md` |
| TWRP 3.7.1 (sekaiacg build, fuzhi 4.19.325 kernel) | boots — **chosen as the base** |

The published image keeps that TWRP-line kernel/dtbo/ramdisk and only replaces
the recovery program with patched Skyward 0.2.0. The recovery partition is
independent of the ROM you run, so the phone stays on MIUI or LineageOS as-is.
The same TWRP base also fails to decrypt /data in recovery (QTI TEE wall,
`lmi/DECRYPT-FINDINGS.md`), which is why the image ships whole-block encrypted
`/data` backup instead.

**Prebuilt images** are on the
[Releases page](https://github.com/Robincheng34/skyward-device-ports/releases):
[`v0.2.0-lmi`](https://github.com/Robincheng34/skyward-device-ports/releases/tag/v0.2.0-lmi) ·
[`v0.2.0-hotdog`](https://github.com/Robincheng34/skyward-device-ports/releases/tag/v0.2.0-hotdog).
Kernels and ramdisk bases inside them are third-party GPL builds — see the
release notes for attribution, and check your device's recovery partition size
before flashing.

## Layout

```
METHODOLOGY.md                 the full playbook, start here
lmi/                           the A-only story
  RE-DIFF-1.2-vs-mine.md       reverse-engineering two images to find why one boots
  A-ONLY-PORT.md               removing the A/B assumption from the boot path
  DECRYPT-FINDINGS.md          why FBE decryption cannot work here (TEE), evidence chain
  rebuild_final.py             repack: swap ramdisk, recomputed AVB hash footer
  patch_cmdline.py             edit boot cmdline, reseal AVB
  extract_ramdisks.py          LZ4-legacy + gzip ramdisk unpacker (pure Python)
  parse_cpio_only.py           newc cpio parser
  compare_imgs.py              boot image comparison
  device_lmi_020.toml          device config tuned on the phone
hotdog/                        the A/B story
  HOTDOG-PORT.md               nine pitfalls, from ABL quirks to touch layers
  build_hotdog.py              ten-flag build pipeline with single-variable isolation
  lzc.py                       LZ4 legacy frame compressor with round-trip selftest
  device.toml                  device config tuned on the phone
patches/patched-src/           patched source files (GPLv3, see below)
```

## The patches, in short

All against skyward 0.2.0:

- `main.rs` — slot-optional boot path (`prepare_a_only`), tolerant firmware
  fallback, optional bring-up of the mount list
- `skyward-vab/partitions.rs` — slotless super mapping
  (`mount_partitions_slotless`), slotless mount/unmount for the mount page
- `skyward-info/lib.rs` — property sources without a slot
- `ui.rs` — panel node on the first device-tree level, backlight fallback for
  panels without a normal-maximum calibration
- `input.rs` — touch panels that report `INPUT_PROP_POINTER` without
  `INPUT_PROP_DIRECT` (OnePlus) are still selected

## Licence

Skyward is GPLv3; these patches follow it. The two `device.toml` files and the
documentation are factual notes, use freely. No kernel, firmware or font
binaries are included — bring your own base image.
