from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from translator.siliconflow_client import SiliconFlowClient


PROMPT_FILE = Path(__file__).resolve().parents[1] / "config" / "prompts" / "Translate_Bot_Prompt.md"


@dataclass
class TranslateStage:
    client: SiliconFlowClient

    def run(self, article: dict) -> dict:
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        source_text = self._compose_source_payload(article)
        user_prompt = (
            "请按系统提示翻译以下文章。输出完整英文翻译与 captions，并附名字核对问题列表。\n\n"
            f"{source_text}"
        )
        content = self.client.chat(system_prompt=system_prompt, user_prompt=user_prompt)
        return {
            "source_url": article.get("url", ""),
            "model": self.client.model,
            "translated_text": content,
        }

    @staticmethod
    def _compose_source_payload(article: dict) -> str:
        payload = {
            "title": article.get("title", ""),
            "published_at": article.get("published_at", ""),
            "author": article.get("author", ""),
            "paragraphs": article.get("body_paragraphs", []),
            "captions": article.get("captions", []),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

