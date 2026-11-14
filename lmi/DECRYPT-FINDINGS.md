# lmi 解密（/data）——实测结论与证据链

日期：2026-11-14　设备：Redmi K30 Pro（lmi）　当前镜像：`skyward-lmi-0.2.0-fixed.img`

## 一句话结论

**不是 Skyward 的代码问题，也不是我的 HIDL 实现问题**：这台机器的 FBE/metadata 密钥 blob **在 recovery 引导环境下会被 QTI keymaster TEE 拒绝解开**——连成熟的 TWRP 3.7.1 用同一套 keymaster 4.x 也解不开。系统正常启动时同一把 blob 工作正常。

## 证据链（全部真机实测）

### 1. Skyward 侧：keymaster 可达、编解码正确，但 blob 被判无效

启动探针（`skyward_crypto::keymint::probe()`，写 kmsg）实测输出：

| 调用 | 结果 |
|---|---|
| `getHardwareInfo`（code 1） | `status=0`、`SecurityLevel=1`（TrustedEnvironment，**TEE 真的在**）、name 16 字节 + author 3 字节（即 `qti-keymaster-4` / `QTI`） |
| `getKeyCharacteristics`（code 9，真实 463B blob） | `status=0`、**`ErrorCode = -33`** |

Keymaster 错误码 **-33 = `KM_ERROR_INVALID_KEY_BLOB`**（硬件认为这把 key blob 无效/无法解包）。

> 附带确认：HIDL 传输层（`BC_TRANSACTION_SG` + `BINDER_TYPE_PTR` 40 字节地址对象）、`hidl::find`、`describes`、`vec<uint8_t>`/`string` 编解码**全部正确**，方法序号表 = 3.0 布局（index0=`getHardwareInfo`、8=`getKeyCharacteristics`、15=`begin`、16=`update`、17=`finish`，**无 abort**）。

### 2. 密钥文件是真的、格式合法

`/metadata/vold/metadata_encryption/key/`：

| 文件 | 大小 | 内容特征 |
|---|---|---|
| `keymaster_key_blob` | 463B | 魔数 `"pKMblob\0"` + `"DKMK"` + version 3 → 合法的 keymaster blob |
| `encrypted_key` | 491B | 密文（GCM） |
| `secdiscardable` | 16384B | 绑定用 |
| `version` | 1B | `"1"` |

### 3. 系统侧：metadata 加密确实在用

系统（LineageOS 16）实测：

- `ro.crypto.metadata.enabled = true`
- `ro.crypto.state = encrypted`、`ro.crypto.type = file`（FBE）
- `/data` 挂在 `/dev/block/dm-41`（有 dm 层）
- `/metadata/vold/metadata_encryption/key/` 仍在使用（权限 0700，root 才能读）

即：**同一把 blob，系统能解，recovery 不能解。**

### 4. 决定性对照：TWRP 3.7.1 也解不开

刷回原 TWRP（`probe/lmi-recovery-raw.img`）启动后，其 `/tmp/recovery.log`：

```
I:FBE contents 'ice', filenames ''
I:setting Key_Directory to: /metadata/vold/metadata_encryption
I:Keymaster_Ver::Using keymaster version '4.x' for decryption
I:Unable to decrypt metadata encryption
I:FBE setup failed. Trying FDE...
I:Unable to mount '/data'
```

**成熟实现、同样的 keymaster 4.x 路径，同样失败。** 这是 `-33` 的独立复现。

### 5. 已排除的假设

| 假设 | 实测 | 结论 |
|---|---|---|
| 是我 HIDL 编解码写错 | `getHardwareInfo` 正确返回 TEE 等级与厂商名；`vec<u8>`/string 往返正确 | 排除 |
| 引导状态不同（unlocked/orange） | recovery 与系统均为 `verifiedbootstate=orange`、`vbmeta.device_state=unlocked`、`secureboot=1` | 排除 |
| keymaster HAL 缺属性依赖 | vendor 的 `keymaster@4.0-service-qti.rc` 只有 `class early_hal`、`user system`、`group system drmrpc`，不依赖任何 props | 排除 |
| TEE 没起来 | `SecurityLevel=1`（TrustedEnvironment） | 排除 |
| 密钥文件是残留垃圾 | 系统 `ro.crypto.metadata.enabled=true`、`/data` 在 dm 层上 | 排除 |

## 剩下的可能原因（已做实验，假设被证伪）

QTI keymaster TA 把 blob 包在**按引导上下文派生的 HBK** 下——这条假设**已实测排除**。

做法：`patch_cmdline.py` 把系统独有的身份/状态参数补进 recovery 的引导命令行（腾掉重复冲突的两个 `buildvariant`，补 5 条，498 字节），并重算 AVB 哈希后刷入。

| 步骤 | 结果 |
|---|---|
| 参数是否生效 | ✅ `ro.boot.serialno=3c64ac03`、`ro.boot.keymaster=1`、`ro.boot.hwversion=3.9.0`、`ro.boot.cpuid=0xdf955842`、`ro.boot.cert=M2001J11C` 全部就位 |
| 解密探针 | ❌ 仍为 `ErrorCode = -33`（`dfffffff`） |

**结论：引导参数不是原因。** 至此，能低成本验证的假设已全部排除，剩下的是 TEE/平台层面的限制：同一把 blob、同一个 QTI TA、同样的解锁状态，**系统引导可解、recovery 引导不可解**，且这不是 Skyward 独有（TWRP 3.7.1 同样失败）。

## 结论对功能的影响

| 功能 | 状态 |
|---|---|
| 挂载页（分区列表 / 挂载 / 卸载） | ✅ 已修好并验证 |
| system / vendor / product / odm / system_ext 挂载 | ✅ |
| MTP、adb、刷分区镜像、备份系统分区 | ✅ |
| **读 /data 内容（解密）** | ❌ 被 TEE 拒绝，非本程序可控 |
| 格式化 /data（factory reset） | ✅ 不需要解密 |
| 原样备份 /data（整块镜像，加密态） | ✅ 不需要解密 |

## 已落地的替代能力：整块备份 / 还原 /data（加密态，不需要密钥）

解密不可行，但"保住数据"可以不需要解密。`backup.rs` 已改造（2026-11-14）：

- **备份**：`/data` 解不开时，备份页勾"数据"自动改为**整块镜像**（`userdata.img`，按 by-name `userdata` 的块设备逐字节复制，lz4 可选）。计划列表里显示 `userdata` 与其字节数（本机 114,898,743,296 ≈ 107 GiB）。
- **还原**：按备份文件名后缀自动识别（`.img` = 整块写回 userdata 分区并校验 SHA-256；`.tar` = 原有文件级还原）。写回前会卸载占用的挂载点，写完读回校验。
- **顺带修复**：`backup()`/`restore()` 原来无条件要求 A/B slot（lmi 是 A-only，整个备份功能在这台机器上从未可用）。现 slot 为可选：Boot/Efs/Data 在 A-only 上可用；**System（super 逻辑分区）在 A-only 上明确拒绝**。
- **注意事项**：目的地不能用内置存储（它就是 /data），需 U 盘且剩余空间 ≥ 107 GiB；密文压缩收益极低；勾"校验"时间翻倍；还原整块写回会覆盖现有 /data。

## 复现命令

```bash
# 探针（启动时自动跑，读 kmsg）
adb shell "dmesg | grep 'key probe'"

# TWRP 对照
fastboot flash recovery probe/lmi-recovery-raw.img && fastboot reboot recovery
adb shell "grep -iE 'decrypt|keymaster' /tmp/recovery.log"
```
