from __future__ import annotations

import re
import unicodedata

MODEL_NAME = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
MODEL_ID = f"{MODEL_NAME}@{MODEL_REVISION}"
DIMENSIONS = 384
MAX_TEXT_CHARS = 2000
MAX_BATCH_SIZE = 16
MAX_QUERY_TOKENS = 64
MODEL_FILES = (
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "sentencepiece.bpe.model",
)

_TOKEN_RUNS = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff]+|[^\W_\u3400-\u4dbf\u4e00-\u9fff]+",
    re.UNICODE,
)
_CJK = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff]+$")
_STOP_WORDS = frozenset("a an and are as at be by for from in is it of on or the to with".split())


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def tokenize(text: str) -> tuple[str, ...]:
    """English words and contiguous Chinese bigrams, with no external tokenizer."""
    tokens: list[str] = []
    for match in _TOKEN_RUNS.finditer(normalize_text(text)):
        run = match.group()
        if _CJK.fullmatch(run) and len(run) > 1:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
        elif run not in _STOP_WORDS:
            tokens.append(run)
    return tuple(dict.fromkeys(tokens))


def search_terms(text: str) -> str:
    return " " + " ".join(tokenize(text)) + " "
