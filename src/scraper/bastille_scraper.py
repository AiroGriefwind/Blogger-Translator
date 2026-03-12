from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag


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
            results.append(text)
        return results

    @staticmethod
    def _extract_captions(article_root: Tag | None, soup: BeautifulSoup) -> list[str]:
        results: list[str] = []
        seen: set[str] = set()
        roots = [article_root] if article_root else []
        roots.append(soup)

        for root in roots:
            if root is None:
                continue
            for node in root.select("a.image-lightbox[data-caption], p.caption, p[class*='caption']"):
                text = ""
                if node.has_attr("data-caption"):
                    text = node["data-caption"].strip()
                else:
                    text = node.get_text(" ", strip=True)
                if text and text not in seen:
                    seen.add(text)
                    results.append(text)

        for anchor in soup.select("a.image-lightbox"):
            alt_text = ""
            if anchor.has_attr("data-caption"):
                alt_text = (anchor.get("data-caption") or "").strip()
            if not alt_text:
                img = anchor.select_one("img[alt]")
                if img:
                    alt_text = (img.get("alt") or "").strip()
            if alt_text and alt_text not in seen:
                seen.add(alt_text)
                results.append(alt_text)
        return results

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

