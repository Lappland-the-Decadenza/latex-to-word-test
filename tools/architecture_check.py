"""Static architecture ratchets for the codebase-separation plan.

This checker is deliberately independent of ``latexword``.  It reads Python
source with :mod:`ast`, so importing the converter cannot hide a boundary
violation behind import-time side effects.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT_PACKAGE = "latexword"
MAX_FILE_LINES = 400
SOFT_FILE_LINES = 250
WAIVER_RE = re.compile(
    r"architecture-waiver:\s*([A-Z0-9_-]+)\s+(.+?)\s+expires=(stage-[1-4])\s*$"
)
MARKERS = ("# architecture: declarative-table", "# architecture: generated")
REMOVED_CARRIERS = {
    r"\hlight": "native highlight forms must replace the Word carrier",
    r"\wordemptyparagraph": "native paragraph structure must replace the Word carrier",
    r"\wstyle": "style identity belongs in the sidecar",
    r"\wrstyle": "character style identity belongs in the sidecar",
    r"\wordfield": "unknown field instructions belong in the sidecar",
    r"\wordimage": "image metadata belongs in the sidecar",
    r"\wordobject": "opaque object identity belongs in the sidecar",
    r"\wordcontent": "content controls belong in the sidecar",
    r"\wordtextbox": "text-box identity belongs in the sidecar",
    r"\wordtable": "table shape belongs in the sidecar",
    r"\wordvanish": "hidden-run state belongs in the sidecar",
    r"\linfrac": "native fraction notation must replace the carrier",
    r"\skwfrac": "native fraction notation must replace the carrier",
    r"\nobarfrac": "native fraction notation must replace the carrier",
}

# Names are package namespaces, not individual modules.  ``math.latex`` and
# ``math.omml`` are separate namespaces because their mutual dependency is the
# specific split this plan must protect.
FORBIDDEN_EDGES = {
    "document": {"latex", "math", "docx", "sidecar", "workspace", "project", "symbols"},
    "latex": {"docx", "sidecar", "workspace", "project"},
    "math.latex": {"math.omml", "docx", "sidecar", "workspace", "project"},
    "math.omml": {"math.latex", "latex", "sidecar", "workspace", "project"},
    "docx": {"latex", "project", "workspace"},
    "sidecar": {"latex", "docx", "workspace", "project"},
    "symbols": {"document", "latex", "math", "docx", "sidecar", "workspace", "project"},
    "project": {"workspace"},
    "workspace": {"project", "session", "cli", "rpc"},
    "session": {"cli", "rpc"},
    "math.api": set(),
    "math.shared": set(),
}

# A physical move changes the path while the implementation itself is being
# separated.  Keep the existing size ratchet attached to the old owner until
# the move has settled; this prevents a split from accidentally becoming an
# excuse to grow a load-bearing implementation.
MOVED_BASELINES = {
    "latexword/math/latex/parse.py": "latexword/math/parse.py",
    "latexword/math/latex/serialize.py": "latexword/math/serialize.py",
    "latexword/math/latex/tokenize.py": "latexword/math/tokenize.py",
    "latexword/math/latex/macros.py": "latexword/math/macros.py",
    "latexword/math/omml/emit.py": "latexword/math/emit.py",
    "latexword/math/omml/load.py": "latexword/math/load.py",
}

FACADE_PATHS = {
    "latexword/docx/read.py",
    "latexword/docx/write.py",
    "latexword/math/latex2omml.py",
    "latexword/math/omml2latex.py",
    "latex2word.py",
    "word2latex.py",
}
CLI_PATHS = {"latex2word.py", "word2latex.py"}

# These are declarations, rather than filename conventions.  A declaration
# may move only after its destination exists; once it does, this table also
# prevents a compatibility copy from surviving the move.
DECLARATION_OWNERS = {
    "node_id": ("latexword.document.identity", {"NodeId"}),
    "diagnostics": (
        "latexword.document.diagnostics",
        {"Diagnostic", "DiagnosticCode", "Severity", "SourceReference"},
    ),
    "document_model": ("latexword.document.model", {"Document"}),
    "sidecar_store": ("latexword.sidecar.store", {"ObjectStore"}),
    "numbering": (
        "latexword.docx.numbering",
        {
            "NumberingSpec",
            "NumberingRule",
            "NumFmt",
            "NUMFMT_TO_LABEL",
            "LABEL_TO_NUMFMT",
            "ENUM_DEFAULT_NUMFMT_BY_DEPTH",
        },
    ),
    "style_roles": (
        "latexword.docx.styles",
        {"StyleRole", "StyleIdentity", "SemanticRole"},
    ),
    "math_constructs": (
        "latexword.math.ast",
        {"MathNode", "ConstructSpec", "MATH_CONSTRUCTS"},
    ),
    "symbols": (
        "latexword.symbols.registry",
        {"SYMBOL_MAP", "SYMBOL_REGISTRY", "SYMBOLS"},
    ),
    "formatting": (
        "latexword.document.formatting",
        {
            "Formatting",
            "CharacterFormatting",
            "ParagraphFormatting",
            "RunFormat",
            "ParagraphFormat",
        },
    ),
}


@dataclass(frozen=True)
class Source:
    path: Path
    relative: str
    module: str | None
    tree: ast.Module
    text: str


@dataclass(frozen=True)
class Violation:
    code: str
    relative: str
    line: int
    message: str

    def __str__(self) -> str:
        location = f"{self.relative}:{self.line}" if self.line else self.relative
        return f"{self.code} {location} {self.message}"


def module_for_path(root: Path, path: Path) -> str | None:
    """Return a dotted module name for a package source file."""
    try:
        relative = path.relative_to(root).with_suffix("")
    except ValueError:
        return None
    parts = list(relative.parts)
    if not parts or parts[0] != ROOT_PACKAGE:
        return None
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or ROOT_PACKAGE


def discover_sources(root: Path) -> tuple[list[Source], list[Violation]]:
    sources: list[Source] = []
    violations: list[Violation] = []
    paths = sorted(root.joinpath(ROOT_PACKAGE).rglob("*.py"))
    paths += [root / name for name in sorted(CLI_PATHS)]
    for path in paths:
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=relative)
        except SyntaxError as error:
            violations.append(
                Violation("SYNTAX", relative, error.lineno or 1, str(error))
            )
            continue
        sources.append(Source(path, relative, module_for_path(root, path), tree, text))
    return sources, violations


def package_namespace(module: str | None) -> str | None:
    if not module or module == ROOT_PACKAGE:
        return None
    parts = module.split(".")
    if len(parts) >= 3 and parts[1] == "math":
        if parts[2] in {"latex", "omml"}:
            return f"math.{parts[2]}"
        if parts[2] in {"ast", "common", "errors"}:
            return "math.shared"
        return "math.api"
    return parts[1] if len(parts) > 1 else None


def source_is_exempt(source: Source) -> bool:
    return any(line.strip() in MARKERS for line in source.text.splitlines()[:20])


def logical_line_count(text: str, start: int = 1, end: int | None = None) -> int:
    lines = text.splitlines()
    end = len(lines) if end is None else min(end, len(lines))
    return sum(
        bool(line.strip()) and not line.lstrip().startswith("#")
        for line in lines[max(0, start - 1) : end]
    )


def function_nodes(tree: ast.AST) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}.{child.name}" if prefix else child.name
                found.append((name, child))
                visit(child, name)
            elif isinstance(child, ast.ClassDef):
                name = f"{prefix}.{child.name}" if prefix else child.name
                visit(child, name)
            else:
                visit(child, prefix)

    visit(tree, "")
    return found


def git_source(root: Path, relative: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return None
    return result.stdout.decode("utf-8")


def baseline_function_sizes(root: Path, relative: str) -> dict[str, int]:
    text = git_source(root, relative)
    if text is None:
        return {}
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError:
        return {}
    return {
        name: logical_line_count(text, node.lineno, node.end_lineno)
        for name, node in function_nodes(tree)
    }


def collect_waivers(sources: list[Source]) -> tuple[dict[tuple[str, int, str], str], list[Violation]]:
    waivers: dict[tuple[str, int, str], str] = {}
    violations: list[Violation] = []
    for source in sources:
        for line_number, line in enumerate(source.text.splitlines(), 1):
            if "architecture-waiver:" not in line:
                continue
            match = WAIVER_RE.search(line)
            if not match:
                violations.append(
                    Violation(
                        "WAIVER_INVALID",
                        source.relative,
                        line_number,
                        "waivers need a code, reason, and expires=stage-N",
                    )
                )
                continue
            code, reason, _expiry = match.groups()
            waivers[(source.relative, line_number, code)] = reason.strip()
    return waivers, violations


def import_targets(source: Source, known_modules: set[str]) -> set[str]:
    if source.module is None:
        return set()
    current = source.module.split(".")
    targets: set[str] = set()
    for node in ast.walk(source.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(ROOT_PACKAGE):
                    targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = current[:-node.level]
                prefix = base + (node.module.split(".") if node.module else [])
                if node.module:
                    candidate = ".".join(prefix)
                    if candidate in known_modules:
                        targets.add(candidate)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    candidate = ".".join(prefix + [alias.name])
                    if candidate in known_modules:
                        targets.add(candidate)
            elif node.module and node.module.startswith(ROOT_PACKAGE):
                targets.add(node.module)
                for alias in node.names:
                    candidate = f"{node.module}.{alias.name}"
                    if candidate in known_modules:
                        targets.add(candidate)
    return targets


def check_imports(sources: list[Source]) -> tuple[list[Violation], dict[str, set[str]]]:
    known = {source.module for source in sources if source.module}
    edges: dict[str, set[str]] = {}
    violations: list[Violation] = []
    for source in sources:
        for node in ast.walk(source.tree):
            if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
                violations.append(
                    Violation("WILDCARD_IMPORT", source.relative, node.lineno, "wildcard imports are forbidden")
                )
        if source.module is None:
            continue
        targets = import_targets(source, known)
        edges[source.module] = targets
        source_namespace = package_namespace(source.module)
        for target in targets:
            target_namespace = package_namespace(target)
            if target_namespace in FORBIDDEN_EDGES.get(source_namespace or "", set()):
                violations.append(
                    Violation(
                        "FORBIDDEN_EDGE",
                        source.relative,
                        0,
                        f"{source_namespace} may not import {target_namespace} ({target})",
                    )
                )
    return violations, edges


def cycle_violations(sources: list[Source], edges: dict[str, set[str]]) -> list[Violation]:
    by_module = {source.module: source for source in sources if source.module}
    package_edges: dict[str, set[str]] = {}
    for module, targets in edges.items():
        source_package = package_namespace(module)
        if source_package is None:
            continue
        for target in targets:
            target_package = package_namespace(target)
            if target_package and target_package != source_package:
                package_edges.setdefault(source_package, set()).add(target_package)

    violations: list[Violation] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    reported: set[tuple[str, ...]] = set()

    def visit(package: str, stack: list[str]) -> None:
        if package in visiting:
            cycle = tuple(stack[stack.index(package) :] + [package])
            if cycle not in reported:
                reported.add(cycle)
                module = next(
                    (name for name in by_module if package_namespace(name) == package),
                    ROOT_PACKAGE,
                )
                source = by_module.get(module)
                violations.append(
                    Violation("IMPORT_CYCLE", source.relative if source else ROOT_PACKAGE, 0, " -> ".join(cycle))
                )
            return
        if package in visited:
            return
        visiting.add(package)
        for target in sorted(package_edges.get(package, ())):
            visit(target, stack + [package])
        visiting.remove(package)
        visited.add(package)

    for package in sorted(package_edges):
        visit(package, [])
    return violations


def declaration_violations(root: Path, sources: list[Source]) -> list[Violation]:
    locations: dict[str, list[tuple[Source, int]]] = {}
    for source in sources:
        for node in ast.walk(source.tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                locations.setdefault(node.name, []).append((source, node.lineno))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                names = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in names:
                    if isinstance(target, ast.Name):
                        locations.setdefault(target.id, []).append((source, node.lineno))

    violations: list[Violation] = []
    for family, (owner, names) in DECLARATION_OWNERS.items():
        for name in names:
            matches = locations.get(name, [])
            if len(matches) > 1:
                for source, line in matches[1:]:
                    violations.append(
                        Violation(
                            "DUPLICATE_OWNER",
                            source.relative,
                            line,
                            f"{name} duplicates {family}; owner is {owner}",
                        )
                    )
            owner_path = root.joinpath(*owner.split("."))
            owner_path = owner_path.with_suffix(".py")
            if owner_path.is_file():
                for source, line in matches:
                    if source.module != owner:
                        violations.append(
                            Violation(
                                "WRONG_OWNER",
                                source.relative,
                                line,
                                f"{name} belongs in {owner}",
                            )
                        )
    return violations


def facade_violations(sources: list[Source]) -> list[Violation]:
    violations: list[Violation] = []
    for source in sources:
        if source.relative not in FACADE_PATHS:
            continue
        if source.relative in CLI_PATHS:
            for node in source.tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    violations.append(
                        Violation("CLI_ALGORITHM", source.relative, node.lineno, "CLI files may only orchestrate")
                    )
            continue
        for node in source.tree.body:
            if isinstance(node, ast.ClassDef):
                violations.append(
                    Violation("FACADE_ALGORITHM", source.relative, node.lineno, "facades may not define classes")
                )
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # A facade may catch and aggregate adapter errors.  Iteration,
            # matching, and loops are the stronger signal that the facade is
            # still implementing a parser/emitter rather than orchestrating
            # a component owner.
            algorithm_nodes = (ast.For, ast.AsyncFor, ast.While, ast.Match)
            if any(isinstance(child, algorithm_nodes) for child in ast.walk(node)):
                violations.append(
                    Violation(
                        "FACADE_ALGORITHM",
                        source.relative,
                        node.lineno,
                        f"{node.name} contains parsing/emission control flow",
                    )
                )
    return violations


def size_violations(root: Path, sources: list[Source]) -> list[Violation]:
    violations: list[Violation] = []
    for source in sources:
        if source_is_exempt(source):
            continue
        current_lines = logical_line_count(source.text)
        baseline_path = MOVED_BASELINES.get(source.relative, source.relative)
        baseline = git_source(root, baseline_path)
        baseline_lines = logical_line_count(baseline) if baseline is not None else 0
        strict_path = source.relative.startswith(("latexword/workspace/", "latexword/session/", "latexword/cli/"))
        if current_lines > MAX_FILE_LINES and (baseline is None or strict_path):
            violations.append(
                Violation("FILE_TOO_LARGE", source.relative, 1, f"{current_lines} logical lines > hard ceiling {MAX_FILE_LINES}")
            )
        elif current_lines > SOFT_FILE_LINES and baseline is None and not source_is_exempt(source):
            violations.append(
                Violation("FILE_OVER_SOFT", source.relative, 1, f"{current_lines} logical lines > soft ceiling {SOFT_FILE_LINES}; split or justify")
            )
        elif strict_path and baseline_lines > MAX_FILE_LINES and current_lines > baseline_lines:
            violations.append(
                Violation(
                    "FILE_GROWTH",
                    source.relative,
                    1,
                    f"{current_lines} logical lines grew from {baseline_lines} before split",
                )
            )
    return violations


def policy_violations(sources: list[Source]) -> list[Violation]:
    violations = []
    for source in sources:
        if source.relative.startswith("latexword/cli/") or source.relative in CLI_PATHS:
            continue
        for node in ast.walk(source.tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "sys" and node.func.attr == "exit":
                violations.append(Violation("IO_POLICY", source.relative, node.lineno, "sys.exit is below cli/rpc"))
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                violations.append(Violation("IO_POLICY", source.relative, node.lineno, "print is below cli/rpc"))
    return violations


def schema_name_violations(sources: list[Source]) -> list[Violation]:
    values = {}
    for source in sources:
        for node in ast.walk(source.tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                continue
            if not re.fullmatch(r"lw-[a-z0-9-]+/v\d+", node.value.value):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values.setdefault(node.value.value, []).append((source, target.lineno))
    return [
        Violation("DUPLICATE_SCHEMA", source.relative, line, f"schema {value} is also declared elsewhere")
        for value, entries in values.items() for source, line in entries[1:]
    ]


def generic_module_violations(sources: list[Source]) -> list[Violation]:
    return [
        Violation("GENERIC_MODULE", source.relative, 1, "generic utils.py/helpers.py modules are forbidden")
        for source in sources
        if source.path.name in {"utils.py", "helpers.py"}
    ]


def carrier_violations(sources: list[Source]) -> list[Violation]:
    violations = []
    for source in sources:
        if source.relative == "latexword/latex/profile.py":
            continue
        for line_number, line in enumerate(source.text.splitlines(), 1):
            for spelling, message in REMOVED_CARRIERS.items():
                if spelling in line:
                    violations.append(
                        Violation("FORBIDDEN_CARRIER", source.relative, line_number, message)
                    )
    return violations


def check(root: Path) -> list[Violation]:
    sources, violations = discover_sources(root)
    waivers, waiver_violations = collect_waivers(sources)
    violations.extend(waiver_violations)
    import_errors, edges = check_imports(sources)
    violations.extend(import_errors)
    violations.extend(cycle_violations(sources, edges))
    violations.extend(declaration_violations(root, sources))
    violations.extend(facade_violations(sources))
    violations.extend(size_violations(root, sources))
    violations.extend(policy_violations(sources))
    violations.extend(schema_name_violations(sources))
    violations.extend(generic_module_violations(sources))
    violations.extend(carrier_violations(sources))
    return [
        violation
        for violation in violations
        if (violation.relative, violation.line, violation.code) not in waivers
        or violation.code == "WAIVER_INVALID"
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    violations = sorted(check(args.root), key=lambda item: (item.relative, item.line, item.code))
    if violations:
        for violation in violations:
            print(violation)
        print(f"architecture check failed: {len(violations)} violation(s)", file=sys.stderr)
        return 1
    print("architecture check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
