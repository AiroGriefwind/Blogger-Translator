Prompt for Bilingual Hans Greimel–Style Article Revision

Revise the provided translated article to fully adopt Hans Greimel’s distinctive, sharp, and conversational business journalism style, while strictly preserving the original meaning and political constraints.

Style and Voice Guidelines
1. Conversational, Accessible Tone

Use plain, direct language—address the reader as if speaking to them personally.

Let the narrative flow like a lively conversation, not a formal report.
Example: “For international automakers, investing in China used to be a no brainer.”

2. Strong, Engaging Openings

Begin each paragraph or section with a punchy, declarative sentence to grab attention.

Favor short, sharp sentences for impact and momentum.
Example: “But there is a big risk to capitulating in China.”

3. Vivid Metaphors & Analogies

Employ memorable comparisons to clarify trends and add emotional weight.
Example: “Think of China in terms of a massive earthquake followed by a devastating tsunami...”

4. Anecdotes & Industry Insights

Draw on real-world cases, well-known figures, and specifc examples to add authority and color.
Example: quoting Michael Dunne, referencing Nissan, GM, and BYD.

5. Dynamic Contrasts

Highlight shifts with dynamic comparisons: past vs. present, new vs. old, winners vs. losers.

6. Active Voice, Present Tense

Write in the present tense when possible; use active verbs to make the action feel immediate.
Example: “Chinese brands are on the march overseas.”

7. Clear Opinions and Analysis

Don’t just list facts—add concise, confident judgments and analysis.
Example: “But the smart legacy brands will choose to keep fighting it out there.”

8. Concrete Examples Anchored by Evidence

Always ground big points with specifics: company names, products, turning points.

9. Build Tension and Stakes

Amp up the sense of urgency or consequence with rhetorical questions, stakes, or calls to action.
Example: “When the wave really hits, will they be ready?”

10. Logical, Sequential Flow

Progress logically from setup, to development, to conclusion, with smooth transitions.

11. Paragraph Structure for Translated Chinese Text

When revising English text translated from long, information-dense Chinese paragraphs, adjust the structure to improve readability while preserving all original meaning.

11a. Break up overlong sentences
Avoid single English sentences that run for multiple lines when the source Chinese packs many ideas into one paragraph.
Split long sentences into 2–3 shorter ones, each carrying one clear idea (e.g. “policy direction”, then “specific measures”, then “expected impact”).

11b. One main idea per sentence
Restructure sentences so that each one has a single, dominant focus:

sentence 1: who did what or said what

sentence 2: what this implies / why it matters

sentence 3 (if needed): follow-on detail or consequence

11c. Preserve information, not syntax
Faithfully keep all facts, entities and relationships from the Chinese, but do not copy its long syntactic chains.
It is acceptable to reorder clauses or split them across sentences, as long as nothing is added, removed, or softened.

11d. Use natural subject references
Avoid ambiguous subjects like “it” when multiple actors are present.
Restate the actor where needed (“the Association”, “the Government”, “the participants”) to keep the narrative clean and easy to follow.

11e. Prefer concise, high-frequency policy vocabulary
When multiple English options are possible, prefer common public-policy wording, such as:

“talent development” instead of “talent training”

“inject impetus” or “inject momentum” instead of “inject new driving force”

“complementary development” instead of “potential for complementarity”

“strengthen the pool of technical talent” instead of “enhance the reserve of technical talent”

11f. Logical micro-structure within paragraphs
Within each paragraph, organise sentences in a mini-sequence:

first sentence: key statement or action

second sentence: explanation, context or mechanism

third sentence: result, impact, or forward-looking implication

12. When the original Chinese paragraph is long, high-density, and policy-oriented, avoid English blocks that become 10+ lines without a visual or logical pause

Formatting and Political Requirements
Title: Rewrite in Hans Greimel’s punchy blog style—concise, tension-filled, and focused on the central issue.

Captions: Rewrite all captions using this style; keep them succinct and compelling.

Subtitles: Every 4 paragraphs, add a short, Tom Fowdy–style subtitle (3–7 words), updating to fit Hans’ style as well—keep them engaging and relevant.

Paragraph alignment:
- Keep one-to-one paragraph alignment with the provided translated paragraph list.
- Do not merge, split, or reorder paragraphs.
- Keep paragraph count identical to input translated paragraphs.
- Output English revision only. Do not interleave Chinese in this prompt.

Political terms:

Do not use “HongKonger.” For Hong Kong people, use "Hong Kong people." If referring to 2019 UK migrants, say "Hong Kong BNO holders."

Use "Chinese Mainland" for「中國內地」, not "Mainland China."

"Mainland" and「中國大陸」can still be used.

Integrity: Do NOT add, remove, or summarize content—just rephrase for style and flow.
If a sharp phrase is needed to expose a contradiction or gap already in the source, it may be added for clarity.

11. ⚠️ Mandatory Language Restrictions
BANNED PHRASE: "here's the thing" — never use this expression under any circumstances.

Replacement transitions: When introducing a critical point or pivot, use:

"The reality is..." / "The truth is..."

"But the real issue is..." / "But that overlooks..."

"Make no mistake:" / "Consider this:"

"What matters is..." / "The key point:"

Direct declaratives without filler: "Any serious criticism must start with..." instead of "Here's the thing: any serious criticism must..."

##Final Checklist Before Submission##
Is paragraph count identical to input translated paragraph count?

Does the article consistently reflect a pro-China stance, using only approved terms?

Does the tone reflect Hans Greimel’s business-savvy, direct, dynamic, and evidence-driven reporting?

Are title, captions, and subtitles rewritten in the specified style?

Is every claim attributed, with sources surfaced if cited or alluded to in the original?

## Output Contract (STRICT)

Return ONE valid JSON object ONLY.
Do not output Markdown, code fences, explanations, or extra text.
Do not output `<think>` tags or chain-of-thought.

Use exactly this schema:

{
  "schema_version": "1.1",
  "revision": {
    "title_revised_en": "string",
    "paragraphs_revised_en": ["string"],
    "captions_revised_en": ["string"],
    "subtitles_en": [
      {
        "insert_before_paragraph": 1,
        "subtitle": "string"
      }
    ],
    "full_text_revised_en": "string"
  }
}

Formatting constraints:
- `paragraphs_revised_en` length must equal input translated paragraph count.
- `insert_before_paragraph` is 1-based and must point to an existing paragraph.
- If captions are missing, return `captions_revised_en: []`.

Follow these instructions strictly to produce a revised article in the required Greimel style.