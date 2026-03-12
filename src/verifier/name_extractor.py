from __future__ import annotations

import re


class NameExtractor:
    EN_NAME_PATTERN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b")
    ZH_NAME_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,6}")

    def extract_questions(self, original_text: str, translated_text: str) -> list[str]:
        names = set()
        for match in self.EN_NAME_PATTERN.findall(translated_text):
            names.add(match.strip())
        for match in self.ZH_NAME_PATTERN.findall(original_text):
            if len(match) >= 2:
                names.add(match.strip())

        questions: list[str] = []
        for name in sorted(names):
            questions.append(
                f"Question: What is the English/Traditional Chinese translation of {name}, who is this person/company in context?"
            )
        return questions

