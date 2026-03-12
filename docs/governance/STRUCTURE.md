# STRUCTURE

```text
Blogger Translator/
  src/
    app/streamlit_app.py
    pipeline/orchestrator.py
    scraper/{bastille_scraper.py, html_structure.json}
    translator/{siliconflow_client.py, translate_stage.py}
    verifier/name_extractor.py
    revisor/revision_stage.py
    formatter/docx_formatter.py
    storage/{firebase_storage_client.py, repositories.py}
    config/{settings.py, prompts/*}
  scripts/
  tests/
  docs/governance/
  README.md
  requirements.txt
  pyproject.toml
```

## 约束

- 提示词统一放在 `src/config/prompts/`。
- 运行编排统一由 `src/pipeline/orchestrator.py` 进入。
- 每个功能分支都维护并更新 `docs/governance/*`。

## Worktree 目录约定

- `../wt-streamlit`
- `../wt-firebase-storage`
- `../wt-scraper`
- `../wt-translator`
- `../wt-verifier`
- `../wt-revisor`
- `../wt-formatter`

