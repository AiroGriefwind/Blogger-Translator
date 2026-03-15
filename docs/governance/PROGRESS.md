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

## 2026-03-15（Translator 分支同步与 CLI 环境）

日期时间：2026-03-15  
分支：`feature/translator`  
完成项：
- 安装并登录 GitHub CLI（`gh version 2.88.1`，账号 `AiroGriefwind`）。
- 拉取远端最新分支信息（`git fetch origin`）。
- 将 `origin/main` 最新进度（含 Streamlit UI 合并结果）快进合并到 `feature/translator`。  
验证结果：
- `feature/translator` 已包含 `src/app/pipeline_runner.py`、`src/app/ui_state.py` 等来自 `main` 的新增文件。
- 当前分支环境已具备后续执行 `gh pr create` 的 CLI 前置条件。  
阻塞项：
- 过程中曾进入 detached HEAD（`checkout origin/feature/translator`），需确保后续在本地分支上执行 merge/commit。  
下一步：
- 在 `feature/translator` 继续完成 LLM 接通与 smoke 测试。
- 完成后推送分支并创建 PR（base: `main`，head: `feature/translator`）。

## 2026-03-15（Translator 超时排查与流程文档）

日期时间：2026-03-15  
分支：`feature/translator`  
完成项：
- 在 `STARTUP.md` 增补“推送分支 -> 创建 PR -> 合并 main -> 全分支同步”的标准命令手册。
- LLM 配置新增 `SILICONFLOW_TEMPERATURE`、`SILICONFLOW_TIMEOUT_SECONDS`、`SILICONFLOW_MAX_RETRIES`，并兼容 `LLM_*` 别名。
- `SiliconFlowClient` 增加超时/网络抖动重试（含简单退避），降低偶发 `ReadTimeout` 导致的整段失败。
- `orchestrator`、`smoke_llm`、`smoke_translate_article` 接入上述可配置超时与重试参数。
验证结果：
- 通过日志确认 `smoke_translate_article` 报错点位于 SiliconFlow 请求读超时（`read timeout=120`），并非抓取失败。
- 抓取输入规模可控（当前样例正文约 2328 字符，段落 18，非异常大输入）。  
阻塞项：
- `Pro/deepseek-ai/DeepSeek-R1` 在复杂翻译任务下仍可能出现长延迟；需结合模型与超时参数联合调优。  
下一步：
- 优先尝试 `LLM_MODEL_B` 或提高 timeout（如 180-240）并观察稳定性。
- 若仍抖动，考虑在 smoke 脚本加入“仅前 N 段”快速联调模式。

## 2026-03-15（UI 接入真实抓取 + 翻译）

日期时间：2026-03-15  
分支：`feature/translator`  
完成项：
- Streamlit 执行区新增“执行到翻译阶段”按钮，支持 UI 下先跑真实抓取与翻译，再决定是否继续后续阶段。
- PipelineRunner 的真实 LLM 参数接入超时/重试/温度配置，并兼容 `SILICONFLOW_*` 与 `LLM_*` 两套环境变量。
- 统一环境检查提示：UI 中 API Key 检查改为兼容 `SILICONFLOW_API_KEY` 或 `LLM_API_KEY`。
- SiliconFlow 客户端增加输出清洗：移除 `<think>...</think>`，避免推理痕迹污染翻译结果展示。
验证结果：
- 终端实测 `smoke_translate_article.py` 在 Distill 模型 + 提高 timeout 时可返回翻译文本。
- UI 侧具备“仅抓取”“执行到翻译”“全流程”三种执行路径。  
阻塞项：
- “全流程真实模式”仍可能受 revisor 阶段模型时延影响，建议先以“执行到翻译阶段”联调。  
下一步：
- 在 UI 增加可选模型切换（如从 sidebar 直接覆盖模型）与“仅前 N 段翻译”开关，进一步提升联调稳定性。

## 2026-03-15（Prompt 职责拆分与 Verifier 联动）

日期时间：2026-03-15  
分支：`feature/translator`  
完成项：
- 重构 `Translate_Bot_Prompt`：移除核对列表职责，保留翻译与 captions 的结构化 JSON 输出。
- 重构 `Revision_Bot_Prompt`：移除“英中交错排列”硬约束，改为保持英文段落一对一对齐输出。
- 新增 `Verifier_Interleave_Paragraphs_Prompt`：专用于原文/译文段落配对并输出 `paragraph_pairs` JSON。
- 新增 `Verifier_Name_Check_Prompt`：专用于单段实体抽取与在线核验，要求返回可点击证据 URL 与证据定位说明。
- 明确 verifier 接入顺序：先段落交错，再按段抽实体，再按实体逐次核验并回传 UI。  
验证结果：
- Prompt 职责边界清晰：翻译/润色不再承担核验任务，核验链路可在 verifier 分支并行扩展。
- 新增两个 verifier prompt 均给出严格 JSON 契约，便于后续程序解析与展示。  
阻塞项：
- 实体在线核验质量仍依赖模型是否具备联网检索能力与来源可达性。  
下一步：
- 由 verifier 分支接入新 prompt，完成“逐段实体核验结果”写回 UI 的流程实现。

## 2026-03-15（Verifier 全联网核验接入）

日期时间：2026-03-15  
分支：`feature/verifier`  
完成项：
- 新增 `Verifier_Entity_Verify_Prompt`，将“单实体验证”从段落抽取中拆分，要求返回可点击 URL 与证据说明。
- 重构 `Verifier_Name_Check_Prompt` 为“段落级实体抽取 + 联网证据收集”契约，避免与验证职责混淆。
- 新增 `ParagraphAligner` / `EntityExtractor` / `EntityVerifier` / `VerifyStage` 四个 verifier 组件，形成“段落对齐 -> 实体抽取 -> 逐实体验证”的串联流程。
- `pipeline_runner` 与 `orchestrator` 的 verify 阶段改为调用 `VerifyStage`，并落盘 `verifier_entities` 结构化日志。
- Streamlit 的 verifier 页签改为按“段落 -> 实体 -> 证据 URL”展示，同时保留 `name_questions` 兼容字段。
- 增加 verifier 契约测试，覆盖 URL 门禁降级与翻译 JSON 解析兜底逻辑。
验证结果：
- 代码层已具备“抽取也走 LLM、验证逐实体走 LLM”的双阶段能力。
- 若验证结果缺失有效 URL，系统会自动将 `is_verified` 降级为 `false` 并补充不确定性说明。
- UI 可直接查看每个实体的证据链接与证据注释。  
阻塞项：
- “模型是否真实联网搜索”依赖上游模型能力与服务端配置，当前代码只能做输出证据门禁，无法强制模型侧联网实现细节。  
下一步：
- 在真实联网模型环境下执行端到端联调，验证 Wikipedia 优先策略与 URL 可达性。
- 按运行数据继续收紧证据域名白名单和质量规则（如来源可信度分级）。

## 记录模板

```
日期时间：
分支：
完成项：
验证结果：
阻塞项：
下一步：
```

