# 逆向对比：skyward-lmi-0.1.2.img（他人） vs skyward-lmi.img（我方 0.2.0）

> 方法：REA(reverse-engineer-anything) v6.8.0 doctor/能力探测 + 直接 bootimg header / cpio(newc) / ELF / strings 解析。
> REA 深度二进制能力在本机不可用（`inspect-binary-layout` 返回 `capability_unavailable`：需 Linux x64 + pwntools；Hopper/Ghidra/IDA 均未安装；node 22.22.2 < 22.23.4）。
> 数据源：`H:/idmDownload/skyward-lmi.img`（我方） / `C:/Users/Robin/Desktop/skyward-lmi-0.1.2.img`（他人）。

## 1. 结论先行

**我方镜像起不来的根因不是 Skyward 本身，而是「基线镜像（kernel+dtbo+ramdisk）」不匹配 lmi。**
他人镜像是 **「fuzhi 自编译内核 + 配套 dtbo + sekaiacg TWRP 3.7.1 ramdisk」** 的完整自洽组合；
我方是 **「LineageOS 23.2 官方内核 + 其配套 dtbo + stock recovery ramdisk」**。
lmi 的 bootloader/内核交接对 kernel+dtbo 配套极敏感，用 LineageOS 的 kernel+dtbo 配外来 ramdisk，会在内核→init 交接阶段失败直接回 fastboot。

## 2. boot image 头 / 内核 / dtbo

| 项 | MINE（我方 0.2.0） | OTHER（0.1.2） |
|---|---|---|
| header_version | 2 | 2 |
| page_size | 4096 | 4096 |
| kernel 版本 | `4.19.325-cip131-st15-perf-g71b13e62f057`（LineageOS 23.2，Android clang **21.0.0**，+LTO/+BOLT/+PGO，`root@6b98c25dfafd`） | `4.19.325-fuzhi-20261026+`（**fuzhi 自编译**，ZyC clang **16.0.6**） |
| kernel_size | 53,456,920 | 46,659,600 |
| kernel sha256(前8B) | db46b5eef3f3（= stock LineageOS） | cd9d1a74c442（≠stock≠TWRP，独立内核） |
| dtbo_size | 1,424,944（LineageOS 配套） | 1,603,572（fuzhi 配套） |
| cmdline | stock 风格（无 console=；含 `androidboot.fstab_suffix=qcom androidboot.init_fatal_reboot_target=recovery`） | TWRP 风格（`console=ttyMSM0,115200n8 ... androidboot.selinux=permissive ... buildvariant=eng`） |

> 已排除：header 各地址字段（kernel_addr=0x8000 / ramdisk_addr=0x1000000 / tags_addr=0x100 / page_size=4096）三者完全一致，非 header 问题。

## 3. ramdisk 基线（cpio 内容）

| 项 | MINE | OTHER |
|---|---|---|
| 压缩格式 | LZ4 legacy（`02 21 4c 18`） | gzip（`1f 8b 08`） |
| 条目数 | **601** | **3679** |
| 基线 | LineageOS/AOSP stock recovery（`bootstrap-apex`、AOSP `res/images`、`android.hardware.health-service.qti_recovery`） | **TWRP 3.7.1 @ sekaiacg**（`twrp`、`busybox`、`magiskboot`、`customzip/Magisk`、`libtwrp*`、`twrp.flags`；`ro.product.system.name=twrp_lmi`，构建 2024-12-13，Android 16 树 SP2A.220405.004） |
| 共有文件 | 506 | 506 |
| 独有文件 | 95 | 3173 |

## 4. Skyward 载荷差异

| 项 | MINE（0.2.0） | OTHER（0.1.2） |
|---|---|---|
| `/system/bin/recovery`（=skyward 主二进制） | 8,583,776 B，含 `"Skyward 0.2.0"` | 8,455,040 B |
| 构建 rustc commit | `0ef1bc386059596d…` | `254b59607d4417e9…` |
| cargo registry | 官方 `index.crates.io` | 国内镜像 `rsproxy.cn`（依赖更全：rustls/ureq/ring/jiff/ttf-parser） |
| `/skyward/system-init` | **有**（1,098,968 B，含 `skyward-modules/src/modprobe.rs`，负责 modprobe/系统级初始化） | **无**（推测 system-init 已并入主二进制，属另一种构建配置） |
| `/skyward/device.toml` | 8,037 B（我方理论配置） | **1,713 B（lmi 真机调优配置）** |
| `/system/etc/init/skyward-mtp.rc` | 1,223 B | 1,223 B（**完全相同**） |
| `/init` | symlink→`/system/bin/init`（0120750） | symlink→`/system/bin/init`（0120777） |

### device.toml 关键差异（OTHER 明显是 lmi 真机调好的）
- `[touch] ignore = ["hbtp_vm"]` —— lmi 触摸驱动会多出虚拟面板，TWRP 需 `TW_INPUT_BLACKLIST=hbtp_vm`；我方缺此项。
- `[haptics]` aw8697 精确波形/模式/时长。
- keymaster/gatekeeper 服务以 **root** 运行（我方写成 `user="system"` + `ready_hardware_service`）。
- `mounted = ["firmware","persist","bluetooth","dsp"]`（我方只挂 persist）。

## 5. 失败链（推断）
1. flash 我方镜像 → bootloader 校验/加载 kernel+dtbo 通过；
2. 内核启动，但与 LineageOS kernel 配套的 dtbo / first-stage init 期望 LineageOS 自己的 vendor 模块与 ramdisk 布局；
3. 换成 stock recovery ramdisk 后，init 交接失败 → panic → **回 fastboot**。

## 6. 修复路线

**A（最快，推荐先验证）：** 直接 flash 他人 `skyward-lmi-0.1.2.img`（fuzhi kernel+dtbo+TWRP ramdisk 自洽，且 device.toml 已 lmi 调优）。先确认它在本机能起。

**B（我方自有 0.2.0 构建）：** 以 OTHER 的 kernel+dtbo+cmdline 为基线，ramdisk 改用「TWRP 3.7.1 ramdisk（`probe/lmi-recovery-raw.img`）注入我方 0.2.0 `skyward` + `system-init`」，并采用 OTHER 版 `device.toml`（lmi 正确配置，替换我方理论版）。这样既保住 0.2.0，又能启动。

> 备份齐全：`probe/lmi-boot.img`、`lmi-vbmeta.img`、`mdm1m9kefs1/2/3.img`、`mdm1m9kefsc.img`、`lmi-recovery-raw.img`（TWRP）。设备当前处于 fastboot，recovery 已是 TWRP，安全。
