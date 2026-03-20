from verifier.entity_verifier import EntityVerifier, _is_valid_http_url
from verifier.verify_stage import VerifyStage


class _DummyClient:
    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
        raise RuntimeError("chat() should not be called in this unit test")


def test_url_validator() -> None:
    assert _is_valid_http_url("https://en.wikipedia.org/wiki/Donald_Trump")
    assert _is_valid_http_url("http://example.com/page")
    assert not _is_valid_http_url("ftp://example.com/file")
    assert not _is_valid_http_url("not-a-url")


def test_entity_verifier_downgrades_verified_without_url() -> None:
    verifier = EntityVerifier(client=_DummyClient())
    normalized = verifier._normalize_result(  # pylint: disable=protected-access
        paragraph_id=3,
        entity={
            "entity_zh": "特朗普",
            "entity_en": "Donald Trump",
            "type": "person",
            "is_verified": True,
            "verification_status": "verified",
            "sources": [{"url": "not-a-url", "site": "x", "evidence_note": "x"}],
            "final_recommendation": "Use Donald Trump",
            "uncertainty_reason": "",
            "next_search_queries": [],
        },
    )
    item = normalized["entity"]
    assert item["is_verified"] is False
    assert item["verification_status"] == "unverified"
    assert item["sources"] == []
    assert item["uncertainty_reason"] != ""
    assert item["next_search_queries"]


def test_extract_translated_paragraphs_prefers_json_contract() -> None:
    stage = VerifyStage(client=_DummyClient())
    parsed = stage._extract_translated_paragraphs(  # pylint: disable=protected-access
        {
            "translated_text": (
                '{"translation":{"paragraphs_en":["Paragraph A","Paragraph B"]},'
                '"captions":{"translated_captions":[]}}'
            )
        }
    )
    assert parsed == ["Paragraph A", "Paragraph B"]


def test_extract_translated_paragraphs_fallback_to_blankline_split() -> None:
    stage = VerifyStage(client=_DummyClient())
    parsed = stage._extract_translated_paragraphs(  # pylint: disable=protected-access
        {"translated_text": "Para 1\n\nPara 2\n\nPara 3"}
    )
    assert parsed == ["Para 1", "Para 2", "Para 3"]
