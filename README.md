# skyward-device-ports

为 [Skyward](https://github.com/kirklin/skyward)（一个 Rust 编写的 Android recovery）
适配上游未支持设备的移植笔记、构建管线与补丁。

三台设备已完成完整适配，均经真机验证：

| 设备 | 代号 | 槽位 | 底座 | 结果 |
|---|---|---|---|---|
| 小米 Redmi K30 Pro | `lmi` | A-only | TWRP 3.7.1 ramdisk（sekaiacg）+ MIUI 官方 ROM 内核 | 完整运行：分区挂载、挂载页、MTP、整块 /data 备份 |
| 一加 7T Pro | `hotdog` | A/B | LineageOS recovery ramdisk + OxygenOS 11 原厂内核 | 完整运行（含触控） |
| 小米 8 | `dipper` | A-only（纯物理分区） | LineageOS recovery ramdisk（自提 fstab） | 完整运行（MTP 待修） |

## 为什么 lmi 的底座是 TWRP 线，而不是 LineageOS

K30 Pro 是 MIUI 时代机型，内核↔dtbo↔ramdisk 三件套必须来自同一个世界。
真机实测结论：

| 底座来源 | 实测结果 |
|---|---|
| MIUI 原厂 | 可启动（手机日常 ROM），但其 recovery ramdisk 是 MIUI 自己的 |
| LineageOS 官方内核 + dtbo + stock recovery ramdisk | **init 前 panic**——我们的第一次尝试，过程见 `lmi/RE-DIFF-1.2-vs-mine.md` |
| TWRP 3.7.1（sekaiacg 构建，MIUI 官方 ROM 内核） | 可启动——**选为底座** |

发布的镜像保留了 TWRP 线的内核/dtbo/ramdisk，只把 recovery 程序替换为
打补丁的 Skyward 0.2.0。recovery 分区与你刷的 ROM 相互独立，手机继续用
MIUI 或 LineageOS 均不受影响。同一 TWRP 底座在 recovery 下也无法解密
/data（QTI TEE 的墙，见 `lmi/DECRYPT-FINDINGS.md`），因此镜像提供的是
整块加密态 /data 备份。

## 仓库里没有可刷镜像

本仓库所有内容都是方法、脚本、补丁与配置——供你为自己的设备重建。

**成品镜像**在 [Releases 页面](https://github.com/Robincheng34/skyward-device-ports/releases)：
[`v0.2.0-lmi`](https://github.com/Robincheng34/skyward-device-ports/releases/tag/v0.2.0-lmi) ·
[`v0.2.0-hotdog`](https://github.com/Robincheng34/skyward-device-ports/releases/tag/v0.2.0-hotdog)。
镜像内的内核与 ramdisk 底座均为第三方 GPL 构建——署名见 Release 说明；
刷入前请确认你设备 recovery 分区的大小。

## 目录结构

```
METHODOLOGY.md                 完整方法论，从这里开始读
lmi/                           A-only 的故事
  RE-DIFF-1.2-vs-mine.md       逆向两份镜像，找出为何一份能启动
  A-ONLY-PORT.md               从启动路径中移除 A/B 假设
  DECRYPT-FINDINGS.md          为什么 FBE 解密在此设备上不可能（TEE），完整证据链
  rebuild_final.py             重打包：替换 ramdisk、重算 AVB 哈希 footer
  patch_cmdline.py             修改 boot cmdline、重封 AVB
  extract_ramdisks.py          LZ4-legacy + gzip ramdisk 解包器（纯 Python）
  parse_cpio_only.py           newc cpio 解析器
  compare_imgs.py              boot 镜像对比
  device_lmi_020.toml          真机调校的设备配置
hotdog/                        A/B 的故事
  HOTDOG-PORT.md               九个坑：从 ABL 脾气到触控三层
  build_hotdog.py              十开关构建管线，支持单变量对照
  lzc.py                       LZ4 legacy 帧压缩器（带往返自检）
  device.toml                  真机调校的设备配置
dipper/                        纯物理分区 A-only 的故事
  DIPPER-PORT.md               九个坑：DRM panic、fstab、面板、s2idle
  build_dipper.py              构建器（含 fstab/MTP 补丁）
  device.toml / fstab.qcom     dipper 设备配置与分区表
  patch_drm.py                 drm 0.15 crtc_id=0 panic 的本地补丁
patches/patched-src/           补丁后的源码文件（GPLv3，见下）
```

## 补丁摘要

全部基于 skyward 0.2.0：

- `main.rs`——槽位可选的启动路径（`prepare_a_only`）、固件回退容错、
  `mounted` 分区列表尽力而为
- `skyward-vab/partitions.rs`——无槽位的 super 映射
  （`mount_partitions_slotless`）、挂载页的无槽位挂载/卸载
- `skyward-info/lib.rs`——无槽位时的属性来源
- `ui.rs`——面板节点在设备树第一层的查找、无亮度标定面板的回退
- `input.rs`——只报 `INPUT_PROP_POINTER` 不报 `INPUT_PROP_DIRECT`
  的触摸面板（一加）也能被选中

## 许可

Skyward 为 GPLv3，这些补丁遵循同一许可。两份 `device.toml` 与文档是事实
记录，随意使用。仓库不含任何内核、固件或字体二进制——底座镜像请自备。
