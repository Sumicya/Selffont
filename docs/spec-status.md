# 规范文件状态（查证记录，不是规范本身）

| 项 | 值 |
| --- | --- |
| 指针路径 | `selfs/GLOBAL.md` |
| 实际位置 | **独立仓库 `Sumicya/selfs`，文件 `GLOBAL.md`**（不是本仓的 `selfs/` 目录） |
| 提交 | `e5671d8643eefb3aa5e331eb3baed165513c20ac`（`selfs` 仓 `main` 分支头；blob `84139725344df171dbd8f63b6611c02074b72e34`） |
| 字节 | 9598（`wc -c`） |
| 首行 | `# Sumicya 规范` |
| 中行 | `**6 少**：少是方向，判据是事不是行。行涨而事不涨＝没过。` |
| 末行 | `## 附录 D 许可 …字体按 OFL-1.1…` |
| 采样时刻 | 2026-11-26T04:10:00+00:00 |
| 上一读 | `901b9f57be122eae2d8b210c3c0b7eb85245245c`／9606 B（本轮开头） |

## 更正（§18：黑历史不删，更正另起一条）

**旧结论（2026-11-26 早先写入本文件）**：称 `selfs/GLOBAL.md`「从未在任何一次提交里存在过」，
依据是本仓 `git rev-list --all` 逐个 `cat-file -e` 全部 absent、全盘 `find GLOBAL.md` 无命中。

**更正**：那条查证只查了**本仓**与**本地文件系统**，而指针指的是**另一个仓库**。主人说「重取我
没有删库」是对的——文件一直在 `Sumicya/selfs`。旧结论作废。

**引发的偏差**（本条事故）：我在「规范不存在」的前提下开工，判据只能从历史检讨与自述工具里拼，
于是出现了可查的自证循环——`tools/mark.py` 插 `〔N〕`，我拿它的通过输出当「标号合规」的证据，
而规范要的是 `〖N〗`。

## 现行处置

1. `tools/mark.py` 已改为插 `〖N〗`，解析两种括号（历史稿不判成无标记）。
2. 每轮开头与收尾各取一次 `selfs` 仓 `GLOBAL.md` 的提交号与字节（§2），对不上先对齐。
3. 本文件的读数刷新方式：
   `gh api repos/Sumicya/selfs/commits/main -q .sha` 取提交号，
   `gh api repos/Sumicya/selfs/contents/GLOBAL.md -H 'Accept: application/vnd.github.raw' | wc -c` 取字节。
