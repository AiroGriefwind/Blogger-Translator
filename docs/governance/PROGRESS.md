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

## 2026-03-15（Streamlit 接入实体缓存与线上映射）

日期时间：2026-03-15  
分支：`feature/streamlit`  
完成项：
- 新增实体精确 key 归一化规则（`entity_zh|entity_en|type`）与 `entity_map_v1` JSON schema。
- verifier 阶段新增“同次运行缓存”能力：同一实体后续段落命中缓存后跳过 LLM。
- verifier 阶段新增“线上映射优先命中”：抽取实体后先查 Firebase Storage 映射，完全一致命中直接复用并跳过 LLM。
- 新增线上映射读写仓储：支持加载映射、精确查询、按核验结果批量 upsert（附证据 URL 与 run_id）。
- Streamlit 侧新增两个开关：`核验前查线上映射库（完全一致）`、`将已确认实体写入线上映射库`。
- UI verifier 展示增加来源状态（如 `db_exact_hit` / `runtime_cache_hit`），并显示写库统计。
验证结果：
- 代码静态检查通过：`py_compile`（`streamlit_app.py`、`pipeline_runner.py`、`verify_stage.py`、`repositories.py`、`firebase_storage_client.py`）。
- verifier 实时日志会记录“DB 命中跳过 LLM / 运行内缓存命中跳过 LLM / 写库完成统计”事件。
- 在 `执行到核验阶段` 模式下也可触发写库，避免必须跑到 storage 阶段。  
阻塞项：
- 当前只实现“完全一致命中”短路，尚未实现“近似匹配候选 + LLM 联合展示”。  
下一步：
- 增加近似匹配策略（英文标准化 + 词形归一 + 阈值），并在 UI 展示候选对照与命中解释。
- 为 entity map 增加并发写入保护（etag/generation）与版本回滚策略。

## 2026-03-16（Verifier 分支：Maynor API Pro 接入与模型切换）

日期时间：2026-03-16  
分支：`feature/verifier`  
完成项：
- 新增 `MAYNOR_*` 兼容读取：`Settings` 与 `PipelineRunner` 现支持 `MAYNOR_API_KEY` / `MAYNOR_BASE_URL` / `MAYNOR_MODEL`，并保留 `SILICONFLOW_*`、`LLM_*` 兼容路径。
- 增加基于域名的 API Key 选择策略：当 `BASE_URL` 指向 `apipro.maynor1024.live` 时优先使用 `MAYNOR_API_KEY`，避免混用旧 key 导致 401。
- Streamlit 侧栏模型切换重构为：`Claude（模型1）`、`Gemini（模型2）`、`Maynor（自定义）`。
- Streamlit 环境检查中的 API Key 可用性判断已纳入 `MAYNOR_API_KEY`。
- 完成 Maynor 网关连通性排查，定位 `gpt-3.5-turbo` 在当前账号分组无可用通道导致 503。
验证结果：
- `smoke_llm.py` 在 Maynor + `gpt-4o-mini` 下可成功返回文本。
- 模型探测结果：`claude-sonnet-4-6-thinking` 可用（200），`gemini-3.1-pro-preview` 当前分组返回 503（No available channels）。
- 配置解析确认命中 `MAYNOR_BASE_URL=https://apipro.maynor1024.live/v1` 与当前选定模型。
阻塞项：
- `gemini-3.1-pro-preview` 在当前 `default` 分组暂无可用通道，需渠道侧开通或切组后再验证。
下一步：
- 使用 `Claude（模型1）` 在 UI 执行“到核验阶段”完成端到端验证。
- 视渠道可用性决定是否加入“Gemini 自动回退 Claude”策略，减少联调中断。

## 2026-03-16（Streamlit：Verifier 卡片交互与单实体录入）

日期时间：2026-03-16  
分支：`feature/streamlit`  
完成项：
- Verifier 页签重构为分组展示：`LLM 返回实体卡片`、`db_exact_hit` 折叠区、`runtime_cache_hit` 折叠区。
- 新增“替换”弹窗：支持输入正确译文、自动检索全文与段落译文命中，并逐条点击确认替换。
- 新增人名简称命中策略：如 `John Wick` 会同时检索 `John`、`Wick`，覆盖后续简称场景。
- 新增“录入”弹窗：预填 LLM 结果但可人工编辑，URL 支持 `+/-` 动态增删多条。
- 新增单实体写库链路：`PipelineRunner.upsert_single_entity_to_online_db` -> `RunRepository.upsert_single_verified_entity`。
- 新增 `verifier_ui_utils` 与对应测试，覆盖实体分组、候选检索与单实体写库校验。
验证结果：
- 测试通过：`pytest -q tests/test_verifier_contract.py tests/test_verifier_ui_utils.py tests/test_repository_entity_map.py`（9 passed）。
- 语法检查通过：`python -m py_compile src/app/streamlit_app.py src/app/verifier_ui_utils.py src/storage/repositories.py`。
- lints 检查无新增错误（涉及 `streamlit_app.py`、`pipeline_runner.py`、`repositories.py` 与新增测试文件）。
阻塞项：
- 本机环境缺少 `gh` 命令（不在 PATH），无法直接命令行创建 PR，只能使用网页创建/更新 PR。
下一步：
- 合并后在真实联网模型环境下跑“执行到核验阶段”，验证替换与录入交互在真实数据下的稳定性。
- 评估是否引入近似匹配候选（非完全一致）以补充当前 `db_exact_hit` 命中策略。

## 2026-03-17（Revisor：分段大纲驱动润色）

日期时间：2026-03-17  
分支：`feature/revisor`  
完成项：
- 新增 `Revision_Outline_Prompt.md` 与 `Revision_Chunk_Prompt.md`，将 revisor 拆为“大纲生成 + 分段润色”两类 prompt。
- 重写 `RevisionStage`：支持 `run(scraped, translated, verifier_output=None)`，按 `<=5` 段切分流程执行“outline -> chunk revise -> assemble”。
- 接入 translator JSON 契约解析（优先读取 `translation.paragraphs_en` / `captions.translated_captions`，失败时回退空行切段）。
- 接入 verifier 输出摘要与实体映射，新增 `revision_meta`（`used_verifier`、`resolved_entities`、`unresolved_entities`、`total_parts`、`degraded_reason`）。
- 在编排层打通 verifier -> revisor 传参：`pipeline_runner` 与 `orchestrator` 均改为传入 `verifier_output`。
- 新增大纲落盘：通过 `save_log(run_id, "revision_outline", ...)` 写入 `runs/{run_id}/logs/revision_outline.json`。
- 更新 mock 输出结构，补齐 `schema_version=2.0`、`revision`、`revision_meta`、`revision_outline` 字段。
- 新增 `tests/test_revision_stage.py`，覆盖“有 verifier 输出”与“无 verifier 降级”路径。
验证结果：
- `python -m py_compile src/revisor/revision_stage.py src/app/pipeline_runner.py src/pipeline/orchestrator.py src/app/mock_pipeline.py tests/test_revision_stage.py` 通过。
- `pytest -q tests/test_revision_stage.py tests/test_verifier_contract.py tests/test_verifier_ui_utils.py tests/test_repository_entity_map.py` 通过（11 passed）。
阻塞项：
- 当前分段边界由大纲模型输出决定；若模型输出不合法会回退固定 5 段切分，语义连贯性仍依赖后续提示词迭代。
- chunk 级 caption 目前默认仅在首段任务改写，复杂多图文场景可进一步细化为按段绑定 caption。
下一步：
- 在真实 LLM + 真实 Storage 环境跑一次端到端，核对 `revision_outline`、`revised`、`docx` 三者一致性。
- 由 `feature/formatter` 评估是否直接消费 `revision.paragraphs_revised_en` / `subtitles_en` 以提升结构化排版能力。

## 2026-03-17（Verifier 稳定性：JSON 修复重试 + 降级可视化）

日期时间：2026-03-17  
分支：`feature/revisor`  
完成项：
- 为 `ParagraphAligner` / `EntityExtractor` / `EntityVerifier` 增加 JSON 解析修复重试：首次解析失败时，自动触发一次“JSON repair”补救请求并重解析。
- 为上述三个组件增强 `_parse_json_object` 容错：在 code fence 清洗后，增加对象截取与 `raw_decode` 兜底提取，降低模型返回前后缀文本造成的解析失败。
- 在 `VerifyStage` 增加流程级降级保护：`aligner` 失败回退按段号一一对齐；`extractor` 失败回退空实体列表；`entity_verifier` 失败回退 `unverified` 并补 `uncertainty_reason`。
- 将降级事件打通到运行日志：新增 `align_failed` / `extract_failed` / `verify_failed` 事件，实时写入 UI 日志流。
- 在 verifier 输出中新增 `summary.degrade_stats`（`aligner_fallbacks` / `extractor_failures` / `verifier_failures`）与 `degradation_notes`。
- Streamlit verifier 页签新增“降级统计”与“核验降级说明”展示，确保降级行为在 UI 与 logs 中都可追踪。
- 使用真实模型 `claude-sonnet-4-6-thinking` 完成端到端实测（含 storage 上传与 docx 产出），验证异常不再导致 verifier 阶段硬失败。
验证结果：
- `pytest -q tests/test_verifier_contract.py tests/test_verifier_ui_utils.py tests/test_revision_stage.py tests/test_repository_entity_map.py` 通过（11 passed）。
- `read_lints` 检查通过（`verify_stage.py`、`streamlit_app.py` 等改动文件无新增 lint）。
- 真实运行成功：`run_id=20260317041414_002904d2`，`verifier_summary` 返回 `total_entities=58 / verified=55 / unresolved=3`，并生成云端 docx。
- 再次真实运行成功：`run_id=20260317044233_d8a9bec3`，`summary.degrade_stats` 字段存在且可读（本次为 0/0/0）。
阻塞项：
- JSON 修复重试会增加额外 LLM 调用成本；在模型波动高峰期可能拉长 verifier 阶段耗时。
- 当前 translator 仍为“全文一次性翻译”，长文情况下依然可能产生超长输出和 JSON 不稳定风险。
下一步：
- 在 translator 分支评估“程序切段翻译 + 分块重试 + 最终拼装”方案，与 revisor 分段策略保持编号对齐。
- 为 verifier 的降级计数增加长期监控指标（按 run_id 聚合），用于观察模型稳定性趋势与回归预警。

## 2026-03-20（Storage/Streamlit：同义词审查、人工合并与待确认改库）

日期时间：2026-03-20  
分支：`feature/firebase-storage`  
完成项：
- verifier 与线上映射交互改为“严格同义词集合命中”路径：移除 `db_alias_hit` 宽松回退，新增 `db_synonym_hit`，并保留精确命中短路。
- 扩展 `entity_map` 记录结构：新增 `zh_aliases`、`en_aliases`、`synonym_reviewed_zh`、`synonym_reviewed_en`、`created_at` 兼容回填。
- 新增 review 持久化：`name_map/review/review_state.json`、`review_results.json`、`pending_changes.json`，支持中断恢复与继续执行。
- 新增同义词审查 prompt 与阶段实现：`Verifier_Synonym_Review_Prompt.md`、`SynonymReviewStage`，按“分类 + 语言 + 批次”执行 LLM 审查。
- Streamlit 数据库区升级为 5 个子页签：`本次核验`、`大模型审核`、`人工合并`、`确认修改`、`线上词库`。
- `线上词库` 卡片新增“修改/删除”动作：修改进入 `update_record` 待确认，删除进入 `delete_record` 待确认，支持“取消删除”回退。
- `确认修改` 页签支持折叠展示待确认动作（合并/修改/删除），仅在“发送到线上数据库”时批量落库并写审计日志。
- 修复人工合并落库行为：合并后删除 source 旧词条，避免线上词库继续显示两条历史记录。
- 处理并解决与 `origin/main` 的冲突文件（`pipeline_runner.py`、`streamlit_app.py`、`revision_stage.py`、`test_repository_entity_map.py`），保留数据库治理能力并兼容主干最新 revisor/translator 链路。
验证结果：
- 语法检查通过：`python -m py_compile src/storage/repositories.py src/app/pipeline_runner.py src/verifier/synonym_review_stage.py src/verifier/verify_stage.py src/app/streamlit_app.py src/revisor/revision_stage.py tests/test_repository_entity_map.py`。
- 单测通过：`pytest -q tests/test_repository_entity_map.py tests/test_revision_stage.py tests/test_translate_stage.py`（12 passed）。
- 追加改动后回归通过：`pytest -q tests/test_repository_entity_map.py`（5 passed）。
- 分支已推送并创建 PR：`feature/firebase-storage` -> `main`（PR #12）；冲突修复后再次推送，PR 进入可继续 review 状态。
阻塞项：
- Streamlit Cloud 部署仍需通过平台 Secrets 注入环境变量与 Firebase 凭据 JSON，当前仓库未内置自动落地 secrets 到凭据文件的部署适配层。
下一步：
- 在目标部署环境补充 Secrets 映射与启动自检（LLM key、bucket、credentials）后执行一次真实端到端联调。
- 视人工运营需求补充“变更 diff 预览”和“按动作类型过滤待确认列表”，提升大批量人工审核效率。

## 记录模板

```
日期时间：
分支：
完成项：
验证结果：
阻塞项：
下一步：
```

