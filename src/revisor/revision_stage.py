from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from translator.siliconflow_client import SiliconFlowClient


PROMPT_FILE = Path(__file__).resolve().parents[1] / "config" / "prompts" / "Revision_Bot_Prompt.md"


@dataclass
class RevisionStage:
    client: SiliconFlowClient
    max_title_words: int = 12
    max_caption_words: int = 25

    def run(self, source_article: dict, translation: dict) -> dict:
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        user_prompt = (
            "请根据系统提示对以下翻译做润色，保持英语段落后紧跟中文原文段落。\n\n"
            f"原文标题：{source_article.get('title', '')}\n"
            f"原文正文：{source_article.get('body_paragraphs', [])}\n"
            f"原文captions：{source_article.get('captions', [])}\n\n"
            f"初稿翻译：\n{translation.get('translated_text', '')}"
        )
        revised_text = self.client.chat(system_prompt=system_prompt, user_prompt=user_prompt)
        return {
            "model": self.client.model,
            "revised_text": revised_text,
            "title_limit": self.max_title_words,
            "caption_limit": self.max_caption_words,
        }

