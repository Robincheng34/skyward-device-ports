# 小米 8（dipper）适配记录

## 设备画像

| 项 | 实测 |
|---|---|
| 代号 / 型号 | `dipper` / MI 8（MIUI 12, Android 10, patch 2020-12） |
| 槽位 | **A-only**（无 slot_suffix） |
| 分区 | **纯物理分区（无 super）**：system/vendor 是 GPT 上的独立分区 |
| recovery 分区 | 64 MiB（0x4000000） |
| 加密 | FBE（`fileencryption=ice`），无 metadata 加密 |
| HAL | keymaster 3.0 + 4.0 HIDL、gatekeeper 1.0（无 KeyMint AIDL） |
| 启动方式 | **支持 `fastboot boot`**（零写入测试，比 lmi 安全） |

## 底座

LineageOS 22.2-20261121 官方 `recovery.img`（sha256 `9d20c8e0…`）。
结构：header v1、kernel 25.4MB、ramdisk 14.7MB（gzip）、**无 dtbo/dtb 段**、
尾部 26MB 零填充、带 AVB footer（vbmeta `algo=2` = SHA256+RSA 签名）。

## 攻克的九个坑

1. **无 super**：`prepare_a_only` 加物理分区分支——按 `/dev/block/by-name/<name>`
   只读挂载 system/vendor 到 `/mnt/*`（props 从这里读）。
2. **LOS ramdisk 无 fstab**：从手机 vendor 分区取出 `fstab.qcom`
   （persist/dsp/modem 等 late mounts），烤进 ramdisk 的 `/vendor/etc/`。
3. **prop.default 版本冲突**：底座预置 `ro.build.version.release=15`，
   init 拒绝 skyward 改成系统的 10 → 构建器剔除所有版本行。
4. **vbmeta 签名无法重算**：algo=2 无私钥 → 靠 `fastboot boot` 不校验；
   vbmeta 区右移到新 ramdisk 之后，footer 的 vbmeta_offset 同步更新。
5. **DRM panic（SIGABRT）**：`drm 0.15.0` 解析 flip-complete 事件时
   `crtc_id=0` → `unwrap()` panic。用 `[patch.crates-io]` 本地副本改为
   fallback 到 crtc handle 1（`patch_drm.py`）。另加全局 panic hook
   把 panic 文本写 kmsg（通用诊断资产）。
6. **面板节点不在设备树**：`dsi_ss_ea8074_notch_fhd_cmd_display` 在 DRM
   参数里但树里没有同名节点（面板用 phandle 引用）→ `normal_max`
   找不到节点时回退到背光全范围。
7. **`s2idle` sysfs 只读**：`write /sys/power/mem_sleep` 权限拒绝 →
   改为尽力而为（只记录，不退出）。
8. **tmpfs 挂载信息**：`installed_props_a_only` 改用 `/mnt/<name>` 路径。
9. **MTP 端点缺失**（未完全解决，非致命）：LOS recovery 的 init.rc
   只建 adb/fastboot functionfs；已补 `ffs.mtp` + mtp config 分支，
   但 `on fs` 里的 functionfs mount 未被执行，待进一步调试 init 时序。

## 验收结果

```
init.svc.recovery = running（pid 连续 5 次采样不变）
dipper 0.2.0 recovery up ... asking for Menu
mounted system on /mnt/system (ext4)   mounted vendor on /mnt/vendor (ext4)
ro.build.version.release = 10
dsp 挂载、AMS haptics 未用、中文界面正常
无 recovery failed / panic / signal 6
```

## 后续修复（2026-11-25）

- **A-only 点"更新"页报错**（`only an A/B phone has an update to merge`）：
  `pages.rs` 的 Advanced 列表改为按 `cx.info.slot.is_some()` 条件渲染
  —— A-only 机不显示"更新"入口，A/B 设备不变。
- **主页误导性提示**：无 super 的机型主页曾显示"读取到更新状态前，
  暂不刷写 super 中的分区"——`snapshot_state()` 在无 super 时返回
  `SnapshotState::None` 而不是 `Unknown`，提示消失。

## MTP 调试结论（未攻破，非致命）

dipper 走的是 `configfs=0` 的老式 android_usb 路径（`on fs` 块里挂
adb/fastboot 端点）。已验证：
- 手动 `mount -t functionfs mtp /dev/usb-ffs/mtp` **可以成功**（ep0 出现）；
- 但在 `on fs` 块里加任何 mtp mount 行会让 init 启动失败（设备起不来）；
- 在 `on property:sys.usb.config=mtp,adb` 分支里挂则因 skyward 在端点
  不存在时就不会设置该属性而永远不触发（鸡生蛋问题）。

当前镜像**已回退到稳定版**：只在 configfs=1 块保留 `ffs.mtp` function
声明，不碰启动关键路径。MTP 需更深层方案（如 skyward 自己挂载
functionfs，或改 init 的 ffs.ready 时序），暂列已知限制。

## 已知限制（非致命）

- MTP 文件传输不可用（见上）。
- keymaster 4 HIDL 在 recovery 下探测不到（解密预期同 lmi 平台墙）。
- metadata 分区不存在 → 设置不持久化。
- persist 挂载失败的日志（`/mnt/vendor` 只读导致 mkdir 失败），不影响核心功能。

## 产物

- `skyward-dipper.img`（64 MiB，可 `fastboot boot` 零写入验证）
- `build_dipper.py`（单文件构建器，含所有注入/补丁逻辑）
- `device.toml` / `fstab.qcom` / `patch_drm.py`
- 通用代码增强已合入 `patches/patched-src/`（panic hook、DRM 保护、
  面板回退、物理分区分支、s2idle 容错）
