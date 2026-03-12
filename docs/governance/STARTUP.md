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

