from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any

import requests


@dataclass
class SiliconFlowClient:
    api_key: str
    base_url: str
    model: str
    timeout: int = 120
    max_retries: int = 2

    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return self._sanitize_output(content)
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                should_retry = status in {408, 429} or (status is not None and status >= 500)
                if not should_retry or attempt >= self.max_retries:
                    raise
                last_error = exc
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= self.max_retries:
                    raise
                last_error = exc

            # 轻量退避，避免瞬时网络抖动导致整个阶段失败。
            time.sleep(min(2 * (attempt + 1), 8))

        if last_error is not None:
            raise last_error
        raise RuntimeError("SiliconFlow 请求失败，但未捕获到具体异常")

    @staticmethod
    def _sanitize_output(content: str) -> str:
        # 部分推理模型会返回 <think>...</think>，UI 默认不展示该部分。
        return re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()

