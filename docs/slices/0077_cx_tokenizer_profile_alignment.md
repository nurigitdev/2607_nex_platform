# Slice 0077: CX tokenizer profile alignment

## Intent

Slice 0077 makes BM25 tokenizer behavior explicit and keeps query tokenization
aligned with the lexical index that is being searched.

This matters because the default tokenizer is `mecab_ko` with
`korean_mixed_v1` fallback. If the index is built with one tokenizer and the
query is tokenized with another, retrieval can silently miss valid chunks.

## Implementation

- `cx_lexical_index.v1` records a `tokenizer_profile` with:
  - requested tokenizer
  - tokenizer actually used
  - fallback tokenizer
  - fallback usage flag
  - query tokenizer policy
  - dictionary profile
  - MeCab dictionary environment key state
- Retrieval query tokenization now uses the tokenizer recorded on each lexical
  index and falls back to the recorded fallback tokenizer.
- If both recorded tokenizer names are unusable, query tokenization falls back
  to the built-in `korean_mixed_v1` tokenizer to preserve retrieval availability
  for legacy or partially migrated in-memory records.
- Retrieval packages expose `bm25_tokenizer_profile` in `retrieval_profile`.

## Current Policy

- Default BM25 tokenizer: `mecab_ko`
- Default dictionary profile: `mecab-ko-dic`
- Fallback tokenizer: `korean_mixed_v1`
- Fallback dictionary profile: `none_regex_korean_mixed_v1`
- Query tokenizer policy: `match_index_tokenizer_with_fallback`

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_cx_lexical_index.py tests/test_nex_cx_retrieval.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
