"""Template rendering with ``{variable}`` substitution."""

from __future__ import annotations

import re
from typing import Any

#: ``{name}`` or ``{name:default}``.  Names may contain word chars and dots.
_VAR_RE = re.compile(r"\{(\s*[\w.\-]+\s*(?::[^}]*)?)\}")


def variable_names(body: str) -> list[str]:
    """The ordered, unique variable names used by *body*."""
    names: list[str] = []
    for match in _VAR_RE.finditer(body or ""):
        name = match.group(1).split(":", 1)[0].strip()
        if name not in names:
            names.append(name)
    return names


def render(body: str, **variables: Any) -> str:
    """Substitute ``{var}`` placeholders in *body*.

    Missing variables fall back to ``{default}`` when one is given,
    otherwise they are left untouched so a typo is visible.
    """

    def _sub(match: re.Match) -> str:
        spec = match.group(1).strip()
        name, _, default = spec.partition(":")
        name = name.strip()
        default = default.strip()
        value = variables.get(name)
        if value is None:
            return default if default else match.group(0)
        return str(value)

    return _VAR_RE.sub(_sub, body or "")


def render_from_dict(body: str, variables: dict[str, Any]) -> str:
    return render(body, **variables)


def substitute_pairs(body: str, pairs: dict[str, str]) -> str:
    return render(body, **pairs)
