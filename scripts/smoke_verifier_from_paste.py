from __future__ import annotations

import json

from config.settings import Settings
from translator.siliconflow_client import SiliconFlowClient
from verifier.verify_stage import VerifyStage


def _build_input(limit_paragraphs: int = 1) -> tuple[dict, dict]:
    # Normalized from user-pasted scraper/translator outputs.
    # Keep a small subset for smoke to avoid long multi-entity online verification timeout.
    zh_paragraphs = [
        "美利坚合众国的大统帅又来一场「黑色幽默」：一手点燃中东战火、导致全球能源动脉霍尔木兹海峡被封锁的美国总统特朗普，竟在镜头前耸肩自夸，声称保障这条航道畅通是「很荣幸」，是在在帮助中国等国。然而，镜头之外，他最亲密的亚太盟友——日本，正因这条海峡的关闭而陷入一场迫在眉睫的「存亡危机」。一边是「救世主」的自我感动，一边是「附庸国」的瑟瑟发抖，这番对比，堪称当代国际关系中「选择性失明」的典范。",
        "据霍士新闻网报道，特朗普在佛罗里达州接受采访时，被问及因美以袭击伊朗而遭封锁的霍尔木兹海峡局势。这位始作俑者非但毫无愧色，反而摆出一副「救世主」姿态，声称要确保海峡畅通，并刻意标榜此举是在帮助依赖这条航道的「中国和其他国家」。",
        "荒诞的是，特朗普忘记了基本事实：正是他授权的军事行动，直接触发了伊朗封锁海峡的反制。将自己制造的危机，包装成对他人的「帮助」，这种逻辑宛如纵火犯宣称帮忙灭火是他的「荣幸」，更何况他根本没有能力灭火。",
        "特朗普的「荣幸」论调，在现实面前显得无比苍白。真正决定船只能否安全通过霍尔木兹海峡的，并非美国的「保护」。伊朗伊斯兰革命卫队已明确宣布，仅禁止美国、以色列、欧洲国家及其支持者的船只通过霍尔木兹海峡。",
    ][:limit_paragraphs]

    en_paragraphs = [
        "The President of the United States, Donald Trump, has once again delivered a 'black comedy': the man who ignited Middle Eastern conflict and caused the closure of the Hormuz Strait, a global energy artery, now shrugs and boasts on camera, claiming that ensuring the strait's smooth operation is a 'great honor' and a service to China and other nations.",
        "According to Fox News, Trump, during an interview in Florida, was asked about the Hormuz Strait situation resulting from U.S.-Israeli strikes on Iran. Far from showing any remorse, Trump adopted a 'savior' pose, asserting his commitment to keeping the strait open and emphasizing that this effort was particularly beneficial to China and other nations reliant on this route.",
        "The absurdity lies in Trump's disregard for basic facts: it was his authorized military actions that directly triggered Iran's closure of the strait as a countermeasure. Presenting the crisis he created as a 'help' to others is akin to an arsonist claiming credit for firefighting efforts.",
        "Trump's 'honor' narrative pales in the face of reality. The real determinant of whether ships can safely traverse the Hormuz Strait is not American 'protection.' The Islamic Revolutionary Guard Corps of Iran has explicitly banned vessels from the U.S., Israel, Europe, and their allies from passing through the strait.",
    ][:limit_paragraphs]

    scraped = {
        "url": "https://www.bastillepost.com/hongkong/article/15731771",
        "title": "特朗普“帮助中国”的荣幸，和日本“被勒脖子”的现实",
        "published_at": "2026-03-11T22:42:59+08:00",
        "author": "双标研究所",
        "body_paragraphs": zh_paragraphs,
        "captions": [],
    }
    translated_payload = {
        "schema_version": "1.1",
        "translation": {
            "title_en": "Trump's Honor in 'Helping China' While Ignoring Japan's 'Economic Suffocation'",
            "published_at": "2026-03-11T22:42:59+08:00",
            "author_en": "Double Standards Decoder",
            "paragraphs_en": en_paragraphs,
            "full_text_en": "\n\n".join(en_paragraphs),
        },
        "captions": {"translated_captions": []},
    }
    translated = {
        "source_url": scraped["url"],
        "model": "manual-pasted-translation",
        "translated_text": json.dumps(translated_payload, ensure_ascii=False),
    }
    return scraped, translated


def main() -> None:
    settings = Settings.load(require_storage=False)
    client = SiliconFlowClient(
        api_key=settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url,
        model=settings.siliconflow_model,
        timeout=settings.siliconflow_timeout_seconds,
        max_retries=settings.siliconflow_max_retries,
    )
    verify = VerifyStage(client, temperature=settings.siliconflow_temperature)

    scraped, translated = _build_input(limit_paragraphs=1)
    result = verify.run(scraped=scraped, translated=translated)

    samples = []
    for paragraph in result.get("paragraph_results", []):
        for entity in paragraph.get("verified_entities", []):
            sources = entity.get("sources", [])
            samples.append(
                {
                    "paragraph_id": paragraph.get("paragraph_id"),
                    "entity_zh": entity.get("entity_zh", ""),
                    "entity_en": entity.get("entity_en", ""),
                    "is_verified": entity.get("is_verified", False),
                    "url": (sources[0].get("url", "") if sources else ""),
                }
            )
            if len(samples) >= 5:
                break
        if len(samples) >= 5:
            break

    output = {
        "summary": result.get("summary", {}),
        "alignment_notes": result.get("alignment_notes", []),
        "sample_entities": samples,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
