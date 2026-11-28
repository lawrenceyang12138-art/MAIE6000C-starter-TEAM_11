"""Conservative, deterministic navigation over physical PDF page numbers.

This module interprets page expressions only. It never identifies a document,
reads evaluation answers, rewrites the embedding query or guesses total pages.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

PageIntentKind = Literal["first", "last", "middle", "absolute", "single"]


@dataclass(frozen=True)
class PageIntent:
    kind: PageIntentKind
    page: int | None = None


@dataclass(frozen=True)
class PageIntentParse:
    intent: PageIntent | None
    skipped_reason: str | None = None


_PAGE_CONTEXT = re.compile(r"页|\b(?:pages?|leaf|leaves)\b")
_NEGATION = re.compile(
    r"不要|别|并非|不是|排除|除了|除外|无需|不必|不用|不(?:打开|查看|看|找)"
    r"|\b(?:not|never|avoid|exclude|except|without|don't|dont)\b"
)
_NUMBER_TEXT = r"[0-9零〇一二两三四五六七八九十百千万负+\-]+"
_RELATIVE_WORD = r"(?:first|opening|initial|last|final|closing|middle|central)"
_CONFLICT = re.compile(
    rf"\b{_RELATIVE_WORD}\s*(?:,|/|\band\b|\bor\b)\s*(?:the\s+)?"
    rf"{_RELATIVE_WORD}\s+(?:pages?|leaf|leaves)\b"
)
_RANGE = re.compile(
    rf"(?:第\s*)?{_NUMBER_TEXT}\s*(?:[-–—~至到])\s*(?:第\s*)?{_NUMBER_TEXT}\s*页"
    r"|\b(?:pages?|leaf|leaves)\s+\d+\s*(?:[-–—~]|to\b|through\b)\s*\d*"
    r"|\b\d+(?:st|nd|rd|th)?\s+(?:to|through)\s+\d+(?:st|nd|rd|th)?\s+pages?\b"
    r"|\bpages?\s+\d+\s*(?:,|and\b|or\b)\s*\d+"
    r"|\b(?:first|last|final)\s+(?:[2-9]\d*|\d{2,})\s+pages\b"
    r"|(?:最后|前|后)(?:[2-9]\d*|[二两三四五六七八九十百千]+)页"
)
_RELATIVE_PATTERNS = (
    ("first", re.compile(
        r"首页|首\s*页|第\s*一\s*页|\b(?:first|opening|initial)\s+(?:page|leaf)\b"
    )),
    ("last", re.compile(
        r"(?:最后|最末)(?:的)?(?:那)?(?:一|1)?页|末页|尾页"
        r"|\b(?:last|final|closing)\s+(?:page|leaf)\b"
    )),
    ("middle", re.compile(
        r"(?:正?中间|中央|中心)(?:的)?(?:那)?(?:一|1)?页"
        r"|\b(?:middle|central|center|centre)\s+(?:page|leaf)\b"
    )),
    ("single", re.compile(
        r"(?:只有|仅有|仅)(?:一|1)页|单页(?:文档|文件|资料|报告|pdf)"
        r"|\b(?:single|one)[ -]page\s+(?:document|file|report|pdf|notes?|paper|manual)\b"
        r"|\b(?:document|file|report|pdf)\s+(?:with\s+)?(?:only\s+)?one\s+page\b"
    )),
)
_CHINESE_ABSOLUTE = re.compile(rf"第\s*(?P<number>{_NUMBER_TEXT})\s*页")
_ENGLISH_ABSOLUTE = re.compile(
    r"\b(?:page|leaf)\s*(?:number\s*|no\.?\s*|#\s*)?"
    r"(?P<number>[+\-]?\d+)(?P<ordinal>st|nd|rd|th)?\b(?!\.\d)"
)
_ENGLISH_ORDINAL = re.compile(
    r"\b(?P<number>[+\-]?\d+)(?P<ordinal>st|nd|rd|th)\s+(?:page|leaf)\b"
)
_ORDINAL_WORDS = {
    "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
    "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
    "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
    "twentieth": 20,
}
_WORD_ABSOLUTE = re.compile(
    r"\b(" + "|".join(_ORDINAL_WORDS) + r")\s+(?:page|leaf)\b"
)
_UNSUPPORTED_NUMBER = re.compile(
    r"\b(?:page|leaf)\s+(?:[+\-]?\d+\.\d+|infinity|infinite|∞)"
    r"|第\s*(?:[+\-]?\d+\.\d+|负\d+|无限|∞)\s*页"
)
_DIGITS = {character: value for value, character in enumerate("零一二三四五六七八九")}


def _chinese_render(value: int) -> str:
    """Canonical Chinese form of 1..9999, used to reject ambiguous numerals."""
    result = ""
    needs_zero = False
    for unit, suffix in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        digit, value = divmod(value, unit)
        if digit:
            if needs_zero:
                result += "零"
            if not (digit == 1 and unit == 10 and not result):
                result += "零一二三四五六七八九"[digit]
            result += suffix
            needs_zero = False
        elif result and value:
            needs_zero = True
    return result


def _page_number(value: str) -> int | None:
    if re.fullmatch(r"\d+", value):
        # Bounded by the database's integer page representation, not corpus size.
        if len(value) > 10:
            return None
        number = int(value)
        return number if 1 <= number <= 2_147_483_647 else None
    normalized = value.replace("两", "二").replace("〇", "零")
    if not normalized or len(normalized) > 15:
        return None
    number = digit = 0
    previous_unit = 10000
    for character in normalized:
        if character in _DIGITS:
            digit = _DIGITS[character]
        elif character in "十百千":
            unit = {"十": 10, "百": 100, "千": 1000}[character]
            if unit >= previous_unit:
                return None
            number += (digit or 1) * unit
            digit = 0
            previous_unit = unit
        else:
            return None
    number += digit
    if not 1 <= number <= 9999:
        return None
    # Both 十 and 一十 are ordinary unambiguous ways to write ten.
    accepted = {_chinese_render(number)}
    if 10 <= number <= 19:
        accepted.add("一" + _chinese_render(number))
    return number if normalized in accepted else None


def _ordinal_valid(number: int, suffix: str | None) -> bool:
    if suffix is None:
        return True
    expected = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(
        number % 10, "th"
    )
    return suffix == expected


def parse_page_intent(query: str) -> PageIntentParse:
    """Recognize one explicit navigation instruction; ambiguity stays ordinary.

    Document ordinals are deliberately not interpreted. Negation, ranges and
    conflicting page instructions disable navigation for the complete query.
    """
    normalized = " ".join(unicodedata.normalize("NFKC", query).casefold().split())
    if not _PAGE_CONTEXT.search(normalized):
        return PageIntentParse(None, "no_intent")
    intents = []
    for kind, pattern in _RELATIVE_PATTERNS:
        if pattern.search(normalized):
            intents.append(PageIntent(kind))
    invalid_number = bool(_UNSUPPORTED_NUMBER.search(normalized))
    for pattern in (_CHINESE_ABSOLUTE, _ENGLISH_ABSOLUTE, _ENGLISH_ORDINAL):
        for match in pattern.finditer(normalized):
            number = _page_number(match["number"])
            suffix = match.groupdict().get("ordinal")
            if number is None or not _ordinal_valid(number, suffix):
                invalid_number = True
            else:
                intents.append(PageIntent("absolute", number))
    intents.extend(PageIntent("absolute", _ORDINAL_WORDS[match[1]])
                   for match in _WORD_ABSOLUTE.finditer(normalized))
    if _NEGATION.search(normalized) and (intents or _RANGE.search(normalized) or invalid_number):
        return PageIntentParse(None, "negated")
    if _RANGE.search(normalized):
        return PageIntentParse(None, "range")
    if _CONFLICT.search(normalized):
        return PageIntentParse(None, "conflicting")
    if invalid_number:
        return PageIntentParse(None, "unsupported")
    if not intents:
        return PageIntentParse(None, "no_intent")
    equivalent = {
        ("absolute", 1) if intent.kind == "first" else (intent.kind, intent.page)
        for intent in intents
    }
    if len(equivalent) != 1:
        return PageIntentParse(None, "conflicting")
    # Prefer the named first-page intent when the phrase also matched 第1页.
    intent = next((item for item in intents if item.kind == "first"), intents[0])
    return PageIntentParse(intent)


def target_pages(intent: PageIntent, page_count: int) -> tuple[int, ...]:
    """Return valid physical target pages; absent targets never become neighbors."""
    if type(page_count) is not int or page_count < 1:
        return ()
    if intent.kind == "first":
        return (1,)
    if intent.kind == "last":
        return (page_count,)
    if intent.kind == "middle":
        lower = (page_count + 1) // 2
        return (lower,) if page_count % 2 else (lower, lower + 1)
    if intent.kind == "single":
        return (1,) if page_count == 1 else ()
    if intent.kind == "absolute" and type(intent.page) is int and 1 <= intent.page <= page_count:
        return (intent.page,)
    return ()
