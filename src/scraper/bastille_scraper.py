from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


@dataclass
class ScrapedArticle:
    url: str
    title: str
    published_at: str
    author: str
    body_paragraphs: list[str]
    captions: list[str]
    raw_html: str
    scrape_meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "published_at": self.published_at,
            "author": self.author,
            "body_paragraphs": self.body_paragraphs,
            "captions": self.captions,
            "raw_html": self.raw_html,
            "scrape_meta": self.scrape_meta,
        }


class BastilleScraper:
    def __init__(self, config_file: str | Path | None = None):
        base = Path(__file__).resolve().parent
        config_path = Path(config_file) if config_file else base / "html_structure.json"
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        self.selectors = payload["bastillepost"]

    def fetch_html(self, url: str) -> str:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        return resp.text

    def parse(self, url: str, html: str) -> ScrapedArticle:
        soup = BeautifulSoup(html, "html.parser")
        ldjson = self._extract_ldjson(soup)
        title = self._pick_text(soup, self.selectors["title"]) or ldjson.get("headline", "")
        published_at = self._pick_text(soup, self.selectors["time"]) or ldjson.get(
            "datePublished", ""
        )
        author = self._pick_text(soup, self.selectors["author"]) or self._ldjson_author(ldjson)

        article_root = soup.select_one(self.selectors["article_root"])
        body_paragraphs = self._extract_paragraphs(article_root)
        captions = self._extract_captions(article_root, soup)

        return ScrapedArticle(
            url=url,
            title=title or "",
            published_at=published_at or "",
            author=author or "",
            body_paragraphs=body_paragraphs,
            captions=captions,
            raw_html=html,
            scrape_meta={
                "paragraph_count": len(body_paragraphs),
                "caption_count": len(captions),
                "used_ldjson_fallback": bool(ldjson),
            },
        )

    def scrape(self, url: str) -> ScrapedArticle:
        html = self.fetch_html(url)
        return self.parse(url=url, html=html)

    @staticmethod
    def _pick_text(soup: BeautifulSoup | Tag, selector_csv: str) -> str | None:
        for selector in [s.strip() for s in selector_csv.split(",")]:
            node = soup.select_one(selector)
            if node:
                text = node.get_text(" ", strip=True)
                if text:
                    return text
        return None

    @staticmethod
    def _extract_paragraphs(article_root: Tag | None) -> list[str]:
        if not article_root:
            return []
        results: list[str] = []
        for p in article_root.select("p"):
            text = p.get_text(" ", strip=True)
            css = " ".join(p.get("class", []))
            if not text:
                continue
            if "caption" in css.lower():
                continue
            if BastilleScraper._is_disclaimer_text(text):
                continue
            results.append(text)
        return results

    @staticmethod
    def _extract_captions(article_root: Tag | None, soup: BeautifulSoup) -> list[str]:
        results: list[str] = []
        seen: set[str] = set()

        # 先提取正文容器内的 captions。
        if article_root:
            for node in article_root.select("a.image-lightbox[data-caption], p.caption, p[class*='caption']"):
                BastilleScraper._append_caption(node=node, seen=seen, results=results)

        # 再从正文后序扫描，直到“往下看更多文章”为止，避免误抓下一篇文章内容。
        iterator = article_root.next_elements if article_root else soup.descendants
        for elem in iterator:
            if isinstance(elem, NavigableString):
                if "往下看更多文章" in str(elem):
                    break
                continue
            if not isinstance(elem, Tag):
                continue
            if elem.name == "h3" and "往下看更多文章" in elem.get_text(" ", strip=True):
                break
            if elem.name == "a" and "image-lightbox" in (elem.get("class") or []):
                BastilleScraper._append_caption(node=elem, seen=seen, results=results)
            elif elem.name == "p":
                css = " ".join(elem.get("class", []))
                if "caption" in css.lower():
                    BastilleScraper._append_caption(node=elem, seen=seen, results=results)
        return results

    @staticmethod
    def _append_caption(node: Tag, seen: set[str], results: list[str]) -> None:
        text = ""
        if node.has_attr("data-caption"):
            text = (node.get("data-caption") or "").strip()
        if not text:
            text = node.get_text(" ", strip=True)
        if not text and node.name == "a":
            img = node.select_one("img[alt]")
            if img:
                text = (img.get("alt") or "").strip()
        if not text:
            return
        if BastilleScraper._is_disclaimer_text(text):
            return
        if text not in seen:
            seen.add(text)
            results.append(text)

    @staticmethod
    def _is_disclaimer_text(text: str) -> bool:
        normalized = text.replace("*", "").replace(" ", "")
        return "博客文章文責自負" in normalized and "不代表本公司立場" in normalized

    @staticmethod
    def _extract_ldjson(soup: BeautifulSoup) -> dict[str, Any]:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.get_text())
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("@type") in {"NewsArticle", "Article"}:
                return data
        return {}

    @staticmethod
    def _ldjson_author(ldjson: dict[str, Any]) -> str:
        author = ldjson.get("author")
        if isinstance(author, dict):
            return str(author.get("name", "")).strip()
        if isinstance(author, list) and author and isinstance(author[0], dict):
            return str(author[0].get("name", "")).strip()
        return ""

