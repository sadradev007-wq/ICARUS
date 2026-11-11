# Context Engine

The initial Context Engine increment is a read-only workspace tool exposed as \`retrieve_context\`.

## What it does

- Inventories a bounded set of text files and classifies them by role and language.
- Produces a compact repository map: file counts by language/role, likely entry manifests, and local dependency edges.
- Ranks files against a task/query using path, filename, symbol-definition, and content matches.
- Reserves room for direct dependency neighbours so a relevant module can bring its local implementation context with it.
- Returns bounded snippets and an approximate token estimate.

## Dependency analysis

The first static graph supports:
- Python \`import\` and \`from ... import ...\` statements resolved against workspace Python modules, including common \`src/\` layouts.
- Relative JavaScript/TypeScript \`import\`, \`export ... from\`, \`require()\`, and literal dynamic-import paths when they resolve to files in the workspace.

It does not resolve package-registry dependencies, arbitrary runtime/dynamic imports, aliases configured by bundlers, or imports in other languages. Edges are evidence from source syntax, not proof that a dependency is loaded at runtime.

## Bounds and safety

- Up to 2,000 paths are inventoried per call.
- Individual files are limited to 96 KB and the total source scan to 4 MB.
- Returned context is limited to 512–8,000 approximate tokens and 1–20 files.
- Binary, invalid UTF-8, oversized, generated, harness-metadata, and sensitive-looking paths are skipped.
- Workspace paths are resolved through \`Workspace.resolve\`; symlink targets outside the selected workspace are rejected.
- Common credential patterns are redacted using the reviewer's existing heuristic filter. This is defense in depth, not a complete secret scanner.
- No files are written, no commands are run, and no network or package registry is accessed.

The token estimate uses approximately four characters per token. It is a budgeting heuristic, not the configured model's tokenizer. Semantic/embedding retrieval and broader language-aware dependency analysis remain future work.

## Reference patterns studied

The implementation was informed by patterns in the pinned sample repositories:
- [Aider RepoMap](https://github.com/Aider-AI/aider/tree/5dc9490bb35f9729ef2c95d00a19ccd30c26339c): repository-level symbol and relationship maps.
- [Continue context retrieval](https://github.com/continuedev/continue/tree/5522c6f44ca0ac3528b37244818fbfa39b5af470): retrieval of relevant codebase context and import/static context.
- [AgentMemory](https://github.com/rohitg00/agentmemory/tree/c6c476d2905926727fa5848a134d7a3b38a7fa98): graph-oriented retrieval concepts.

These repositories were inspected selectively at the pinned revisions. No third-party source code was copied or vendored, and the 119 sample repositories were not benchmarked.
