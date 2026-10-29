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
# Content identity for MODEL_REVISION, also retained by the historical model
# manifest. Preparation and offline loading share these trusted expected hashes;
# a newly generated manifest must not authenticate arbitrary replacement files.
PINNED_MODEL_SHA256 = {
    "config.json": "69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959",
    "model.safetensors": "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477",
    "tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    "tokenizer_config.json": "a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b",
    "special_tokens_map.json": "d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7",
    "sentencepiece.bpe.model": "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
}

_TOKEN_RUNS = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff]+|[^\W_\u3400-\u4dbf\u4e00-\u9fff]+",
    re.UNICODE,
)
_CJK = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff]+$")
_STOP_WORDS = frozenset("a an and are as at be by for from in is it of on or the to with".split())


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def tokenize(text: str) -> tuple[str, ...]:
    """English words and contiguous Chinese bigrams, with no external tokenizer.

    Bigrams never cross whitespace or punctuation. A single Chinese character is
    retained as a token; longer Chinese runs use bigrams rather than unrelated
    individual characters. SQL and SQLite use exactly the same token contract.
    """
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
