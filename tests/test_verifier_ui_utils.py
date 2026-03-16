from app.verifier_ui_utils import (
    build_entity_groups,
    build_entity_search_terms,
    build_replacement_candidates,
)


def test_build_entity_search_terms_for_person_aliases() -> None:
    terms = build_entity_search_terms("John Wick", "person")
    assert "John Wick" in terms
    assert "John" in terms
    assert "Wick" in terms


def test_build_replacement_candidates_hits_fullname_and_aliases() -> None:
    terms = build_entity_search_terms("John Wick", "person")
    translated_text = "John Wick appeared first, then John left."
    paragraph_results = [{"paragraph_id": 1, "en": "Later, Wick returned to the scene."}]
    candidates = build_replacement_candidates(
        translated_text=translated_text,
        paragraph_results=paragraph_results,
        search_terms=terms,
    )
    matched_terms = {item["term"] for item in candidates}
    assert "John Wick" in matched_terms
    assert "John" in matched_terms
    assert "Wick" in matched_terms


def test_build_entity_groups_splits_by_verification_status() -> None:
    paragraph_results = [
        {
            "paragraph_id": 1,
            "zh": "约翰威克",
            "en": "John Wick",
            "verified_entities": [
                {"entity_zh": "约翰威克", "entity_en": "John Wick", "verification_status": "db_exact_hit"},
                {
                    "entity_zh": "约翰",
                    "entity_en": "John",
                    "verification_status": "runtime_cache_hit",
                },
                {"entity_zh": "维克", "entity_en": "Wick", "verification_status": "verified"},
            ],
        }
    ]
    grouped = build_entity_groups(paragraph_results)
    assert len(grouped["db_exact_hit"]) == 1
    assert len(grouped["runtime_cache_hit"]) == 1
    assert len(grouped["llm"]) == 1

