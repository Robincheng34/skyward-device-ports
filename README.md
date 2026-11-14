# skyward-device-ports

Porting notes, build pipelines and patches for running
[Skyward](https://github.com/kirklin/skyward) (a Rust-based Android recovery) on devices
the upstream does not target.

Two devices are fully documented, both verified on real hardware:

| Device | Codename | Slot | Base | Result |
|---|---|---|---|---|
| Xiaomi POCO F2 Pro / Mi 10 Turbo | `lmi` | A-only | others' TWRP-style image (fuzhi kernel) | fully running: mounts, mount page, MTP, raw `/data` backup |
| OnePlus 7T Pro | `hotdog` | A/B | LineageOS recovery + OEM kernel | fully running incl. touch |

Nothing in this repository is a flashable image: everything here is method,
scripts, patches and configuration, so you can rebuild for your own device.

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
