# Skyward 0.2.0 —— 完整 A-only 移植说明（Redmi K30 Pro / lmi）

> 目标：让上游 Skyward 0.2.0（假设 A/B 动态分区）在 **A-only 但使用 super 动态分区**的 lmi 上运行。
> 结果：**成功**。0.2.0 recovery 在 lmi 稳定运行，system/vendor 等已挂载，keymaster/gatekeeper 服务 running，UI + MTP 正常。
> 产物：`skyward-lmi-0.2.0-fixed.img`（128MiB）。修补后的源码：`patched-src/`。

## 1. 为什么 0.2.0 原生跑不起来

lmi 是 A-only（无 `_a/_b`），但**是动态分区设备**（system/vendor/product/odm/system_ext 都在 `super` 里，`/dev/block/by-name/super -> sda32`，metadata 在 sda18）。Skyward 0.2.0 的启动链硬依赖 A/B：

- `main.rs` 启动菜单路径：`prepare(&cfg, booted_slot()?)`
- `booted_slot()` = `skyward_vab::current_slot()?.context("not an A/B device")` —— A-only 时 `current_slot()` 返回 `None` → 直接 `bail`。
- `mount_partitions(slot: Slot)` 用 `slot.number()` 读 LP metadata、用 `slot.suffix()` 过滤分区名 —— 都假设有 `_a/_b`。

## 2. 五处源码改动（见 `patched-src/`）

### (1) `crates/skyward/src/main.rs`
- `fn bring_up(cfg, slot: Slot)` → `fn bring_up(cfg, slot: Option<Slot>)`；props 取值改为：
  ```rust
  let props = match slot {
      Some(s) => skyward_info::installed_props(s)?,
      None => skyward_info::installed_props_a_only()?,
  };
  ```
- 启动菜单路径（原 `prepare(&cfg, booted_slot()?)?`）改为：
  ```rust
  match skyward_vab::current_slot()? {
      Some(slot) => prepare(&cfg, slot)?,
      None => prepare_a_only(&cfg)?,
  }
  ```
- `prepare` 内的 `bring_up(cfg, slot)` → `bring_up(cfg, Some(slot))`。
- 新增 `prepare_a_only(cfg)`：调 `skyward_vab::mount_partitions_slotless()`，记日志并 `bring_up(cfg, None)`（错误只记录，不致命）。
- `bring_up` 里 `cfg.partitions.mounted` 的循环由 `?` 中断改为**尽力而为**（缺一个分区只记日志，不阻断后续服务）。

### (2) `crates/skyward-vab/src/partitions.rs`
- 抽出 `map_and_mount_base(p, devices, base: &str)`（原 `map_and_mount` 改为 `map_and_mount_base(p, devices, base(p, slot))`）。
- 新增：
  ```rust
  pub fn mount_partitions_slotless() -> Result<Mounts> {
      // 挂 /metadata；skyward_lp::read(super, 0)（metadata 第 0 份）；
      // 对 md.partitions 中非 -cow、非 disabled、非空的全部逻辑分区，
      // 以 p.name（无后缀）为 base 做 dm-linear 映射并只读挂载到 mount_point(name)。
  }
  ```

### (3) `crates/skyward-vab/src/lib.rs`
- `pub use partitions::{ ... , mount_partitions_slotless, ... }` 补导出。

### (4) `crates/skyward-info/src/lib.rs`
- `pub fn boot_props()`（仅 `ro.boot.*`）。
- `pub fn installed_props_a_only()`：遍历 `["system","system_ext","vendor","product","odm"]`，从 `skyward_vab::mount_point(base)` 读 `build.prop`/`default.prop`，叠加在 boot props 上。

### (5) `crates/skyward/src/ui.rs`
- `fn normal_max(max)`：找不到 Xiaomi 专有属性（`mi,max-brightness-normal` 等）时，回退用标准 `qcom,mdss-dsi-bl-max-level` 作 normal=full（lmi 的 `qcom,mdss_dsi_j11_38_08_0a_fhd_cmd` 屏只有标准属性，否则 fatal）。

## 3. 交叉编译（WSL，本机 Windows 无 Android target）

```bash
export PATH=$HOME/.cargo/bin:$PATH
export NDK=/root/android-ndk-r29
export TC=$NDK/toolchains/llvm/prebuilt/linux-x86_64
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER=$TC/bin/aarch64-linux-android30-clang
export CC_aarch64_linux_android=$TC/bin/aarch64-linux-android30-clang
export AR_aarch64_linux_android=$TC/bin/llvm-ar
cd ~/sb/skyward
cargo build --release --target aarch64-linux-android -p skyward
# 产物 target/aarch64-linux-android/release/skyward = 8,586,080 B
```
`skyward-system-init` 无需改动，复用同版本 0.2.0 现成二进制（1,098,968 B）。

## 4. 打包（`rebuild_final.py`）

以他人 `skyward-lmi-0.1.2.img` 为底座（fuzhi 内核 + 配套 dtbo + TWRP 3.7.1 ramdisk，已验证可启动），只改 ramdisk：

- 剔除 TWRP 的 `customzip/Magisk`（24.7MB，Skyward 用不上）腾出空间（分区正好 128MiB）。
- `/system/bin/recovery` ← 补丁后 0.2.0；新增 `/skyward/system-init`；`/skyward/device.toml` ← 0.1.2 配置删 `[haptics]` 段（0.2.0 的 `[haptics]` 需 `resonance` 字段，可选，删掉即可）。
- kernel / recovery_dtbo / dtb 逐字节保留；重排后 `recovery_dtbo_offset` 相应更新。
- **AVB**：他人镜像 `algorithm=NONE`（纯哈希无签名），`digest=SHA256(image[0:127635456])` 无盐，位于 vbmeta 偏移 396 → 重算 digest 回填。`original_image_size=127,635,456`，vbmeta@127635456，footer@末尾。

## 5. 验证（真机 dmesg）

```
skyward: lmi 0.2.0 recovery up, misc command "boot-recovery" args [], asking for Menu
skyward: mounted system on /mnt/system (ext4)
skyward: mounted vendor on /vendor (erofs)
skyward: mounted product on /mnt/product (ext4)
skyward: mounted odm on /odm (erofs)
skyward: mounted system_ext on /mnt/system_ext (ext4)
skyward: 128 device nodes given the owner their phone describes
skyward: ro.build.version.release is the installed system's 16
skyward: persist is mounted on /mnt/vendor/persist
skyward: dsp is mounted on /vendor/dsp
skyward: mtp: the computer opened a session
```
`init.svc.recovery=running`（稳定，非 restarting）；`init.svc.keymaster-4-0=running`、`init.svc.gatekeeper-1-0=running`；
`/proc/mounts`：dm-0→/mnt/system、dm-1→/vendor(erofs)、dm-3→/odm、dm-4→/mnt/system_ext。

## 6. 收尾处理（已完成，dmesg 零错误）

- **触摸（原 `hbtp_vm` 问题）无需补丁**：0.2.0 的 `input.rs` 选设备条件是 `direct && mt`（`PropType::DIRECT` + `ABS_MT_POSITION_X/Y`）。lmi 的虚拟设备 `uinput-goodix` 无 `INPUT_PROP_DIRECT`，被天然排除；真实触摸（`fts_ts` / `xiaomi-touch`）才是 direct+mt。0.2.0 用 `direct` 判定取代了 0.1.2 的 `ignore` 黑名单。
- **firmware**：lmi 根本没有 `firmware` 分区（`/dev/block/by-name/firmware` 不存在），已从 device.toml `mounted` 移除。
- **bluetooth**：vendor fstab 标 `vfat`，但 fuzhi 的 recovery 内核挂载返回 EINVAL（疑似未编 vfat 驱动），恢复环境用不到 BT，已从 `mounted` 移除。
- 最终 `mounted = ["persist", "dsp"]`，均正常挂载。`bring_up` 完整走完，无 "devices not brought up"。

### 最终状态（真机验证）
```
skyward: lmi 0.2.0 recovery up ... asking for Menu
mounted system /mnt/system  vendor /vendor(erofs)  product  odm  system_ext
128 device nodes …  ro.build.version.release = 16
persist → /mnt/vendor/persist   dsp → /vendor/dsp
mtp: the computer opened a session
```
`dmesg | grep -iE 'skyward.*(not mounted|failed|error|not brought)'` → **空**。
`init.svc.recovery / keymaster-4-0 / gatekeeper-1-0` 全 `running`。
