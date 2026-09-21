"""Public JLPT N5-N1 non-listening item types supported by this system.

The module name is retained for compatibility with existing imports.
"""

JLPT_NON_LISTENING_TYPES = {
    "vocabulary": ("kanji_reading", "orthography", "word_formation", "context_expression", "paraphrase", "usage"),
    "grammar": ("grammar_form", "sentence_composition", "text_grammar"),
    "reading": ("short_passage", "mid_passage", "long_passage", "integrated_comprehension", "thematic_comprehension", "information_retrieval"),
}

N2_NON_LISTENING_TYPES = JLPT_NON_LISTENING_TYPES
ITEM_TYPES = frozenset(item for group in JLPT_NON_LISTENING_TYPES.values() for item in group)
