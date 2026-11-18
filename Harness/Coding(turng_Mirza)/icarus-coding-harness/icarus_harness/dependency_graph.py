from __future__ import annotations

import posixpath
import re
from pathlib import PurePosixPath
from typing import Any


_GO_MODULE_RE = re.compile(r'(?m)^\s*module\s+(?:"([^"]+)"|\x60([^\x60]+)\x60|(\S+))')
_GO_IMPORT_BLOCK_RE = re.compile(r"(?ms)^[ \t]*import[ \t]*\((.*?)\)")
_GO_IMPORT_SINGLE_RE = re.compile(
    r'(?m)^[ \t]*import[ \t]+(?:(?:[A-Za-z_][A-Za-z0-9_]*|[._])[ \t]+)?["\x60]([^"\x60]+)["\x60]'
)
_GO_IMPORT_SPEC_RE = re.compile(
    r'^[ \t]*(?:(?:[A-Za-z_][A-Za-z0-9_]*|[._])[ \t]+)?["\x60]([^"\x60]+)["\x60]'
)
_RUST_MOD_RE = re.compile(
    r"(?m)^(?:#\[path\s*=\s*['\"]([^'\"]+)['\"]\s*\]\s*\n)?"
    r"(?:pub(?:\s*\([^)]*\))?\s+)?mod\s+([A-Za-z_]\w*)\s*;"
)
_RUST_USE_RE = re.compile(
    r"(?m)^(?:pub(?:\s*\([^)]*\))?\s+)?use\s+"
    r"(crate|self|super)::([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*;"
)


def _go_imports(source: str) -> set[str]:
    imports: set[str] = set()
    blocks = list(_GO_IMPORT_BLOCK_RE.finditer(source))
    for block in blocks:
        body = re.sub(r"/\*.*?\*/", "", block.group(1), flags=re.S)
        for line in body.splitlines():
            line = line.split("//", 1)[0]
            match = _GO_IMPORT_SPEC_RE.match(line)
            if match:
                imports.add(match.group(1))
    remainder = _GO_IMPORT_BLOCK_RE.sub("", source)
    imports.update(match.group(1) for match in _GO_IMPORT_SINGLE_RE.finditer(remainder))
    return imports


def _go_edges(entries: dict[str, dict[str, Any]]) -> set[tuple[str, str, str]]:
    modules: list[tuple[str, str]] = []
    package_files: dict[str, list[str]] = {}
    for relative, item in entries.items():
        name = PurePosixPath(relative).name.casefold()
        if name == "go.mod":
            match = _GO_MODULE_RE.search(str(item.get("raw_text", "")))
            if match:
                module_path = next((value for value in match.groups() if value), "")
                root = posixpath.dirname(relative)
                modules.append((module_path, "" if root == "." else root))
        if relative.endswith(".go"):
            package_files.setdefault(posixpath.dirname(relative), []).append(relative)

    if not modules or not package_files:
        return set()
    modules = sorted(set(modules), key=lambda pair: (len(pair[0]), len(pair[1])), reverse=True)
    for paths in package_files.values():
        paths.sort()

    edges: set[tuple[str, str, str]] = set()
    for source, item in entries.items():
        if not source.endswith(".go"):
            continue
        if not any(not root or source.startswith(root + "/") for _module, root in modules):
            continue
        for imported in _go_imports(str(item.get("raw_text", ""))):
            if imported.startswith("/") or "\\" in imported:
                continue
            if any(part in {".", ".."} for part in PurePosixPath(imported).parts):
                continue
            matches = [
                pair for pair in modules
                if imported == pair[0] or imported.startswith(pair[0] + "/")
            ]
            if not matches:
                continue
            target_module, target_root = max(matches, key=lambda pair: len(pair[0]))
            suffix = imported[len(target_module):].lstrip("/")
            target_dir = posixpath.normpath(posixpath.join(target_root, suffix)) if suffix else target_root
            if target_dir == ".." or target_dir.startswith("../") or target_dir.startswith("/"):
                continue
            targets = package_files.get(target_dir, [])
            production = [path for path in targets if not PurePosixPath(path).name.endswith("_test.go")]
            for target in production or targets:
                if target != source:
                    edges.add((source, target, "go_import"))
    return edges


def _is_rust_crate_root(relative: str) -> bool:
    path = PurePosixPath(relative)
    parent = path.parent
    parts = set(parent.parts)
    if path.name in {"lib.rs", "main.rs"} and (parent.name == "src" or str(parent) == "."):
        return True
    if path.suffix == ".rs" and parent.name in {"bin", "tests", "examples", "benches"}:
        return True
    return path.name in {"lib.rs", "main.rs"} and {"src", "bin"}.issubset(parts)


def _rust_edges(entries: dict[str, dict[str, Any]]) -> set[tuple[str, str, str]]:
    rust_paths = {path for path in entries if path.endswith(".rs")}
    roots = sorted(path for path in rust_paths if _is_rust_crate_root(path))
    if not roots:
        roots = sorted(
            path for path in rust_paths
            if PurePosixPath(path).name in {"lib.rs", "main.rs"}
            and str(PurePosixPath(path).parent) == "."
        )

    edges: set[tuple[str, str, str]] = set()
    contexts: dict[str, list[tuple[tuple[str, ...], dict[tuple[str, ...], str]]]] = {}
    for root in roots:
        module_files: dict[tuple[str, ...], str] = {(): root}
        queue: list[tuple[tuple[str, ...], str]] = [((), root)]
        visited: set[tuple[tuple[str, ...], str]] = set()
        while queue:
            module_parts, source = queue.pop(0)
            identity = (module_parts, source)
            if identity in visited:
                continue
            visited.add(identity)
            contexts.setdefault(source, []).append((module_parts, module_files))
            source_name = PurePosixPath(source).name
            parent = posixpath.dirname(source)
            if source_name in {"lib.rs", "main.rs", "mod.rs"}:
                module_dir = parent
            else:
                module_dir = posixpath.join(parent, PurePosixPath(source).stem)

            source_text = str(entries[source].get("raw_text", ""))
            for match in _RUST_MOD_RE.finditer(source_text):
                override, module_name = match.groups()
                if override:
                    if override.startswith("/") or "\\" in override:
                        continue
                    target = posixpath.normpath(posixpath.join(parent, override))
                    if target == ".." or target.startswith("../") or target.startswith("/"):
                        continue
                    candidates = [target]
                else:
                    candidates = [
                        posixpath.join(module_dir, module_name + ".rs"),
                        posixpath.join(module_dir, module_name, "mod.rs"),
                    ]
                target = next((candidate for candidate in candidates if candidate in rust_paths), None)
                if not target:
                    continue
                child_parts = module_parts + (module_name,)
                edges.add((source, target, "rust_mod"))
                if child_parts not in module_files:
                    module_files[child_parts] = target
                    queue.append((child_parts, target))

    for source, source_contexts in contexts.items():
        source_text = str(entries[source].get("raw_text", ""))
        for current_parts, module_files in source_contexts:
            for match in _RUST_USE_RE.finditer(source_text):
                prefix, suffix = match.groups()
                suffix_parts = tuple(suffix.split("::"))
                if prefix == "crate":
                    resolved_parts = suffix_parts
                elif prefix == "self":
                    resolved_parts = current_parts + suffix_parts
                else:
                    resolved_parts = current_parts[:-1] + suffix_parts
                target = None
                for size in range(len(resolved_parts), 0, -1):
                    target = module_files.get(resolved_parts[:size])
                    if target:
                        break
                if target and target != source:
                    edges.add((source, target, "rust_use"))
    return edges


def additional_dependency_edges(entries: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Return static Go and Rust edges from already-scanned workspace files.

    Go edges resolve only imports belonging to a discovered local go.mod module.
    Rust edges resolve top-level out-of-line mod declarations and simple
    crate/self/super use paths. External packages and unresolved paths are ignored.
    """
    edges = _go_edges(entries) | _rust_edges(entries)
    return [
        {"source": source, "target": target, "kind": kind}
        for source, target, kind in sorted(edges)
    ]
