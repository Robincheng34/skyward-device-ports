# Android Recovery 移植方法论 —— 三台设备实战沉淀

> 基于真机：Redmi K30 Pro（lmi, A-only）、OnePlus 7T Pro（hotdog, A/B）、
> 以及 lmi 上他人 0.1.2 镜像的逆向。目标：任何新设备 1~2 小时内跑通 Skyward（或同类 Rust recovery）。

---

## 1. 流水线总览（新设备 SOP）

```
① 底座获取 → ② 解包分析 → ③ 注入构建 → ④ 临时启动验证 → ⑤ 日志迭代修硬件项 → ⑥ 刷入固化
```

| 步骤 | 工具 | 要点 |
|---|---|---|
| ① 底座 | LOS 官方 download API / 用户 dump 分区 | **拒绝 .ops 救砖包**（加密容器）；优先 LOS 官方；OOS 机器可 `fastboot boot` 自己的 recovery 后 `dd` 拉 boot_a/dtbo_a |
| ② 解包 | `bootimg` 头解析脚本（header v2/v3/v4 差异） | 记录 kernel/ramdisk/dtbo/dtb 偏移、压缩格式、cmdline、自然结束偏移 vs 分区上限 |
| ③ 构建 | `build_hotdog.py` / `rebuild_final.py` | cpio 重组 + 压缩 + header 回写 + AVB 重封；**十开关隔离变体** |
| ④ 验证 | `fastboot boot`（一加支持）；小米只许 `flash` | 永远先临时启动，不写分区 |
| ⑤ 迭代 | UI 点操作 → dmesg `the data partition stays closed / recovery failed: {why}` | **禁用 CLI 子命令**（与在跑服务抢硬件会重启设备） |
| ⑥ 固化 | `fastboot flash recovery(_a/_b)` | 刷前 `dd` 备份原分区 |

## 2. 硬件层通用坑（按踩中频率排序）

### 2.1 底座匹配是第一生存条件（lmi 教训）
- 混搭基线（LOS 内核 + stock ramdisk）在 lmi 上**必然起不来**：kernel↔dtbo↔cmdline 必须配套自洽
- 他人镜像能启动 = "fuzhi 内核 + 配套 dtbo + TWRP ramdisk" 完整组合
- **结论：底座三件套（kernel/dtbo/cmdline）永远整套取自同一来源，绝不混搭**

### 2.2 ramdisk 装载上限（hotdog 教训）
- OnePlus 6T 时代 ABL 对 boot image 的 ramdisk 装载区 **约 25MB**：LZ4 18.9MB 过、30MB+ 拒载
- 表现怪异：**不是稳定报错**——`Load Error` 与 `Booting OKAY` 交替出现
- 对策：字体子集化（20MB MiSans → `varLib.instancer wght=400` + GB2312 常用字 → 980KB）
- **通用规则：注入前先算"底座 ramdisk 压缩后 + 注入体积"，超限先瘦身**

### 2.3 触摸设备的三个层次（hotdog 教训，最深的一坑）
1. **选择层**：驱动 properties 只有 `INPUT_PROP_POINTER` 没有 `DIRECT`（一加异类）→ 选设备逻辑要 `mt && (direct || pointer)` 兜底
2. **通信层**：I2C 对 TEE/时钟敏感——LOS 23.2/24 内核在 hotdog 上 TP **probe 失败**（`I2C write over retry limit`），换 **OOS 原厂内核**底座后芯片活了。**触摸坏了先查 dmesg 的 `[TP]`/I2C probe，不是 UI 层的锅**
3. **显示联动层**：TP 跟随显示状态；背光 0 = 用户看到"黑屏+触控无效"，实际事件在流（抓包 216 字节实证）
- **判别工具链**：`cat /proc/bus/input/devices`（看 PROP/ABS_MT）→ `pidof recovery; ls -l /proc/$pid/fd`（确认面板被打开）→ `cat /dev/input/eventX > file` 抓原始流判别驱动层 → `brightness` sysfs 排除显示层

### 2.4 cpio 的静默陷阱
- **父目录条目缺失 → 文件被 initramfs 解包静默丢弃**（`skyward/` 目录条目必须有，O_CREAT 不建目录）
- newc 头是 **13 个字段 = 110 字节**（6+12×8+1... 精确：magic6 + 13 个 8 位 hex 字段），少一个全盘解析崩
- 内核 initramfs 解包器对非法 cpio **不报错**，只跳过——一切以 `ls /skyward/` 实测为准

### 2.5 device.toml 必填字段（0.2.0 schema）
- `[display] density` 必填，缺失 fatal
- `[haptics]` 0.2.0 必填 `resonance`（sysfs 路径）；0.1.2 的 sysfs/wave/mode 全弃用——**配置跨版本不兼容，删段优于猜字段**
- `[partitions] mounted`：只填真实存在的分区（lmi 无 firmware 分区；bluetooth vfat 在 recovery 内核挂不上）
- 固件分区按机型：lmi 无 / hotdog 是 `modem`

### 2.6 服务启动链（vendor HAL 复活的完整清单）
```
hwservicemanager（A/B 机器，从 /mnt/system/system/bin 取）
→ qseecomd（TEE 通道，最先验证）
→ keymaster@4.0-service-qti / gatekeeper@1.0-service-qti
```
- **库链**：vendor 服务依赖 bionic APEX 私有库——`libdl_android.so`/`libandroidicu.so`/`libicuuc.so`/`libicui18n.so` 全在 `com.android.runtime.apex`/`com.android.art.release.apex`，`adb pull` + `debugfs dump /lib64/...` 提取后烤入 ramdisk
- **路径**：`[service] libraries = ["/mnt/system/system/lib64", "/vendor/lib64", "/odm/lib64", "/system/lib64"]`
- 手动复现法：`LD_LIBRARY_PATH=... /vendor/bin/qseecomd` 逐层看 linker 报错，修一个再试

### 2.7 版本 prop 冲突
- init **拒绝把已设的 ro 属性改成别的值**：LOS recovery 自带 `ro.build.version.release=16`，skyward 要设成安装系统的 11 → `bring_up` 中断、服务全不启
- 对策：构建器从 `prop.default` 剔除三个版本 prop，让 skyward 挂载后自己设

## 3. 打包层通用坑

### 3.1 AVB（vbmeta footer）
- `algorithm=NONE`（纯哈希）可纯 Python 重封：`digest = SHA256(image[0:original_image_size])` **无盐**，写回 `vbmeta_offset + 396`
- `original_image_size` 在 footer（最后 64 字节）`+12`；vbmeta_offset 在 `+20`
- **改任何字节都要重封，包括 cmdline**
- 分区上限即硬顶：lmi recovery 128MiB、hotdog 100MiB——**先查 `blockdev --getsize64`**

### 3.2 压缩格式
- gzip 全通；**LZ4 legacy 会被部分 ABL 拒载**（hotdog 实测三次全拒）——底座是什么就用什么，别降级
- 自研 LZ4 legacy 压缩器 `lzc.py`（54% 压缩率，带往返自检）

### 3.3 ABL 的状态依赖（最迷惑的坑）
- **同一镜像**：干净路径（系统→fastboot）= Booting OKAY；崩溃回落 fastboot 后连续尝试 = Load Error
- **铁律：每次 boot 测试前完整走「重启回系统 → 等 10s → reboot bootloader」**

## 4. 解密（FBE）的边界与真相（lmi + hotdog 双机验证）

| 层 | 事实 |
|---|---|
| KeyMint AIDL | lmi/hotdog 都是 Keymaster 3/4 **HIDL**，无 AIDL keymint；recovery 无 AIDL servicemanager（`service::declared` 一律驱动错 -2147483647）|
| HIDL 可达 | ✅ 自研探针实证 `getHardwareInfo` → status=0、SecurityLevel=1、qti-keymaster-4/QTI |
| TEE 拒 blob | ❌ `getKeyCharacteristics` 对真实 blob 返回 **-33 INVALID_KEY_BLOB**；**TWRP 3.7.1 同样失败**（独立复现）|
| 引导参数假设 | 补齐 serialno/keymaster/hwversion/cpuid/cert 后仍 -33 → **证伪** |
| 上游 | Skyward 官方只支持 KeyMint 设备，lmi 不在支持列表 |
| **可行替代** | **整块 /data 备份/还原**（加密态 dd，不需密钥）；明文数据走系统内 adb |

**方法论**：解密 = 探针先行（keymint probe 写 kmsg）→ 逐层排除（编解码→引导参数→对照 TWRP）→ **撞 TEE 墙即止损**，转向不依赖密钥的功能。

## 5. 探针体系（比日志猜测快十倍）

| 探针 | 实现 | 回答的问题 |
|---|---|---|
| `device detect` | 启动自动，一行 kmsg | A/B? 槽位? 密钥服务? 动态分区? |
| `key probe` | 启动自动，分片 kmsg | HIDL/AIDL 可达性、ErrorCode |
| 原始事件抓包 | `timeout N cat /dev/input/eventX > file` | 驱动层有没有报点（0=驱动死）|
| fd 检查 | `ls -l /proc/$(pidof recovery)/fd` | UI 层选中了哪个设备 |

**铁律**：`recovery <子命令>` 会与在跑服务抢硬件 → 设备重启；一切诊断走 UI 操作 + dmesg。

## 6. 工程纪律（血泪固化）

1. **多设备环境所有 adb/fastboot 必须 `-s <serial>`**，flash 前 getvar 核对——已发生过误刷未遂（靠 Volume Full 分区大小校验才没写进去）
2. **MSYS/Git Bash 一切路径参数 `MSYS_NO_PATHCONV=1`**（`/system/...`、`/mnt/...`、`/skyward/...` 都会被改写）
3. WSL 编译链：源码用 tar 流推到 `~/sb/skyward`（/mnt/h 不稳）；`aarch64-linux-android30-clang`；增量 14s~90s
4. 每 2~4 轮实验把结论落盘（memory + 设备专属 PORT.md），**崩溃循环/重启即设备回系统是常态不是事故**
5. 变体用开关（`--no-inject/--lz4/--keep-recovery/--no-fonts/--no-permissive/--no-prop`）做**单变量对照**，绝不一次改三个东西

## 7. 新设备速查清单

```
□ 设备代号/序列号；A/B or A-only（getprop ro.boot.slot_suffix）
□ 解锁状态；fastboot boot 是否被允许（决定测试安全性）
□ 底座三件套来源（LOS 官方 / OOS dd dump / TWRP）
□ 分区上限（recovery_a/b 大小）；AVB 算法（NONE?）
□ 加密：ro.crypto.type；fstab userdata 行（ice? wrappedkey? keydirectory?）
□ keymaster HIDL 版本（3.0/4.0/4.1?）；qseecomd 路径
□ TP 驱动（dmesg [TP] probe）；面板 DT 节点层级；亮度 sysfs 路径
□ 固件分区名（modem/firmware/persist/dsp/modemst1/2）
□ ramdisk 体积预算（ABL 上限，一加系 ~25MB）
```

## 8. 资产索引

| 资产 | 位置 |
|---|---|
| A-only 补丁源码（6 文件） | `patches/patched-src/` |
| lmi 打包器 + AVB 重封 | `lmi/rebuild_final.py`、`lmi/patch_cmdline.py` |
| hotdog 打包器（十开关） | `hotdog/build_hotdog.py` |
| LZ4 legacy 压缩器 | `hotdog/lzc.py` |
| cpio/LZ4 解析 | `lmi/extract_ramdisks.py`、`lmi/parse_cpio_only.py` |
| 解密证据链 | `lmi/DECRYPT-FINDINGS.md` |
| 成品镜像 | GitHub Releases 页面 |
