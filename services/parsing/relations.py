"""Find a small number of evidence-backed entity mentions in the text.

Scope note first, because it matters: this is a **rule-based candidate finder,
not a model**. The schedule for this step asks for a minimum of three
candidates with at least one of each entity type, each carrying its page and
its source quote, and explicitly warns against growing this into a full
knowledge graph. A rule set is the honest way to meet that bar: it is
deterministic, every result can be explained, and it does not pretend to
understand the text.

The product claim this supports is deliberately modest. A relation says "this
document mentions this name, on this page, in this sentence, as found by this
rule". A person then confirms, corrects or rejects it. Nothing here asserts a
fact about the world.

Rules, in the order they are applied to a capitalised run:

1. ends with a project-ish noun (Project, Platform, System, Assistant, ...)
   -> project
2. is preceded by a title (Mr, Dr, Prof, ...) -> person
3. otherwise a capitalised run that appears in at least two different chunks
   -> topic

Runs whose first word is an ordinary sentence starter are dropped, because
otherwise every sentence would produce a candidate.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from services.parsing.chunking import Chunk

# Stamped on every relation this module produces, so a rule result can be told
# apart from a model result and both can be revisited later.
PRODUCER_REVISION = "relations-rules-v1"

ENTITY_PERSON = "person"
ENTITY_PROJECT = "project"
ENTITY_TOPIC = "topic"

_PROJECT_SUFFIXES = {
    "project",
    "platform",
    "system",
    "assistant",
    "pipeline",
    "portal",
    "service",
    "manager",
    "workbench",
}

# Ordinary words that start a sentence far more often than they start a name.
_NOT_A_NAME_START = {
    "the", "this", "that", "these", "those", "a", "an", "in", "on", "for",
    "it", "we", "our", "their", "if", "when", "where", "what", "how", "why",
    "then", "now", "use", "run", "check", "open", "see", "each", "every",
    "some", "all", "any", "you", "your", "they", "there", "here", "and",
    "but", "or", "so", "as", "at", "by", "from", "with", "without", "to",
    "of", "is", "are", "was", "were", "be", "been", "do", "does", "did",
    "not", "no", "yes", "only", "also", "more", "most", "less", "least",
}

_RUN = re.compile(r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\b")

# A title immediately before a name. Matching the whole preceding window would
# fail as soon as any earlier text fell inside it, so this anchors to the end.
_TITLE_BEFORE = re.compile(
    r"(?:^|[\s(\[])(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+$",
    re.IGNORECASE,
)

# How much surrounding text is stored as the quote that justifies a relation.
_QUOTE_PADDING = 80

# The schedule asks for a small number of evidence-backed candidates rather
# than a graph, so the result is bounded. Ranking is by how often an entity is
# mentioned: a term a document keeps returning to is a better candidate than
# one that appears once, and this needs no model to justify.
MAX_CANDIDATES = 10


@dataclass(frozen=True)
class CandidateRelation:
    """One entity a document mentions, with the passage that shows it."""

    entity_type: str
    label: str
    normalized_label: str
    # Chunks are referenced by their ordinal within the version, not by a
    # database id: relations are found before anything is written, so the row
    # id does not exist yet. The persistence step resolves it.
    chunk_ordinal: int
    page_number: int
    start_offset: int
    end_offset: int
    quote: str
    producer_revision: str = PRODUCER_REVISION


def _normalise(label: str) -> str:
    return " ".join(label.split()).casefold()


def _strip_leading_filler(run: str) -> str:
    """Drop ordinary words from the front of a capitalised run.

    "The File Management Assistant" is the name "File Management Assistant"
    with an article in front of it. Rejecting the whole run because it begins
    with "The" would throw away exactly the names we are looking for.
    """
    words = run.split()
    while words and words[0].casefold() in _NOT_A_NAME_START:
        words.pop(0)
    return " ".join(words)


def _classify(run: str, preceding: str, seen_in_chunks: int) -> str | None:
    words = run.split()
    if not words:
        return None

    if words[-1].casefold() in _PROJECT_SUFFIXES:
        return ENTITY_PROJECT

    if _TITLE_BEFORE.search(preceding):
        return ENTITY_PERSON

    # A capitalised run that recurs across chunks is a reasonable topic
    # candidate. One that appears once is more likely to be an ordinary
    # sentence opener, so it is dropped.
    if seen_in_chunks >= 2:
        return ENTITY_TOPIC

    return None


def _quote(text: str, start: int, end: int) -> str:
    left = max(0, start - _QUOTE_PADDING)
    right = min(len(text), end + _QUOTE_PADDING)
    return " ".join(text[left:right].split())


def _is_line_initial(text: str, start: int) -> bool:
    return start == 0 or text[start - 1] == "\n"


def find_mentions(
    chunks: Sequence[Chunk], *, skip_line_initial: bool = True
) -> list[CandidateRelation]:
    """Return every mention that passes the rules, in reading order.

    ``skip_line_initial`` turns off the rule that drops a single capitalised
    word at the start of a line. It exists so the effect of that rule can be
    measured rather than asserted: the numbers in
    `evidence/relation-candidates.md` are produced by running the finder both
    ways over the same documents. Leaving it on is the shipped behaviour.
    """
    # First pass: how many distinct chunks does each capitalised run appear in?
    chunks_per_run: dict[str, set[int]] = {}
    for chunk in chunks:
        for match in _RUN.finditer(chunk.text):
            chunks_per_run.setdefault(_normalise(match.group()), set()).add(chunk.ordinal)

    mentions: list[CandidateRelation] = []
    for chunk in chunks:
        for match in _RUN.finditer(chunk.text):
            raw = match.group()
            run = _strip_leading_filler(raw)
            if not run:
                continue
            # The mention starts where the name starts, not where the article
            # in front of it does.
            start = match.start() + (len(raw) - len(run))
            preceding = chunk.text[max(0, start - 12) : start]

            # A single capitalised word at the start of a line is almost always
            # a sentence or bullet opener ("Observe", "Create", "Session"),
            # not a name. Multi-word runs are kept because real names and
            # project titles typically have more than one word.
            if (
                skip_line_initial
                and len(run.split()) == 1
                and _is_line_initial(chunk.text, start)
            ):
                continue

            entity_type = _classify(
                run, preceding, len(chunks_per_run.get(_normalise(run), ()))
            )
            if entity_type is None:
                continue
            mentions.append(
                CandidateRelation(
                    entity_type=entity_type,
                    label=run,
                    normalized_label=_normalise(run),
                    chunk_ordinal=chunk.ordinal,
                    page_number=chunk.page_number,
                    start_offset=start,
                    end_offset=start + len(run),
                    quote=_quote(chunk.text, start, start + len(run)),
                )
            )
    return mentions


def candidate_relations(
    chunks: Sequence[Chunk], limit: int = MAX_CANDIDATES
) -> list[CandidateRelation]:
    """The most-mentioned candidates, at most ``limit`` of them.

    Keeping a single row per entity is what stops this becoming a dumping
    ground of every occurrence; bounding the count is what stops it becoming a
    graph. Later mentions are still available through ``find_mentions``.
    """
    mentions = find_mentions(chunks)
    counts = Counter((mention.entity_type, mention.normalized_label) for mention in mentions)

    seen: set[tuple[str, str]] = set()
    candidates: list[CandidateRelation] = []
    for mention in mentions:
        key = (mention.entity_type, mention.normalized_label)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(mention)

    candidates.sort(
        key=lambda candidate: (
            -counts[(candidate.entity_type, candidate.normalized_label)],
            candidate.chunk_ordinal,
            candidate.start_offset,
        )
    )
    return candidates[:limit]
