# 热切换方案（不重启换字体）

本文回答主人给的四问，然后是落地到 `module/hotswap.sh` 的具体做法。写在前面的原因：
方案里每一个选择都要能指回一条答案，否则「做到极致」就只是一句形容词。

---

## 一、这个领域的顶尖做法会多做哪些我没提到的动作

换字体「当场生效」在 Android 上不是新问题，做这件事做得最狠的是三类人：**主题商店/换肤引擎**、
**字体管理器（iFont、zFont、FontFix）**、**LSPosed 系字体模块**。他们踩过的坑排出来是：

| 别人多做的一步 | 不做会怎样 | 本方案怎么处理 |
| --- | --- | --- |
| **进 init 的挂载命名空间**（`nsenter -t 1 -m`） | 只在自己的 shell 里看见新字体，zygote 与已起进程仍用旧字件；表现是「命令查着换了、屏幕没变」 | `hotswap.sh` 全部 `mount`/`umount` 前缀 `nsenter -t 1 -m`（`SELFFONT_NSENTER` 可空，沙箱测试用） |
| **挂载点必须能落在只读分区上（overlay / bind）** | `/system` 是只读 ext4/erofs，直接 `mount` 会 `Read-only file system` | 只做 `mount --bind`（VFS 层叠，不需要写源分区），源是模块目录里那份可读写副本 |
| **目标文件必须先存在**（bind 的目标可以是空文件，但不能不存在） | `mount: No such file or directory`，尤其在只读分区上无法 `touch` | `bind_one` 检测目标缺失时，用 `cp` 生成同内容替身（`/data/adb` 侧的空间），再 bind——不依赖 `touch` 一个不存在的系统文件 |
| **卸挂必须反序、且只卸自己挂的** | 顺序卸会 `Device or resource busy`；卸错别人的挂载会把开机 magic mount 一起摘掉 | 状态文件按挂载顺序记账，`off` 反序 `umount`；只处理账上的路径，`mount | grep MFGA` 看到的开机挂载一行不碰 |
| **半路失败要能回到已知状态** | 挂到第 3 个文件失败，模块既不是 on 也不是 off，再点一次 on 变成空操作，永远修不好 | 三态 `on / off / partial`，`partial` 下 `on` 继续补齐、`off` 按账摘干净；沙箱测试里专门有一条 partial 用例 |
| **换完要让进程重读 FontManagerService 的缓存** | Typeface 是进程内缓存，文件换了屏幕不变 | 三级：`cmd font update`（Android 12+，官方接口，返回 0 只代表请求被受理）→ 无则软重启 `system_server`（约 15–20 秒）→ `--reload=app` 只影响新进程 |
| **自检**（不靠肉眼） | 「我以为换了」 | `verify` 逐文件 `sha256sum` 比对系统路径与模块路径，返回 0/1，可脚本化 |

这几条里，前三条是**能不能成功**，后三条是**成功了能不能看出来**。上一版方案只想到「bind 上去」，
这六条就是「顶尖做法」比它多出来的部分。

## 二、最原始底层的材料是什么（不用二手消化过的信息）

- **`/proc/self/mountinfo` 与 init 的挂载表**：真源。读它才知道 `/system/etc` 是独立挂载点还是
  `/system` 的子挂载（子挂载要在**最内层**的挂载点上 bind，否则会被上层挂载遮住）。脚本的
  `mount --bind` 目标取的是**文件**而不是目录，正是为了绕开「子挂载遮父挂载」这一类问题。
- **`mount(8)` / `umount(8)` 与 VFS 语义**：`--bind` 是「把一份 inode 树接到另一个 dentry 上」，
  不是复制。不读这一层，就会想出「复制到 /system 再改权限」这种在只读分区上不可行的办法。
- **`nsenter(1)` 与 PID 1**：Android 上 init 是 PID 1，zygote 与 app 都继承它的挂载命名空间。
  `-t 1 -m` 是进那个命名空间的**唯一**通用入口（`setns` 的 shell 封装）。
- **FontManagerService 的更新入口**：`cmd font` 是 framework 自带的 binder 命令（`system/framework`），
  不是第三方黑科技；`adb shell cmd font --help` 就能看到 `update`。
- **KernelSU 的 magic mount 实现**（`ksu` 的 `overlayfs`/`bindfs` 代码）：不是拿来抄，而是拿来对齐语义——
  运行时 bind 与开机 magic mount 必须是**同构**的（同一批路径、同一优先级），否则 off 之后会留下
  「开机那份还在、运行时那份也还在」的双份状态。

反例（本方案明确不用）：模块安装时把字体写进 `/data/adb/modules/.../system` 再等重启；
用 `resetprop` 改 `ro.font`；用主题引擎 API（厂商私有、AOSP 没有）。这些都不是「运行时换挂载」，
而是「换个时间点重启」。

## 三、具体分析方法与专业工具

1. **`strace -f -e trace=mount,umount2,setns`**：看一条命令到底调了什么。已知 `busybox mount --bind`
   会先 `open_tree`/`move_mount`（新内核）或 `mount(MS_BIND)`（旧内核），两条路径都要能跑。
2. **`ls -l /proc/1/ns/mnt` 与 `readlink`**：确认当前 shell 与 init 是不是同一个命名空间；
   不同才需要 `nsenter`，相同则跳过（省一次 fork，也避免 SELinux 在 `nsenter` 上的拒绝）。
3. **`sha256sum` 逐文件比对**：`verify` 的判据。比 `stat` 可靠——bind mount 后 `stat` 的 inode
   与 mtime 都可能与被挂源相同，但 sha 是内容本身。
4. **`mount | grep` 与 `/proc/mounts` 计数**：`status` 的判据。三个态不是看状态文件有几行，而是看
   **账上有几个目标、`/proc/mounts` 里活着几个**——沙箱测试抓到的第一个真 bug 就在这里
   （状态文件 4 行、实际只挂上 3 个，旧实现报 `on`）。
5. **`sh -n` + 假 `mount`/`umount`**：脚本的正确性不能靠真机试错。`tools/hotswap_test.py` 建假系统根、
   假模块、记账版 `mount`/`umount`，把 `off → on → 幂等 → verify → partial → off → dry-run`
   全部分支跑一遍（18 项），并接进 `build.py --check` 的 `module_hotswap` 一项。
6. **`build.py --check` 的 dry-run 断言**：默认动作（管理器「操作」按钮）必须真的走热切换，且
   `SELFFONT_DRY_RUN=1` 下不得写状态文件。这条断言是拿来防「按钮改回火狐开关」这类回归的。

## 四、除了「我觉得对」，什么外部工具/客观指标能铁证

| 断言 | 铁证 | 现状 |
| --- | --- | --- |
| 挂载真的进了 init 命名空间 | 在**新开的** `su -c` shell 里 `grep MFGA /proc/mounts` 有行；`sha256sum /system/fonts/...` 等于模块内文件 | 未验证（沙箱无 Android） |
| 应用真的重读了字体 | `cmd font update` 返回 0；或软重启后 `logcat -b events | grep -i font` 有重载记录；屏幕上字形变化 | 未验证 |
| off 真的摘干净 | `verify` 返回 1；`/proc/mounts` 里 MFGA 计数回到开机值 | 逻辑已验（沙箱 18 项） |
| 半路失败可恢复 | partial → off 后 `/proc/mounts` 计数归零、`status` 为 off | 沙箱已验证（`SELFFONT_FAKE_FAIL` 注入） |
| 幂等 | 连续两次 `on`，挂载计数不变 | 沙箱已验证 |
| dry-run 不落状态 | `SELFFONT_DRY_RUN=1` 后状态文件不存在或内容不变 | 沙箱已验证 |

沙箱能验的是**记账与分支逻辑**，验不了的是 **SELinux 策略、`nsenter` 权限、FontManagerService 行为、
Typeface 缓存**这四件真机事实。按项目规矩，后者记在 README「未验证项」里，不写成「已验证」。

---

## 落地：脚本怎么工作

```
on   ── 对模块 system/ 下每个文件 ──→ 目标缺失? 建同内容替身 → mount --bind → 记账
     └─ 全部成功 → 状态 on → reload（cmd font update / 软重启 system_server / 只影响新进程）
off  ── 读账 → 反序 umount ──→ 状态 off → reload
status ── targets 总数 vs /proc/mounts 里活着的挂载数 → on / partial / off
verify ── 逐文件 sha256（系统路径 vs 模块路径）→ 0/1
```

使用方式见 README「热切换（不重启）」一节。命令行：

```sh
su -c 'sh /data/adb/modules/MFGA/action.sh'                    # 管理器「操作」按钮 = 切换
su -c 'sh /data/adb/modules/MFGA/action.sh status'
su -c 'sh /data/adb/modules/MFGA/hotswap.sh off --reload=none'
```

边界（写在这里，不等到撞上）：

- 已打开的应用不会自己重画（Typeface 进程内缓存）；除 `--reload=system` 外都要重开那个应用。`cmd font update` 返回 0 不等于屏幕已变——这是各家 ROM 的差异，脚本按「请求被受理」报，不按「已生效」报。
- `off` 只摘这一次运行时的挂载；重启后 magic mount 按模块状态重新叠上。要长期关闭请停用模块。
- 模块若同时被 magic mount 叠着，`off` 后系统回到**开机时那份**（未必是原厂）——这是预期，不是 bug。

## 真机验收清单（未验证，等设备）

```sh
su -c 'sh /data/adb/modules/MFGA/hotswap.sh on'
su -c 'grep -c MFGA /proc/mounts'                       # 与模块内文件数一致
su -c 'sh /data/adb/modules/MFGA/hotswap.sh verify'     # 应为 0
su -c 'sh /data/adb/modules/MFGA/hotswap.sh off'
su -c 'sh /data/adb/modules/MFGA/hotswap.sh verify'     # 应为 1
su -c 'sh /data/adb/modules/MFGA/hotswap.sh status'     # 应为 off
```

四行输出全对，才可以把 README 里的「未验证」改成「已验证」，并把输出存进 `docs/evidence/`。
