from verifier.name_extractor import NameExtractor


def test_extract_questions() -> None:
    extractor = NameExtractor()
    questions = extractor.extract_questions(
        original_text="石破茂在东京表示",
        translated_text="Shigeru Ishiba met Donald Trump in Tokyo.",
    )
    assert any("Shigeru Ishiba" in q for q in questions)
    assert any("Donald Trump" in q for q in questions)

