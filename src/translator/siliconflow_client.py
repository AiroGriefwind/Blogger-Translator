from __future__ import annotations

from dataclasses import dataclass
import random
import re
import time
from typing import Callable
from typing import Any

import requests


@dataclass
class SiliconFlowClient:
    api_key: str
    base_url: str
    model: str
    timeout: int = 120
    max_retries: int = 2

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        on_retry: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
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
                wait_seconds = self._compute_backoff_seconds(attempt=attempt, response=exc.response)
                if on_retry:
                    on_retry(
                        {
                            "attempt": attempt + 1,
                            "status": status,
                            "wait_seconds": wait_seconds,
                            "reason": f"http_{status}",
                            "url": url,
                        }
                    )
                time.sleep(wait_seconds)
                continue
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= self.max_retries:
                    raise
                last_error = exc
                wait_seconds = self._compute_backoff_seconds(attempt=attempt, response=None)
                if on_retry:
                    on_retry(
                        {
                            "attempt": attempt + 1,
                            "status": None,
                            "wait_seconds": wait_seconds,
                            "reason": exc.__class__.__name__.lower(),
                            "url": url,
                        }
                    )
                time.sleep(wait_seconds)
                continue

        if last_error is not None:
            raise last_error
        raise RuntimeError("SiliconFlow 请求失败，但未捕获到具体异常")

    @staticmethod
    def _sanitize_output(content: str) -> str:
        # 部分推理模型会返回 <think>...</think>，UI 默认不展示该部分。
        cleaned = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
        # 某些模型可能只返回 </think> 结尾标签，前面是可见推理文本。
        if "</think>" in cleaned:
            cleaned = cleaned.split("</think>")[-1].strip()
        return cleaned

    @staticmethod
    def _compute_backoff_seconds(attempt: int, response: requests.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After", "").strip()
            if retry_after:
                try:
                    wait = float(retry_after)
                    if wait > 0:
                        return min(wait, 30.0)
                except ValueError:
                    pass
        # Exponential backoff with jitter.
        base = min(2 ** (attempt + 1), 16)
        jitter = random.uniform(0.0, 1.5)
        return min(base + jitter, 30.0)

