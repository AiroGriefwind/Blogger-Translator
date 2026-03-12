from __future__ import annotations

import streamlit as st

from config.settings import SettingsError
from pipeline.orchestrator import PipelineOrchestrator


st.set_page_config(page_title="Blogger Translator", layout="wide")
st.title("Blogger Translator")
st.write("输入巴士的报文章 URL，生成最终翻译与排版 docx。")

url = st.text_input("文章 URL", value="https://www.bastillepost.com/hongkong/article/15731771")
output_dir = st.text_input("本地输出目录", value="outputs")

if st.button("开始处理", type="primary"):
    try:
        orchestrator = PipelineOrchestrator()
        with st.spinner("正在抓取、翻译、润色与导出..."):
            result = orchestrator.run(url=url, output_dir=output_dir)
        st.success("处理完成")
        st.json(result)
    except SettingsError as err:
        st.error(str(err))
    except Exception as err:  # pragma: no cover
        st.exception(err)

