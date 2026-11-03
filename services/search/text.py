from __future__ import annotations

import re
import unicodedata

MODEL_NAME = "perplexity-ai/pplx-embed-v2-late-0.6b"
MODEL_REVISION = "7bba8e7cf2075dec747fa8557f41eb90e70361ed"
MODEL_ID = f"{MODEL_NAME}@{MODEL_REVISION}"
# Frozen physical type of the retired shared dense column. The active model
# never writes or searches that column; its token vectors live in a C sidecar.
DIMENSIONS = 384
TOKEN_DIMENSIONS = 128
MODEL_DIRECTORY = "models/pplx-embed-v2-late-0.6b"
QUERY_PREFIX = "[Q] "
PASSAGE_PREFIX = "[D] "
MAX_QUERY_MODEL_TOKENS = 1024
MAX_DOCUMENT_MODEL_TOKENS = 4096
MAX_TEXT_CHARS = 2000
MAX_BATCH_SIZE = 16
MODEL_FORWARD_BATCH_SIZE = 4
MAX_QUERY_TOKENS = 64
MODEL_FILES = (
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "modules.json",
    "config_sentence_transformers.json",
    "sentence_bert_config.json",
    "processor_config.json",
    "chat_template.jinja",
    "requirements.txt",
    "1_Dense/config.json",
    "1_Dense/model.safetensors",
    "2_MultiVectorMask/config.json",
    "3_Normalize/config.json",
)
# Sizes of the SHA-pinned files, not an estimate from a download response.
MODEL_FILE_BYTES = {
    "config.json": 2305,
    "model.safetensors": 2377321184,
    "tokenizer.json": 19989705,
    "tokenizer_config.json": 1195,
    "modules.json": 535,
    "config_sentence_transformers.json": 264,
    "sentence_bert_config.json": 664,
    "processor_config.json": 1351,
    "chat_template.jinja": 479,
    "requirements.txt": 63,
    "1_Dense/config.json": 238,
    "1_Dense/model.safetensors": 524376,
    "2_MultiVectorMask/config.json": 391,
    "3_Normalize/config.json": 89,
}
# Content identities verified against the official pinned Hugging Face git tree
# (small-file blob OIDs and LFS SHA256s). A self-signed manifest is insufficient.
PINNED_MODEL_SHA256 = {
    "config.json": "c8f7eb8533d309e19fd62390779432c57c9f47dc3dc0e262bc2fadf46513210f",
    "model.safetensors": "107eaae48d026ea20458b30dd755a0f1475b34fcf5a1895123ad67a2385b9d6b",
    "tokenizer.json": "a171436d73b1d30b9ba99ff6b7f15efcf45cf428b6ff908842286a8057030b1c",
    "tokenizer_config.json": "85d5045a11205796e6ec9615f104437813b9d1810debb2669219fe32901eb922",
    "modules.json": "35d6f7421d1df0148c58255c1d7a61e16abc8eb929c37ca898308a963eb693a6",
    "config_sentence_transformers.json":
        "1c1abaf5dfd78bba1d3dce93704ce8d9877687e54eaed6f4a441cf4efa3a3078",
    "sentence_bert_config.json": "002ad0a38c521862a54a2ab61a08b66f5d139a791200a38bbb9f256118d53ba4",
    "processor_config.json": "9bfa7f59801e8680077ebd09a1308cf89125538c5e19b901328ba0066750c504",
    "chat_template.jinja": "00a123eb8e945cf6bf0246abed96fcc0ff577f9c12f3af1aac246f3d32b5c4cf",
    "requirements.txt": "b92fbd9b613248745c1f6805e027d3da68fb2e328e3eda94e9be1eba30f21d91",
    "1_Dense/config.json": "b2edb3cf8fbbd76ed3b41ed1e41bcb49c2fb4863a600914a70e30ba5dc5cef02",
    "1_Dense/model.safetensors": "ea18dae8901decaf9533aaeda9123a52770c8b65680f17e37d15ff6fce085172",
    "2_MultiVectorMask/config.json":
        "98a33321fed690efcf10dff2db3b4e17a435adf8ac3fda67f675633c03b41d2a",
    "3_Normalize/config.json": "51f74e99b3040bed9ddee1f39b0ca2aad0f28f605e932803517e5f574aac7eb4",
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
