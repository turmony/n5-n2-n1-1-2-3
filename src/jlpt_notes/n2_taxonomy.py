"""Public JLPT N2 non-listening item types supported by this system."""

N2_NON_LISTENING_TYPES = {
    "vocabulary": ("kanji_reading", "orthography", "word_formation", "context_expression", "paraphrase", "usage"),
    "grammar": ("grammar_form", "sentence_composition", "text_grammar"),
    "reading": ("short_passage", "mid_passage", "long_passage", "integrated_comprehension", "thematic_comprehension", "information_retrieval"),
}

ITEM_TYPES = frozenset(item for group in N2_NON_LISTENING_TYPES.values() for item in group)
