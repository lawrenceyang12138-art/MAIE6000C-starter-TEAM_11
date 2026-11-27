# Archived search evaluation evidence

These are historical runs on the team's synthetic, ordinal PDF corpus. The
original reports, commands, hashes, and logs are available in the linked Git
snapshot; they are not stored again in this checkout. The links pin the archived
reports, not the code under test. Use the tested revision and inputs recorded
in each report to reproduce that run, and save new results separately.

## E5 team PDF

The [October 29-30 E5 archive][e5] recorded keyword Top-1 **5/5**, semantic
Top-3 **3/5**, and hybrid Top-3 **3/5**. The previous E5 weights were later
retired. Some artifact digests in this archive refer to CRLF checkout bytes
rather than the Git-normalized LF bytes.

## PPLX local model

The [October 30 PPLX archive][pplx] recorded **5/5**, **3/5**, and **3/5**
respectively on both PostgreSQL and SQLite using the normal PDF pipeline.

## Page navigation

The [October 30 page-navigation archive][navigation] records a pure-model
rerun with the same **5/5**, **3/5**, and **3/5** results. With physical-page
navigation enabled, all three modes scored **5/5**. The assisted result is
source-location evidence, not a change in the model's semantic quality.

The semantic **4/5** threshold was a candidate, not a team acceptance gate;
B's human gold review remained pending. These small runs do not establish
semantic quality on general documents or current combined-tree acceptance.

[e5]: https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/tree/7d5d21c94a5ed7962f5f085aa2f68fb02200d379/submissions/week07/evidence/C/team-pdf-20261029
[pplx]: https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/tree/7d5d21c94a5ed7962f5f085aa2f68fb02200d379/submissions/week07/evidence/C/20261030-pplx
[navigation]: https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/tree/7d5d21c94a5ed7962f5f085aa2f68fb02200d379/submissions/week07/evidence/C/20261030-page-navigation
