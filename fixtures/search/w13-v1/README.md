# W13 search evaluation candidate v1

This is a new fixture/answer version, not a replacement for D's historical W7
freeze. The manifest names the 16 files actually mounted by the W7 Compose
configuration, with their real hashes, paths, and four parser classifications.
It also adds 12 synthetic two-page work notes in `topics/`. Each of six subject
areas has a relevant document and a near distractor. Source text is English;
there are six English and six Chinese topical prompts. The five W7 exact
marker queries are a separate source-location smoke test, not topical scores.

The topical queries and supporting passages were written and hash-pinned before
the first ranking run. Questions do not give a filename, document ordinal, or
physical page. Two language variants share each topic, so the 12 prompts are not
12 independent topics. The pool and labels are authored, not an independently
human-reviewed or production-representative benchmark. B's review and the team
threshold are pending; preserve this version's bytes and use a new version for
any agreed corpus or answer change.

A relevant current file, an exact physical page, and a supporting excerpt are
tracked separately. The source document is not modified during the evaluation.
