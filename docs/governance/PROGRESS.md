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

## 记录模板

```
日期时间：
分支：
完成项：
验证结果：
阻塞项：
下一步：
```

