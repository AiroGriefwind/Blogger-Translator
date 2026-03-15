from __future__ import annotations

import argparse

from config.settings import Settings
from scraper.bastille_scraper import BastilleScraper
from translator.siliconflow_client import SiliconFlowClient
from translator.translate_stage import TranslateStage


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test scraper + translate stage.")
    parser.add_argument(
        "--url",
        default="https://www.bastillepost.com/hongkong/article/15731771",
        help="Bastille article URL",
    )
    args = parser.parse_args()

    settings = Settings.load(require_storage=False)
    scraper = BastilleScraper()
    article = scraper.scrape(args.url).to_dict()

    client = SiliconFlowClient(
        api_key=settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url,
        model=settings.siliconflow_model,
        timeout=settings.siliconflow_timeout_seconds,
        max_retries=settings.siliconflow_max_retries,
    )
    stage = TranslateStage(client, temperature=settings.siliconflow_temperature)
    translated = stage.run(article)

    print("source_url:", translated.get("source_url", ""))
    print("model:", translated.get("model", ""))
    print("paragraphs:", len(article.get("body_paragraphs", [])))
    print("captions:", len(article.get("captions", [])))
    print("\n--- translated_text preview ---")
    print((translated.get("translated_text", "") or "")[:1200])


if __name__ == "__main__":
    main()
