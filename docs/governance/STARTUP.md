# STARTUP

## 通用开场白模板（给每个 worktree 的 LLM）

你现在位于分支：`<branch_name>`。  
开始编码前，完整阅读：
- `docs/governance/PRD.md`
- `docs/governance/TECHSTACK.md`
- `docs/governance/STRUCTURE.md`
- `docs/governance/IMPLEMENTATION_PLAN.md`
- `docs/governance/PROGRESS.md`
- `docs/governance/STARTUP.md`

完成后请回报：
1. 你负责的分支职责
2. 你准备修改的文件
3. 你将如何验证

严禁修改不属于本分支职责的模块；如需跨模块修改，先说明理由并记录到 `PROGRESS.md`。

## 分支专用提醒

- `feature/scraper`：只负责抓取与结构化解析。
- `feature/translator`：只负责 LLM 首翻、提示词注入。
- `feature/verifier`：只负责人名/实体核对清单。
- `feature/revisor`：只负责二次润色与标题/Caption裁剪。
- `feature/formatter`：只负责 docx 样式输出。
- `feature/firebase-storage`：只负责 Storage 归档能力。
- `feature/streamlit`：只负责 UI 和编排接入。

## 分支推送 -> PR -> 合并 -> 全分支同步（标准操作手册）

以下步骤默认在仓库根目录执行，PowerShell 命令可直接复制。

### 0) 前置检查（必须）

1. 确认当前分支不是 detached HEAD：
   - `git status -sb`
   - `git branch --show-current`
2. 若显示 `HEAD (no branch)`，先切回本地分支（不要在 `origin/*` 上直接开发）：
   - `git checkout feature/translator`（按需替换分支名）
3. 拉取远端最新信息：
   - `git fetch origin`

### 1) 在当前 feature 分支提交本次改动

1. 查看改动：
   - `git status -sb`
   - `git diff`
2. 运行必要验证（示例）：
   - `$env:PYTHONPATH='src'; python "scripts/smoke_llm.py"`
   - `$env:PYTHONPATH='src'; python "scripts/smoke_translate_article.py"`
3. 提交：
   - `git add .`
   - `git commit -m "feat(translator): ..."`

### 2) 推送当前分支到远端

1. 首次推送（建立 upstream）：
   - `git push -u origin feature/translator`
2. 非首次推送：
   - `git push`

### 3) 使用 gh 创建 PR

1. 确认 gh 已登录：
   - `gh auth status`
2. 创建 PR（示例：从 `feature/translator` 合并到 `main`）：
   - `gh pr create --base main --head feature/translator --title "feat(translator): connect SiliconFlow and smoke tests" --body "## Summary\n- ...\n\n## Test Plan\n- [x] smoke_llm\n- [x] smoke_translate_article"`
3. 查看 PR：
   - `gh pr view --web`

### 4) 合并 PR 到 main

1. 在网页上完成 review 后合并，或用 gh（有权限时）：
   - `gh pr merge --merge --delete-branch`
2. 合并完成后刷新远端引用：
   - `git fetch origin`
3. 确认 `origin/main` 已前进：
   - `git log --oneline --decorate -5 origin/main`

### 5) 更新本地 main

1. 切到本地 main：
   - `git checkout main`
2. 同步远端 main：
   - `git pull --ff-only origin main`

### 6) 让其他功能分支拉取最新 main（每个分支都执行）

1. 切到目标本地分支（示例 `feature/verifier`）：
   - `git checkout feature/verifier`
2. 合并最新主干：
   - `git merge origin/main`
3. 解决冲突（若有）并提交：
   - `git add .`
   - `git commit`
4. 推送同步后的分支：
   - `git push`

### 7) 快速批量同步模板（手动循环执行）

按顺序对以下分支重复第 6 步：
- `feature/scraper`
- `feature/translator`
- `feature/verifier`
- `feature/revisor`
- `feature/formatter`
- `feature/firebase-storage`
- `feature/streamlit`

### 8) 常见错误与纠正

1. 错误：`git checkout origin/feature/xxx` 后直接 merge/commit。  
   影响：进入 detached HEAD，提交和合并不会落到本地分支。  
   修正：`git checkout feature/xxx` 再执行 `git merge origin/main`。
2. 错误：未 `git fetch origin` 就 merge。  
   影响：可能基于旧的 `origin/main`。  
   修正：先 fetch，再 merge。

