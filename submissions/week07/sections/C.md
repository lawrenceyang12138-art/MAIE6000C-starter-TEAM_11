# C — Searching Files: Canonical Index, Ranking and Degradation

## Scope

The “search files” workstream turns a user query into a ranked passage from a
current authorized file. The W7 contract requires keyword retrieval to work
first. Semantic retrieval is a useful increment, but it must not hide the
keyword path or make a model outage look like an empty result.

The original C branch had working keyword, vector and hybrid algorithms but
also introduced `source_files`, `source_versions` and `source_chunks` tables.
Those tables duplicated B's file/version/chunk model. Merging them would have
made the product depend on two definitions of “the current file.” The
integration therefore keeps the search algorithms and removes the duplicate
source model.

## Canonical search index

`chunk_search_index` has one row per canonical `source_chunks.id`. Its primary
key is also a cascading foreign key to `source_chunks`. It stores normalized
search text, tokenized search terms and an optional 384-dimensional embedding,
plus the embedding model id and dimensions. The source text remains in
`source_chunks`; the index is rebuildable derived data.

`persist_chunks` synchronizes the index after a chunk replacement. Unchanged
chunks keep their stable ids. If a chunk's text changes, its old vector is
cleared and its search terms are recomputed. A search result therefore opens
the exact canonical chunk that produced the ranking.

## Retrieval

Queries are normalized and validated at the API boundary. Empty queries,
oversized token counts, unsupported modes and invalid identifiers return a
structured validation error. The search base filters to current versions that
are `basic_ready` or `enriched`, present files and active/paused roots.
Revoked roots, missing files and superseded versions are excluded.

Keyword scoring combines term coverage, a phrase bonus and a filename match.
Chinese text is tokenized as overlapping bigrams; English text is case-folded
and split into word runs. Results are deduplicated by file, keeping the best
passage for each file so one long document cannot overwhelm the list. The
response includes the file, version, chunk, ordinal, page, text, reason,
keyword score and semantic score.

PostgreSQL has a GIN expression index over the normalized search terms. SQLite
is the unit-test adapter; it uses the same normalization and is not presented
as a production search backend. The candidate pool is bounded by
`search_max_candidates`.

## Semantic fallback

Semantic and hybrid modes use the same canonical result base. The AI service
exposes `/embeddings`; the local backend validates a pinned model manifest and
refuses to download a different model at runtime. The HTTP embedding client
checks the model id, dimensions and vector norms. The real pinned E5 model was
loaded locally, produced 384-dimensional vectors for all 20 canonical chunks,
and the five frozen descriptions hit the expected file/page 5/5 in Top-3.
Opening each hit returned the matching chunk/page 5/5.

The UI retains an explicit degradation path such as `ai_unavailable`,
`ai_disabled`, `embeddings_not_ready` or `partial_embeddings` when the model or
service is unavailable. The model weights are not committed to Git; the
release bundle must copy them and build the AI image with
`INSTALL_EMBEDDINGS=1`.

## Evaluation and evidence

The fixed corpus has five keyword queries. On the live stack, K01–K05 returned
the expected file and page 5/5, and each returned chunk id opened evidence
with the same page 5/5. This is the M1 search gate. The results were not tuned
after the answer table was frozen.

The semantic result is verified on the prepared local model. The remaining
step is to package the model cache and the CPU dependency image for the
offline release. The result must be reported as a small synthetic smoke test,
not a general quality claim.

## Tests

The suite covers index creation and rebuild, current-version filtering, root
authorization, file deduplication, keyword phrase matching, semantic vector
retrieval, malformed queries and evidence/chunk agreement. The full suite is
139 passed with one skip. The search implementation is not a replacement for
the parser's evidence checks: the route and the evidence handler both verify
the canonical chunk and version.

One deliberate usability choice is that a query may return several files when
the synthetic corpus shares a common phrase. The UI shows the match reason and
the top result is still the specific document expected by the frozen answer
table. This is more honest than hiding the other matches or claiming that the
common phrase is unique. For a production corpus, the same principle applies:
the result should explain why it matched, not only show a score.
