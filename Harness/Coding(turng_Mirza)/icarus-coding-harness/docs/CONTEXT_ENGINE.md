# Context Engine

The Context Engine exposes \`retrieve_context\`. It never mutates source files; an explicitly enabled semantic cache may persist derived vectors in the workspace's private \`.icarus\` metadata directory.

## What it does

- Inventories a bounded set of text files and classifies them by role and language.
- Produces a compact repository map: file counts by language/role, likely entry manifests, and local dependency edges.
- Ranks files against a task/query using path, filename, symbol-definition, and content matches.
- Reserves room for direct dependency neighbours so a relevant module can bring its local implementation context with it.
- Returns bounded snippets and an approximate token estimate.

## Dependency analysis

The static graph currently supports:
- Python `import` and `from ... import ...` statements resolved against workspace Python modules, including common `src/` layouts.
- Relative JavaScript/TypeScript `import`, `export ... from`, `require()`, and literal dynamic-import paths when they resolve to files in the workspace.
- Go import paths that resolve inside a discovered local `go.mod` module. Nested modules are matched by the longest module path; production `.go` files are preferred over `_test.go` files.
- Rust top-level out-of-line `mod` declarations, simple `#[path = ...]` overrides, and simple `crate::`, `self::`, or `super::` `use` paths.

Go and Rust support is intentionally syntactic and partial. Rust inline/nested modules, grouped `use` trees, conditional compilation, generated files, and arbitrary macro expansion are not resolved. Go external modules and standard-library packages are ignored unless they happen to match a local module declaration. The engine does not resolve package registries, arbitrary runtime/dynamic imports, or bundler aliases. Edges are evidence from source syntax, not proof that a dependency is loaded at runtime.

## Bounds and safety

- Up to 2,000 paths are inventoried per call.
- Individual files are limited to 96 KB and the total source scan to 4 MB.
- Returned context is limited to 512–8,000 approximate tokens and 1–20 files.
- Binary, invalid UTF-8, oversized, generated, harness-metadata, and sensitive-looking paths are skipped.
- Workspace paths are resolved through \`Workspace.resolve\`; symlink targets outside the selected workspace are rejected.
- Common credential patterns are redacted using the reviewer's existing heuristic filter. This is defense in depth, not a complete secret scanner.
- Source files are never written and no commands or package registries are accessed. With the semantic cache disabled, retrieval writes no files; with it enabled, only the bounded \`.icarus/context-index.json\` cache and its lock file are written.

The token estimate uses approximately four characters per token. It is a budgeting heuristic, not the configured model's tokenizer. Broader language-aware analysis remains future work.

## Reference patterns studied

The implementation was informed by patterns in the pinned sample repositories:
- [Aider RepoMap](https://github.com/Aider-AI/aider/tree/5dc9490bb35f9729ef2c95d00a19ccd30c26339c): repository-level symbol and relationship maps.
- [Continue context retrieval](https://github.com/continuedev/continue/tree/5522c6f44ca0ac3528b37244818fbfa39b5af470): retrieval of relevant codebase context and import/static context.
- Continue's pinned `core/indexing/README.md` documents content-addressed artifact reuse and re-indexing changed files; only that design idea informs this cache. Its Apache-2.0 license was checked; no source code was copied.
- [AgentMemory](https://github.com/rohitg00/agentmemory/tree/c6c476d2905926727fa5848a134d7a3b38a7fa98): graph-oriented retrieval concepts.
- [Goose](https://github.com/aaif-goose/goose/tree/cfb67d72f6129ba3c9f68d4c225d8dfcaba18a87): Rust crate module organization and explicit `mod`/`use` relationships.

These repositories were inspected selectively at the pinned revisions. No third-party source code was copied or vendored, and the 119 sample repositories were not benchmarked.


## Optional semantic reranking

Semantic retrieval is an explicit opt-in. Set `embeddings.enabled=true` in
`.icarus/config.json` and configure an OpenAI-compatible `/embeddings`
endpoint. The default is disabled and points at a loopback URL for local use;
the configured embedding model must already be available on that server.

For each retrieval, the engine sends the query and at most 48 file documents.
Documents are assembled from the workspace-relative path, role, language, and
heuristically redacted source text, capped at 8,000 characters each. If more
than 48 files exist, the candidate set combines lexical leaders with a bounded
source/test/documentation sample. Hybrid scoring combines lexical relevance
(35%) and cosine similarity (65%). Dependency-neighbour reservation and the
existing output token budget still apply.

The HTTP client:
- accepts only HTTP(S) URLs without userinfo, query strings, or fragments;
- permits plain HTTP only for loopback hosts;
- requires `allow_remote=true` and an environment-sourced API key for remote HTTPS;
- disables redirects and ambient HTTP proxies;
- bounds input count, input characters, response size, timeout, and vector dimensions;
- never includes API-key values or upstream response bodies in error messages.

Semantic request failures do not fail context retrieval; the result reports
`retrieval_mode=lexical_fallback` and retains lexical ranking. With the provider
disabled, `retrieval_mode=lexical`. Successful optional reranking reports
`retrieval_mode=hybrid`.

The query embedding is recomputed for each request. An optional incremental
document-vector cache can be enabled separately with
\`embeddings.cache_enabled=true\`; it is disabled by default. The cache stores
only workspace-relative paths, SHA-256 digests of redacted semantic documents,
a hash of the configured endpoint/model identity, and numeric vectors. It does
not persist source text, query text, or credential values. Changed document
digests are re-embedded; unchanged documents reuse their vectors.

The cache is bounded to 512 entries and 8 MiB. It is written atomically under
\`.icarus/context-index.json\` with mode 0600, using a pinned no-follow directory
descriptor and a process lock. Unsupported platforms, unsafe paths, and cache
errors fail closed for persistence while semantic retrieval continues without
a cache. Vectors are derived data and should still be treated as sensitive.
Changing the configured endpoint or model identifier invalidates reuse; a
model update behind an unchanged endpoint/model alias cannot be detected.

The candidate set remains bounded to 48 files, so this is an incremental cache
for retrieved candidates rather than a full-repository vector database. Secret
redaction is heuristic, not a guarantee. A remote provider receives the query
and cache-miss source documents after heuristic redaction, so enable remote
embedding only when the endpoint and data-sharing arrangement are trusted.
