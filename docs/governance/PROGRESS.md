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

## 记录模板

```
日期时间：
分支：
完成项：
验证结果：
阻塞项：
下一步：
```

