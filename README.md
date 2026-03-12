# Blogger Translator

从巴士的报文章 URL 出发，自动完成抓取、翻译、润色、标题/Caption 长度控制、`docx` 排版导出，并归档到 Firebase Storage。

## Quick Start

1. 创建虚拟环境并安装依赖：
   - `python -m venv .venv`
   - `.venv\\Scripts\\activate`
   - `pip install -r requirements.txt`
2. 复制 `.env.example` 为 `.env`，填写密钥。
3. 启动：
   - `streamlit run src/app/streamlit_app.py`

## 目录

核心结构见 `docs/governance/STRUCTURE.md`。

