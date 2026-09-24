# 更新日志

## v2.0.0（2026-09-24）

**激进重写：换基准字体、删掉上一轮的批量字形改写、把单一真源补齐。**

- **字体路线**：文渊圆体（可变）→ **Zen Maru Gothic**（固定提交 `553c872`，OFL-1.1）五个静态面，构建期改名为派生家族 `Selffont Maru`（`SelffontMaru-{Light,Regular,Medium,Bold,Black}.ttf`）。Android 100–900 就近映射（600→700、800→900，平局取粗），斜体由平台合成，不伪造 `fvar`。
- **手写笔画回到"显式点 patch"**：删除整字库几何改写及其全部工具（`tools/smooth_strokes.py`、批量模式、GB2312 扫描、照片描摹）。`tools/edit_font.py` 只接受逐字、逐点的 patch，拒绝复合字形、带 hinting 的字形、越界/重复/空改动，并在发布前断言**只有被点名的字形变了**。契约测试锁住 CLI 面（只允许 `--prepared/--patches/--output/--report`）。
- **缺字如实标注**：新增 `tools/glyph_audit.py` + `config/glyph-targets.json`（作者手写练习字表）。对 44 个文本目标的审计：**30 可改 / 14 缺字**（简体专用形，日文基准字体没有）。缺字不再被混进"改笔画"里假装完成。
- **审阅页**：新增 `tools/preview.py`，用真实 TTF 渲染五个面与目标字表，可在浏览器直接看改动（`--serve`），也可出 PNG（`--render`）；有 patch 报告时页面额外显示**改前/改后**对照（未改动的基础面从 `/baseline/` 提供）。
- **首个真实 patch（样例）**：`config/glyph-patches/Regular.json` 按"去钩 + 圆头"改 `力`，由 `tools/edit_font.py` 校验并通过"只有被点名的字形变了"。其余 29 个可改字与其余四个面仍未改——样例存在是为了让作者照着改，不是为了假装笔画已写完。
- **简体扩展（自己做）**：新增 `tools/extend_font.py`，用 Zen Maru 自己的轮廓和笔画派生简体字（贝 页 见 马 鸟 乌 岛 门 员 维 陈 护 进 迁 赵 飞，附赠 东），规则按角色而不是轮廓序号书写，所以五个字重通用；保存前断言原有字形逐字节不变、cmap 只增派生码点；拼不出来的字重（Bold/Black 的 飞）明示跳过。镜像会反转绕向，所以 `Contour.reversed()` 把镜像副本倒回来；选空的部件按契约报错而不是产出一个缺胳膊的字。新增 25 项契约测试。
- **笔画库**：这个字体把单笔画也画成了字（`一 丨 亅 丿 丶` 与片假名 `ニ 冫`），简体 东 与 陈 的右件就是用这些笔画按目标宽度重新排布的——因为笔画粗细不随部件宽窄变化，等比缩小会让笔画变细、和旁边的部件不搭。新增 `tools/make_extension_sheet.py` 重画文档里的对照图。
- **组件借用者可见**：patch 改到的字形若被其他字形当组件引用，`edit_font.py` 会在 stderr 与报告 `componentUsers` 里点名（不静默连带改动）。
- **单一真源**：模块内生成 `font.conf`（五个面名 + 可见性文件），`customize.sh`/`diagnose.sh`/`device_state.sh` 只读它，不再硬编码字体名；`config/font-source.json` 与 `FontIdentity.kt` 由契约测试对齐。
- **删死重**：`tools/otfccbuild`、`tools/otfccdump`、`tools/merge-otd`（约 2.6 MB 预编译二进制）、`NotoSansPro` 合并工作流 `build.yml`、`tools/fontslist/`、`script/remove_emoji_overlap.py`、休眠的 `BadgeDrawObserver`/`BadgeSamplePolicy`/`GlyphCoverageProbe` 及其测试。
- **现代化**：Python 3.11 + fontTools 4.65 + ruff 全绿；JDK 21 / Gradle 9.5.0 / AGP 9.3.0 / SDK 36 / 全 Kotlin；node 24。
- **原生化**：只用 framework `Typeface` 工厂与 `fonts.xml`；Hook 面由纯签名谓词 `HookTarget` 决定并有单元测试。
- **文档**：631 行逐日流水账的 `docs/validation.md` 压缩成验收清单（历史证据留在 Git 历史）；新增 `docs/font-editing.md`；重写 README/架构/换字体文档。LICENSES 换成 Zen Maru OFL 归属。
- **验证**：100 项 Python 契约测试 + 3 项 node 测试 + ruff 全绿；真实五面完成"下载→校验→改名→度量归一→打包"演练（合成 base ZIP）。**真机安装、网页绘制、紧凑槽位均为 `NOT_TESTED`。**

## v1.4.0（2026-09-12，历史路线）

面向 Android 16 / Oplus / KernelSU 的**文渊圆体**系统字体模块 + 只读诊断 APK；度量归一修复通知角标数字偏低/切底（经用户真机确认）；Gecko 启动首选项注入使 Firefox 正文统一为文渊（用户确认）；火狐 Unicode 15.1/16 新 emoji 豆腐块经 A/B 证明属 Gecko 后端限制。该路线的字形、哈希与设备证据见 Git 历史。

---

以下是上游 MFGA 的历史记录，不是当前功能清单。

CN

17.0.1.08-31-alpha2(1717180003)
 - 1.适配HyperOS4
 - 2.同步/新增部分字体，调整部分私用区符号颜色
 - 3*.新增Xposed版本MFGA覆盖一些内置了字体的应用
 - 4.增加了对部分Unicode18彩色Emoji的初步支持(早期预览版)

17.0.0.06-27-alpha(1717180001)
 - 1.同步Roboto到3.0.16(SU)
 - 2.WebUI新增主字体上色，需支持COLRv0，Android10及以上
 - 3.调整主字体中部分组合类符号，修复缺失、在高安卓版本显示异常的情况

Telegram channel: https://t.me/AndroidCoreLayer
Power by: Yiyunlengyu(酷安@Numbersf)
