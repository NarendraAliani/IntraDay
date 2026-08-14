#!/usr/bin/env python3
"""docs/user-guide/validate.py

Checkpoint 25: lightweight, dependency-free documentation validation
for the Dynamic Digital Tutorial Guide. Deliberately NOT a new testing
framework - plain stdlib only (re, pathlib, html.parser), runnable
directly (`python docs/user-guide/validate.py`) or via the thin pytest
wrapper at tests/unit/documentation/test_user_guide.py.

Checks:
  1. index.html exists and is well-formed enough to parse.
  2. Every referenced local CSS/JS/asset file actually exists on disk.
  3. Every internal anchor link (href="#section-id") points at a real
     section id that exists in the document.
  4. No JWT-shaped or other credential-shaped strings appear anywhere
     in the guide (secret-pattern scan).
  5. No literal "TODO"/"FIXME" placeholder text was left in.

Exits non-zero (and prints every failure, not just the first) if any
check fails - suitable for both interactive use and CI/pytest.
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

GUIDE_DIR = Path(__file__).resolve().parent
INDEX_HTML = GUIDE_DIR / "index.html"

# Checkpoint 24A/22's own established secret-pattern vocabulary - a JWT
# has three base64url segments separated by dots; also catch generic
# "token"/"password"/"secret" assignments with a suspiciously long value.
JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
SUSPICIOUS_ASSIGNMENT = re.compile(
    r"(?i)(access[_-]?token|api[_-]?key|secret|password)\s*[:=]\s*['\"][A-Za-z0-9+/=_-]{16,}['\"]"
)
PLACEHOLDER_PATTERN = re.compile(r"\b(TODO|FIXME|XXX)\b")


class GuideParser(HTMLParser):
    """Collects every element id (for internal-link validation) and
    every local asset reference (href/src pointing at a relative,
    non-external path)."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.hrefs: list[str] = []
        self.asset_refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        element_id = attr_dict.get("id")
        if element_id:
            self.ids.add(element_id)
        href = attr_dict.get("href")
        if href:
            self.hrefs.append(href)
            if tag == "link" and not _is_external(href):
                self.asset_refs.append(href)
        src = attr_dict.get("src")
        if src and not _is_external(src):
            self.asset_refs.append(src)


def _is_external(url: str) -> bool:
    return url.startswith(("http://", "https://", "mailto:", "//"))


def validate() -> list[str]:
    errors: list[str] = []

    if not INDEX_HTML.is_file():
        return [f"index.html not found at {INDEX_HTML}"]

    html_text = INDEX_HTML.read_text(encoding="utf-8")

    parser = GuideParser()
    parser.feed(html_text)

    # --- Check 2: local assets referenced actually exist -------------
    for ref in parser.asset_refs:
        resolved = (GUIDE_DIR / ref).resolve()
        if not resolved.is_file():
            errors.append(f"referenced local asset does not exist: {ref!r} (resolved: {resolved})")

    # --- Check 3: internal anchor links resolve to real section ids ---
    for href in parser.hrefs:
        if href.startswith("#") and len(href) > 1:
            target = href[1:]
            if target not in parser.ids:
                errors.append(
                    f'internal link href={href!r} has no matching id="{target}" in the document'
                )

    # --- Check 4: no credential-shaped strings anywhere in the guide --
    for asset_name, text in _all_guide_text():
        if JWT_PATTERN.search(text):
            errors.append(
                f"{asset_name}: contains a JWT-shaped string - possible leaked credential"
            )
        for match in SUSPICIOUS_ASSIGNMENT.finditer(text):
            errors.append(
                f"{asset_name}: contains a suspicious credential-shaped assignment near "
                f"{match.group(0)[:40]!r}"
            )

    # --- Check 5: no leftover placeholder markers ----------------------
    for asset_name, text in _all_guide_text():
        if PLACEHOLDER_PATTERN.search(text):
            errors.append(f"{asset_name}: contains a TODO/FIXME/XXX placeholder marker")

    return errors


def _all_guide_text() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for path in GUIDE_DIR.rglob("*"):
        if path.is_file() and path.suffix in (".html", ".css", ".js", ".md"):
            results.append((str(path.relative_to(GUIDE_DIR)), path.read_text(encoding="utf-8")))
    return results


def main() -> int:
    errors = validate()
    if errors:
        print(f"FAILED: {len(errors)} documentation validation issue(s) found:\n")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("OK: documentation validation passed.")
    print("No broken links, missing assets, or leaked secrets found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
