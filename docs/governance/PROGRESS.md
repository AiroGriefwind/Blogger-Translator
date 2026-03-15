# PROGRESS

## 2026-03-12

- 初始化目录结构与 Python 项目骨架。
- 增加 Scraper/Translator/Verifier/Revisor/Formatter/Storage/Orchestrator 基础模块。
- 增加 Streamlit 入口与 smoke scripts。
- 新增治理文档初版。
- 创建 7 个并行 worktree：streamlit / firebase-storage / scraper / translator / verifier / revisor / formatter。
- 爬虫增强：补充 `.article-body` 容器与 JSON-LD 元数据回退，正文段落提取恢复。
- Scraper 优化：Caption 提取增加边界终止（遇到“往下看更多文章”停止），避免串抓下一篇文章。
- Scraper 清洗：正文过滤 `** 博客文章文責自負,不代表本公司立場 **` 免责声明。

## 2026-03-15

日期时间：2026-03-15  
分支：`feature/scraper`（worktree: `wt-scraper`）  
完成项：
- 修复 Caption 越界抓取问题：提取时遇到“往下看更多文章”即停止扫描。
- 清洗正文免责声明：移除 `** 博客文章文責自負,不代表本公司立場 **`。
- 已将修复提交并推送到 `origin/feature/scraper`。
- 已将 `feature/scraper` 快进合并到 `main` 并推送 `origin/main`。  
验证结果：
- 离线重放 `raw_html` 验证通过：`captions` 不再包含下一篇文章内容。
- 免责声明字段已从正文中移除。  
阻塞项：
- 目标站点偶发超时（ReadTimeout），需后续补充重试机制。  
下一步：
- 在 scraper 模块加请求重试与退避策略，提升稳定性。

## 2026-03-15（Streamlit UI）

日期时间：2026-03-15  
分支：`feature/streamlit`  
完成项：
- 重构 Streamlit 为完整分区 UI：参数区、执行区、阶段状态区、结果 Tabs、日志错误区。
- 新增统一执行适配层，支持真实/Mock 混合执行（抓取、LLM、存储可分别切换）。
- 新增 mock 数据管线与失败注入能力，支持无密钥情况下完整演示流程。
- 引入 `session_state` 阶段状态机与阶段输出缓存，支持失败后保留中间结果。
- 增加产物展示与下载入口：`run_id`、本地 docx、云端路径。
验证结果：
- Mock 模式可生成完整阶段输出并产出可下载 docx。
- 真实模式下可按环境变量可用性分步切换真实抓取/真实 LLM/真实存储。
- 导入路径已兼容 `streamlit run src/app/streamlit_app.py` 启动方式。  
阻塞项：
- 标题/Caption 长度控制闭环仍在后端阶段完善，当前 UI 为占位提示。
- 结构化失败日志写回存储尚未全量实现，当前 UI 先展示本地异常与阶段状态。  
下一步：
- 对接后端长度控制真实输出字段并在 UI 增加规则命中可视化。
- 将分阶段错误日志统一落到 Storage `runs/{run_id}/logs/`。

## 2026-03-15（Firebase Storage Logs）

日期时间：2026-03-15  
分支：`feature/firebase-storage`  
完成项：
- 新增运行日志归档接口：`RunRepository.save_run_log(date_key, run_id, payload)`，固定写入 `logs/{yyyymmdd}/{run_id}.json`。
- 在 `PipelineOrchestrator.run()` 接入分阶段状态追踪（`scrape/translate/verify/revise/format/upload`）。
- 统一阶段状态字段：`pending/running/success/failed/skipped`，并记录每步起止时间、耗时与错误类型/消息。
- 使用 `try/except/finally` 保证运行成功或失败都会落一份 run log JSON 到 Storage。
- 更新 `scripts/smoke_storage.py`，改为验证 run log 路径规范 `logs/{yyyymmdd}/{run_id}.json`。  
验证结果：
- 本地静态检查通过（新增文件无 lints）。
- 脚本可执行到凭据前置校验；当凭据路径正确时可直接用于验证日志上传路径规范。  
阻塞项：
- 若 `.env` 中 `GOOGLE_APPLICATION_CREDENTIALS` 不是本机真实路径，Storage 上传会失败。  
下一步：
- 在 Streamlit 阶段状态面板对接该 run log JSON，支持按步骤展示失败原因与耗时。

## 记录模板

```
日期时间：
分支：
完成项：
验证结果：
阻塞项：
下一步：
```

