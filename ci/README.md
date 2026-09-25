# CI 的源文件

`.github/workflows/` 需要 GitHub 的 `workflows` 权限才能改——本仓库的自动化
令牌没有这个权限，所以工作流文件在这里保留一份**源本**：

- 改 CI：改 `ci/workflows/`，再跑 `python3 tools/sync_ci.py` 同步到
  `.github/workflows/`，然后提交并推送。
- `.github/workflows/build.yml` 已被删除（它指向已不存在的
  `tools/fontslist/urls.txt` / NotoSansPro 合并流程）；同步脚本会删掉它。
- 测试 `tests/test_ci_workflows.py` 保证两边不会悄悄漂移。
