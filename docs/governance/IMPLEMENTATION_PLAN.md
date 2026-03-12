# IMPLEMENTATION_PLAN

## 强制阅读条款（必须）

任何 LLM 在本仓库开始编码前，必须完整阅读以下文件：

1. `docs/governance/PRD.md`
2. `docs/governance/TECHSTACK.md`
3. `docs/governance/STRUCTURE.md`
4. `docs/governance/STARTUP.md`
5. `docs/governance/PROGRESS.md`
6. 本文件 `docs/governance/IMPLEMENTATION_PLAN.md`

若未阅读完毕，不得开始编码。

## 推进阶段

- Phase A：骨架初始化 + 治理文档
- Phase B：Scraper（结构化抓取）
- Phase C：Translator + Verifier
- Phase D：Revisor + 长度控制
- Phase E：Formatter + Streamlit 串联
- Phase F：Storage 归档 + 分支同步 + push

## 分支职责

- `feature/scraper`：爬虫及结构配置
- `feature/translator`：首轮翻译
- `feature/verifier`：人名核对问题生成
- `feature/revisor`：润色与标题/Caption处理
- `feature/formatter`：docx排版
- `feature/firebase-storage`：存储归档
- `feature/streamlit`：界面与编排

