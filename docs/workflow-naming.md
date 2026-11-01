# 命名方案

本页只解决一件事：**同一个仓里产出的东西，名字怎么起，才能一眼看出「是什么、哪一版、能不能刷」**。
全部条目都是提议，改动落在 `.github/workflows/` 与 `.github/scripts/cleanup.py`；哪一条还没落地，条目末尾标「未落地」。

## 一、现在为什么乱

四个 workflow 产出五种名字：

| workflow | 现在产出的名字 | 问题 |
| --- | --- | --- |
| `build.yml` | `Selffont-26.11.1.12.286` | 唯一合规的一个 |
| `build.yml` | `Selffont-preview-<40 位提交 SHA>` | 带 SHA，跟版本无关，看不出新旧 |
| `build.yml` | `Selffont-preview-sha256-<64 位十六进制>` | 64 位哈希当名字，人没法读 |
| `mother.yml` | `Selffont-mother-97e9dd4-7` | 前缀和主包相同，段数不同 |
| `probe.yml` | `SelfFontProbe-dev-1` | 大小写不同（`SelfFont` vs `Selffont`）、没有日期、没有序号，每次覆盖同一个名字 |

乱在三处，都不是「不好看」：

1. **同名不同物**：`Selffont-` 前缀下面同时挂着能刷的模块包、母版对照包、预览件、哈希文件。下载的人只能靠段数猜。
2. **名里没有「能不能刷」**：64 位哈希和 226 B 的 `SHA256SUMS.txt` 跟 152 MB 的模块包平级排队，清理脚本也把它们当同等对象。
3. **名字不跟内容走**：`SelfFontProbe-dev-1` 昨天和今天指向不同的 APK，`Selffont-preview-<SHA>` 换了提交就换名字——两头都不好用：前者查不到对应哪个提交，后者攒出一堆。

## 二、命名规则（提议）

**格式**：`<项目>-<种类>-<版本或来源>`

- `<项目>`：固定 `Selffont`，大小写全仓统一（现在 `SelfFontProbe` 是唯一一个例外）。
- `<种类>`：只有四种，小写，短横分隔：

| 种类 | 是什么 | 能刷吗 |
| --- | --- | --- |
| `full` | 模块包，含二创汉字字库 | **能**，日常用 |
| `mother` | 母版基准包，只用于对照 | **能**，但字形不是我们的 |
| `preview` | 改字形时的小包，只含被改的那几个字 | 能刷，但**只用于看，不用于用** |
| `probe` | LSPosed 探针 APK | 不是字体包，装法不同 |

- `<版本或来源>`：能出正式版本号的（`full`、`mother`）写规范五段版本；出自提交的（`preview`、`probe`）写**短 SHA 前 8 位**。

于是名字长这样：

| 种类 | 名字 | 例子 |
| --- | --- | --- |
| full | `Selffont-full-<yy.m.d.当日序号.总序号>` | `Selffont-full-26.11.2.1.289` |
| mother | `Selffont-mother-<母版短 SHA>-<序号>` | `Selffont-mother-97e9dd4-7` |
| preview | `Selffont-preview-<提交短 SHA 8 位>` | `Selffont-preview-24f4b7a6` |
| probe | `Selffont-probe-<提交短 SHA 8 位>` | `Selffont-probe-1a2b3c4d` |

四条配套规则：

1. **哈希不进 artifact 名**。`SHA256SUMS.txt` 放进包内、贴进 run 摘要（`$GITHUB_STEP_SUMMARY`），不单独占一个 artifact 名额——它只有 226 B，占掉五分之一的名额。
2. **短 SHA 取 8 位**，不取 40 位。完整 SHA 在 run 页面本来就写着，名字里重复一遍只让手机屏幕上一行放不下。
3. **一个名字只对应一个对象**。`probe` 不再用固定名 `dev-1` 覆盖，改跟提交走。
4. **清理脚本不看名字**。规范六·3 的判据是「按 `created_at` 留最新 5 个」，跟名字无关；名字的作用只给人看，不给脚本猜。

## 三、落地状态

| 改动 | 文件 | 状态 |
| --- | --- | --- |
| `probe` 产物名从固定 `SelfFontProbe-dev-1` 改为 `Selffont-probe-<提交短 SHA 8 位>` | `.github/workflows/probe.yml` | **已落地**（本轮，待一次 probe 运行确认名字） |
| `probe` 不再自动建 Release、不再自行 `release upload` | `.github/workflows/probe.yml` | **已落地**（本轮） |
| 所有 action 升到 node24 那一代 | `build.yml`、`mother.yml`、`probe.yml` | **已落地**（本轮，见第四节） |
| 清理脚本不再按名字前缀判 tag 归属 | `.github/scripts/cleanup.py` | **已落地**（本轮） |
| `full` 主包名加 `-full-` 段 | `build.py` | 未落地 |
| `preview` 名从 40 位 SHA 改 8 位 | `.github/workflows/build.yml` | 未落地 |
| 哈希从独立 artifact 挪进包内与 run 摘要 | `.github/workflows/build.yml` | 未落地 |

后三条要动 `build.py` 与产物命名，会连带影响版本号解析（`name.split("-")[1]`）与设备端覆盖安装的版本比较，得单独一轮改、单独一轮验证，不在本轮夹带。

## 四、action 版本（本轮实查）

逐个取 `action.yml` 里的 `using:` 字段，不看日期猜：

| action | 用在哪 | 运行时 | 状态 |
| --- | --- | --- | --- |
| `actions/checkout@v7` | 全部 | node24 | 现行 |
| `actions/setup-python@v7` | 全部 | node24 | 现行 |
| `actions/upload-artifact@v7` | `build.yml`、`mother.yml`、`probe.yml` | node24 | 现行 |
| `actions/cache@v5` | `build.yml`、`mother.yml` | node24 | 现行（本轮从 v4 升上来） |
| `actions/setup-java@v5` | `probe.yml` | node24 | 现行 |
| `gradle/actions/setup-gradle@v4` | `probe.yml` | composite（自身不占 node 运行时） | 现行 |

升 `cache@v4 → v5` 的理由只有一条：v4 的 `action.yml` 写的是 `using: 'node20'`，v5 写的是 `node24`。同仓其余 action 全在 node24，只有这两处还跑在上一代上。

复算：

```sh
for a in actions/cache actions/upload-artifact actions/checkout; do
  gh api "repos/$a/contents/action.yml?ref=v5" --jq '.content' | base64 -d | grep 'using:'
done
```
