# 手工推送 CI 工作流

本仓库的自动化令牌没有 GitHub 的 `workflows` 权限，改不了
`.github/workflows/`。工作流源本在 `ci/workflows/`，用你在 Termux 里的账号
同步并推送即可（一次就好）：

```sh
cd ~/Selffont
git pull                                   # 拿到最新提交
python3 tools/sync_ci.py                   # 把 ci/workflows 复制到 .github/workflows
git add -A .github
git commit -m "CI: 同步工作流源本（build-module 跑完整链并改名为 Selffont-Maru，删除遗留 build.yml）"
git push origin arena/01a0d237-selffont
```

`sync_ci.py` 会**删除** `.github/workflows/build.yml`——它触发的是已经不存在
的 `tools/fontslist/urls.txt`（NotoSansPro 合并流程），留着只会在下次推送时
报错。之后 `python3 tools/sync_ci.py --check` 应当无输出。
