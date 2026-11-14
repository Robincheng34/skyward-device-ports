# OnePlus 7T Pro（hotdog, HD1910）适配记录

日期：2026-11-14　底座：LineageOS 23.2-20261009 官方 recovery（sha256 3a2e1f8a…）

## 结果

**Skyward 0.2.0 在 7T Pro 上通过 `fastboot boot` 完整运行**（`init.svc.recovery=running`），零分区写入，全程可逆。

## 产物

- `skyward-hotdog.img`（84,328,448 字节，≤ 100MiB recovery 分区，可刷）
- `build_hotdog.py`（构建器，多开关：`--no-inject / --lz4 / --no-permissive / --no-prop / --keep-recovery / --no-fonts`）
- `lzc.py`（LZ4 legacy 压缩器，带自检）
- `device.toml`（hotdog 配置：A/B、display 1440x3120@560、[firmware] modem、persist/dsp、efs=[modemst1,modemst2]、服务×4）

## device.toml 关键内容

- `[device] ab=true`、`[display] 1440x3120 density=560`
- `[firmware] partition="modem"`（挂 /firmware，QSEE 需要）
- 服务：**hwservicemanager**（取自 /mnt/system/system/bin）→ qseecomd → keymaster@4.0-qti → gatekeeper@1.0-qti，每个带
  `libraries = ["/mnt/system/system/lib64", "/vendor/lib64", "/odm/lib64", "/system/lib64"]`
- `[backup] efs = ["modemst1", "modemst2"]`

## ramdisk 注入（相对底座）

1. `/system/bin/recovery` ← skyward 0.2.0（8,601,864，含全部 lmi 补丁，A/B 路径不受影响）
2. **`/skyward/` 目录条目 + device.toml + system-init**（⚠️ 内核 initramfs 解包不会自动建父目录，缺目录条目=文件被静默跳过）
3. `skyward/MiSansVF.ttf` ← **子集字体**（GB2312 一级 3755 字 + ASCII，varLib.instancer wght=400 + pyftsubset：20MB → **980KB**）
4. `system/lib64/{libdl_android,libandroidicu,libicuuc,libicui18n}.so` ← 从安装系统的 **runtime/art APEX payload** 里 debugfs 提取（APEX 未挂载，这些是指向它的悬空符号链接）
5. `prop.default`：`ro.secure=0 / ro.adb.secure=0 / ro.debuggable=1` + **剔除 ro.build.version.release/security_patch/vendor.security_patch**（否则 init 拒绝 skyward 设置版本 prop，bring_up 全断）
6. cmdline 追加 `androidboot.selinux=permissive`
7. ramdisk 用 **gzip**（LZ4 亦可，见下）

## 途中解决的坑（新设备通用）

| 坑 | 表现 | 根因/对策 |
|---|---|---|
| ABL 状态依赖 | 崩溃回落后再 `fastboot boot` 一律 `Load Error` | **每次测试前必须干净重启**（回系统→`adb reboot bootloader`） |
| ramdisk 体积上限 | ramdisk gzip >~25MB 时内核/init 早期失败回落 fastboot | ABL 对 ramdisk 有装载上限（20.3MB✅ 30.5MB❌）→ 字体子集化是正解 |
| skyward 文件静默消失 | `read config /skyward/device.toml: No such file` | cpio 无 `skyward/` 目录条目，内核解包不建父目录 |
| `[display] density` 必填 | `density is required to lay out the UI` | device.toml 加 display 段 |
| 面板节点找不到 | `panel … is not in the device tree` | hotdog 面板节点在 device-tree **第一层**（小米在第二层）→ ui.rs 加第一层回退 |
| 亮度无标定 | `gives its normal maximum as none of …` | OOS dtbo 面板节点无任何亮度属性 → ui.rs 终极回退 normal=max |
| firmware_config 不存在 | `write 1 to …/force_sysfs_fallback: ENOENT` | 4.14 内核无该 sysfs → 改为尽力而为（记 kmsg） |
| 版本 prop 冲突 | `init refused ro.build.version.release=11` → bring_up 全断 | 底座 prop.default 自带 16 → 构建器剔除 |
| 服务秒退 linker | `libhardware/libion/libdl_android/libandroidicu/libicuuc not found` | 前两个在 /mnt/system/system/lib64；后三个在 APEX 里（悬空符号链接）→ 提取烤入 + services 配 libraries |
| qseecomd 起不来 | exit 1 循环 | 缺 /firmware（TA 加载）→ [firmware] modem |

## 现状与遗留

- ✅ 启动、UI、super 六分区挂载（odm/product/system/system_ext/vendor/vendor_dlkm）、/firmware、persist/dsp、MTP、adb（免授权）
- ⚠️ **qseecomd 已运行（TEE 通道通了）**；keymaster/gatekeeper/hwservicemanager 由 skyward 启动时仍 SIGABRT（手动运行 hwservicemanager 正常）——只影响 keymint/HIDL 服务注册，即解密；而 hotdog 是 keymaster 4.x HIDL + QTI TEE，与 lmi 同类，解密预期同受 TEE 平台限制。后续若要攻坚：排查 skyward 启动环境（stdio/fd）与手动环境的差异。
- 解密可行性未单独验证（keymaster 服务未稳定）；按 lmi 经验预期不可行，整块 /data 备份/还原方案可用（skyward 备份功能 lmi 版已带）。

## 刷入方式

`fastboot flash recovery_a recovery_b`（当前用 `fastboot boot` 临时启动即用，不写分区）。
