"""Template and view engine detection: file globs, content signals, manifest signals.

Every signal is `{path, line, rule}`. Confidence follows the strongest signal of
an engine: a file-level signal is `high`, a dependency declaration `medium`, a bare
`$(` usage `low`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

EXCLUDE_DIRS = {
    "node_modules", "vendor", "dist", "build", "target", ".extract", ".git", "graft",
    "graphify-out", ".serena",
}
MAX_BYTES = 1_000_000
RANK = {"low": 0, "medium": 1, "high": 2}

MARKUP_SUFFIXES = {".html", ".htm", ".ftl", ".ftlh", ".mustache", ".hbs", ".handlebars", ".peb", ".pebble"}
SCRIPT_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue"}
SCANNED_SUFFIXES = MARKUP_SUFFIXES | SCRIPT_SUFFIXES

# Dependency names to engine id. Matched case-insensitively as a substring of the
# artifact name, so `com.enonic.lib:lib-thymeleaf` and `thymeleaf-spring5` both count.
DEPENDENCY_ENGINES: tuple[tuple[str, str], ...] = (
    ("thymeleaf", "thymeleaf"),
    ("freemarker", "freemarker"),
    ("mustache", "mustache"),
    ("handlebars", "handlebars"),
    ("pebble", "pebble"),
    ("react4xp", "react"),
)
PACKAGE_ENGINES = {
    "react": "react", "react-dom": "react", "next": "nextjs", "vue": "vue",
    "@angular/core": "angular", "jquery": "jquery", "handlebars": "handlebars",
    "mustache": "mustache",
}

_TH_ATTR = re.compile(r"""xmlns:th\s*=|<[A-Za-z][^<>]*?\s(?:th:[a-z]+|data-th-[a-z]+)\s*=""")
_FTL = re.compile(r"</?#[a-z]+|</?@[\w.]+")
_MUSTACHE = re.compile(r"\{\{\s*[#^>/]")
_PEBBLE = re.compile(r"\{%\s*(?:if|for|include|extends|block|set)\b")
_JSX = re.compile(r"<[A-Z][\w.]*(?:\s|/|>)|</[A-Za-z][\w.]*>|<>|<[a-z]+[^>\n]*\{")
_JQUERY_USE = re.compile(r"(?<![\w$.])(?:\$|jQuery)\s*\(")
_JQUERY_SRC = re.compile(r"""<script[^>]+src\s*=\s*["'][^"']*jquery[^"']*["']""", re.IGNORECASE)
_ANGULAR_COMPONENT = re.compile(r"@Component\s*\(")
_HELPERS = re.compile(r"\bregisterHelper\s*\(")


@dataclass
class Detection:
    engine: str
    framework: str | None
    confidence: str
    signals: list[dict]
    role: str = "template"  # template | script


@dataclass
class Project:
    """Manifest signals per directory that declares a manifest."""

    roots: dict[str, dict[str, list[dict]]] = field(default_factory=dict)

    def add(self, directory: str, engine: str, signal: dict) -> None:
        self.roots.setdefault(directory, {}).setdefault(engine, []).append(signal)

    def engines_for(self, rel: str) -> dict[str, list[dict]]:
        """Signals of the closest ancestor directory that has any; root last."""
        parts = rel.split("/")[:-1]
        for depth in range(len(parts), -1, -1):
            directory = "/".join(parts[:depth])
            if directory in self.roots:
                return self.roots[directory]
        return {}

    def all_signals(self) -> Iterator[tuple[str, dict]]:
        for engines in self.roots.values():
            for engine, signals in engines.items():
                for signal in signals:
                    yield engine, signal


def iter_source_files(source: Path) -> Iterator[Path]:
    """Files under `source`, excluded folders pruned, sorted for stable output."""
    stack = [source]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in EXCLUDE_DIRS:
                    stack.append(entry)
            elif entry.is_file():
                yield entry


def rel_path(source: Path, path: Path) -> str:
    return path.relative_to(source).as_posix()


def _line_of(text: str, needle: str) -> int:
    index = text.find(needle)
    return text.count("\n", 0, index) + 1 if index >= 0 else 1


def _manifest_signals(rel: str, text: str) -> list[tuple[str, dict]]:
    name = rel.rsplit("/", 1)[-1]
    found: list[tuple[str, dict]] = []
    if name == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            return found
        deps: dict = {}
        for key in ("dependencies", "devDependencies"):
            if isinstance(data.get(key), dict):
                deps.update(data[key])
        for package, engine in PACKAGE_ENGINES.items():
            if package in deps:
                found.append((engine, {
                    "path": rel, "line": _line_of(text, f'"{package}"'),
                    "rule": f"package.json dependency {package}", "strength": "medium",
                }))
    elif name in ("pom.xml", "build.gradle", "build.gradle.kts"):
        for needle, engine in DEPENDENCY_ENGINES:
            match = re.search(rf"[\w.:/-]*{needle}[\w.:/-]*", text, re.IGNORECASE)
            if match:
                found.append((engine, {
                    "path": rel, "line": text.count("\n", 0, match.start()) + 1,
                    "rule": f"{name} dependency {match.group(0)}", "strength": "medium",
                }))
    elif name == "angular.json":
        found.append(("angular", {"path": rel, "line": 1, "rule": "angular.json", "strength": "high"}))
    elif re.fullmatch(r"next\.config\.(?:js|mjs|cjs|ts)", name):
        found.append(("nextjs", {"path": rel, "line": 1, "rule": name, "strength": "high"}))
    return found


def build_project(source: Path, files: list[Path]) -> Project:
    project = Project()
    for path in files:
        rel = rel_path(source, path)
        if path.name not in {"package.json", "pom.xml", "build.gradle", "build.gradle.kts", "angular.json"} \
                and not path.name.startswith("next.config."):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        directory = rel.rsplit("/", 1)[0] if "/" in rel else ""
        for engine, signal in _manifest_signals(rel, text):
            project.add(directory, engine, signal)
    return project


def _signal(rel: str, text: str, pattern: re.Pattern[str], rule: str) -> dict | None:
    match = pattern.search(text)
    if match is None:
        return None
    return {"path": rel, "line": text.count("\n", 0, match.start()) + 1, "rule": rule}


def _suffix_signal(rel: str, rule: str) -> dict:
    return {"path": rel, "line": 1, "rule": rule}


def _next_router(rel: str) -> bool:
    parts = rel.split("/")[:-1]
    return "pages" in parts or "app" in parts


def classify_file(
    rel: str,
    text: str,
    project: Project,
    bindings: dict[str, str],
    react4xp_refs: set[str],
) -> Detection | None:
    """Engine of one file, or None when it is not a template or view script."""
    name = rel.rsplit("/", 1)[-1]
    lower = name.lower()
    if ".test." in lower or ".spec." in lower or lower.endswith(".d.ts") or ".min." in lower:
        return None
    suffix = Path(name).suffix.lower()
    context = project.engines_for(rel)

    if suffix in (".ftl", ".ftlh"):
        return Detection("freemarker", None, "high", [_suffix_signal(rel, f"*{suffix}")])
    if suffix == ".mustache":
        return Detection("mustache", None, "high", [_suffix_signal(rel, "*.mustache")])
    if suffix in (".hbs", ".handlebars"):
        return Detection("handlebars", None, "high", [_suffix_signal(rel, f"*{suffix}")])
    if suffix in (".peb", ".pebble"):
        return Detection("pebble", None, "high", [_suffix_signal(rel, f"*{suffix}")])
    if suffix == ".vue":
        return Detection("vue", None, "high", [_suffix_signal(rel, "*.vue")])
    if lower.endswith(".component.html"):
        return Detection("angular", None, "high", [_suffix_signal(rel, "*.component.html")])

    if suffix in (".html", ".htm"):
        if rel in bindings:
            engine = bindings[rel]
            return Detection(
                engine, None, "high", [_suffix_signal(rel, f"controller render binding ({engine})")],
            )
        for pattern, engine, rule in (
            (_TH_ATTR, "thymeleaf", "th:* attribute"),
            (_FTL, "freemarker", "FreeMarker directive"),
        ):
            hit = _signal(rel, text, pattern, rule)
            if hit:
                return Detection(engine, None, "high", [hit])
        family = "handlebars" if "handlebars" in context else "mustache" if "mustache" in context else None
        hit = _signal(rel, text, _MUSTACHE, "{{#section}} or {{>partial}}")
        if hit and family:
            return Detection(family, None, "medium", [hit])
        hit = _signal(rel, text, _PEBBLE, "{% tag %}")
        if hit and "pebble" in context:
            return Detection("pebble", None, "medium", [hit])
        hit = _signal(rel, text, _JQUERY_SRC, "<script src=jquery>")
        if hit:
            return Detection("jquery", None, "high", [hit])
        return None

    if suffix in (".jsx", ".tsx"):
        hit = _signal(rel, text, _JSX, "JSX markup")
        if hit is None:
            return None
        framework = None
        if "nextjs" in context and _next_router(rel):
            framework = "nextjs"
        elif Path(rel).stem in react4xp_refs or "react4xp" in rel.lower():
            framework = "react4xp"
        return Detection("react", framework, "high", [hit])

    if suffix in (".js", ".mjs", ".ts"):
        hit = _signal(rel, text, _ANGULAR_COMPONENT, "@Component(")
        if hit:
            return Detection("angular", None, "high", [hit], role="template")
        hit = _signal(rel, text, _HELPERS, "registerHelper(")
        if hit:
            return Detection("handlebars", None, "high", [hit], role="script")
        hit = _signal(rel, text, _JQUERY_USE, "$( or jQuery( usage")
        if hit:
            confidence = "medium" if "jquery" in context else "low"
            return Detection("jquery", None, confidence, [hit], role="script")
    return None


def engines_report(detections: dict[str, Detection], project: Project) -> list[dict]:
    """One row per engine: strongest confidence, signals, and file count.

    A file under a framework (`nextjs`, `react4xp`) counts for both its engine and
    the framework, so Next.js also records React.
    """
    signals: dict[str, list[tuple[str, dict]]] = {}
    files: dict[str, int] = {}
    for detection in detections.values():
        for key in (detection.engine, detection.framework):
            if not key:
                continue
            files[key] = files.get(key, 0) + 1
            signals.setdefault(key, []).extend((detection.confidence, s) for s in detection.signals)
    for engine, signal in project.all_signals():
        signals.setdefault(engine, []).append((signal["strength"], {
            key: signal[key] for key in ("path", "line", "rule")
        }))
    rows: list[dict] = []
    for engine in sorted(signals):
        best = max((strength for strength, _ in signals[engine]), key=RANK.__getitem__)
        unique: list[dict] = []
        for _, signal in sorted(signals[engine], key=lambda s: (s[1]["path"], s[1]["line"], s[1]["rule"])):
            if signal not in unique:
                unique.append(signal)
        rows.append({
            "id": engine, "confidence": best, "files": files.get(engine, 0), "signals": unique[:10],
        })
    return rows
