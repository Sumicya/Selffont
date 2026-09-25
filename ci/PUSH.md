# 手工推送（Termux）

本仓库的自动化令牌没有 GitHub 的 `workflows` 权限，改不了
`.github/workflows/`。工作流源本在 `ci/workflows/`，用你自己的账号同步并推
一次即可。**下面整块可以直接贴进 Termux**：

```sh
cd ~/Selffont
git fetch origin
git checkout arena/01a0d237-selffont
git pull --rebase origin arena/01a0d237-selffont

python3 tools/sync_ci.py                   # ci/workflows -> .github/workflows
git add -A .github
git commit -m "CI: 同步工作流源本（build-module 跑完整链、产物按 Selffont-Maru 命名、删除遗留 build.yml）"
git push origin arena/01a0d237-selffont
```

`sync_ci.py` 会**删除** `.github/workflows/build.yml`：它触发的是已经不存在
的 `tools/fontslist/urls.txt`（NotoSansPro 合并流程），留着只会在下次推送时
报错。之后 `python3 tools/sync_ci.py --check` 应当无输出——`tests/test_ci_workflows.py`
会一直盯着这件事，所以**在推送工作流之前 CI 是红的，这是有意为之**。

## 看图

GitHub 的提交/分支 diff 对 PNG 只显示 "Binary file not shown"，要看图得点进
文件本身，或者直接在手机上打开：

```sh
# 1) 直接从仓库里取出图片并用手机看图应用打开（需要 termux-api / termux-open）
git show origin/arena/01a0d237-selffont:docs/images/reference-borrowing.png > ~/reference-borrowing.png
termux-open ~/reference-borrowing.png

git show origin/arena/01a0d237-selffont:docs/images/simplified-extension.png > ~/simplified-extension.png
termux-open ~/simplified-extension.png

# 2) 或者确认它们确实在远端（有字节数就说明图在里面）
git ls-tree -r --long origin/arena/01a0d237-selffont -- docs/images
```

浏览器里能直接渲染的地方：

- PR 的 **Files changed**：<https://github.com/Sumicya/Selffont/pull/1/files>（PNG 有预览）
- 单张图：<https://github.com/Sumicya/Selffont/blob/arena/01a0d237-selffont/docs/images/reference-borrowing.png>
- 嵌了图的文档：[`docs/simplified-extension.md`](../docs/simplified-extension.md)（相对链接，点进去就显示）

两张图都由 `tools/make_extension_sheet.py` 生成，不手画：
`docs/images/simplified-extension.png`（派生字五个字重）与
`docs/images/reference-borrowing.png`（左原生 / 中自家规则 / 右参考借入）。
