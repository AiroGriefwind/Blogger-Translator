from scraper.bastille_scraper import BastilleScraper


def main() -> None:
    url = "https://www.bastillepost.com/hongkong/article/15731771"
    scraper = BastilleScraper()
    result = scraper.scrape(url).to_dict()
    print("title:", result["title"])
    print("published_at:", result["published_at"])
    print("author:", result["author"])
    print("paragraphs:", len(result["body_paragraphs"]))
    print("captions:", len(result["captions"]))


if __name__ == "__main__":
    main()

