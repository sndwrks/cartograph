"""The knowledge-base type registry.

Types are code, not data. Adding one is a module plus a line here — never a
migration and never an `ALTER TYPE`, which is why `KnowledgeEntry.type` is
`Text` rather than `sa.Enum`.
"""

from __future__ import annotations

from cartograph.kb.types.base import (
    LOOKUP_KEYS,
    MARKER_PREFIX,
    ExportContext,
    KbType,
    LookupKey,
)
from cartograph.kb.types.convention import Convention, ConventionExample
from cartograph.kb.types.decision import Decision
from cartograph.kb.types.glossary import Glossary
from cartograph.kb.types.runbook import Runbook
from cartograph.kb.types.specification import Specification

REGISTRY: dict[str, type[KbType]] = {
    t.name: t for t in (Glossary, Convention, Decision, Specification, Runbook)
}

#: Which type wins when one term resolves in more than one. Glossary first
#: because acronym disambiguation is the use CLAUDE.md mandates. Total order,
#: so an untyped lookup has no tie-break left to get wrong.
LOOKUP_PRECEDENCE: tuple[str, ...] = (
    "glossary",
    "convention",
    "decision",
    "specification",
    "runbook",
)

DEFAULT_TYPE = "glossary"


class UnknownKbTypeError(KeyError):
    """Raised for a `type` that is not a registry key."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name

    def __str__(self) -> str:
        return f"unknown kb type {self.name!r}"


def get_type(name: str) -> type[KbType]:
    try:
        return REGISTRY[name]
    except KeyError:
        raise UnknownKbTypeError(name) from None


def type_names() -> tuple[str, ...]:
    """Registry keys in lookup-precedence order."""
    return LOOKUP_PRECEDENCE


def types_with_lookup_key(key: LookupKey) -> tuple[str, ...]:
    """Type names that answer lookup on `key`, in precedence order."""
    return tuple(n for n in LOOKUP_PRECEDENCE if key in REGISTRY[n].lookup_keys)


def type_rank(name: str) -> int:
    """Position in LOOKUP_PRECEDENCE; unknown types sort last."""
    try:
        return LOOKUP_PRECEDENCE.index(name)
    except ValueError:
        return len(LOOKUP_PRECEDENCE)


def _self_check() -> None:
    """Fail at import rather than at the first request against a bad registry."""
    for key, kb_type in REGISTRY.items():
        if kb_type.name != key:
            raise RuntimeError(f"registry key {key!r} != {kb_type.name!r}")
        if key not in LOOKUP_PRECEDENCE:
            raise RuntimeError(f"{key!r} missing from LOOKUP_PRECEDENCE")
        if not kb_type.lookup_keys:
            raise RuntimeError(f"{key!r} declares no lookup_keys")
        for lookup_key in kb_type.lookup_keys:
            if lookup_key not in LOOKUP_KEYS:
                raise RuntimeError(f"{key!r} has invalid lookup key {lookup_key!r}")
        directory = kb_type.export_dir
        if directory is not None:
            if directory.startswith("/") or ".." in directory.split("/"):
                raise RuntimeError(f"{key!r} export_dir must be relative: {directory!r}")
    missing = set(LOOKUP_PRECEDENCE) - set(REGISTRY)
    if missing:
        raise RuntimeError(f"LOOKUP_PRECEDENCE names unregistered types: {sorted(missing)}")


_self_check()

__all__ = [
    "DEFAULT_TYPE",
    "LOOKUP_PRECEDENCE",
    "MARKER_PREFIX",
    "REGISTRY",
    "Convention",
    "ConventionExample",
    "Decision",
    "ExportContext",
    "Glossary",
    "KbType",
    "LookupKey",
    "Runbook",
    "Specification",
    "UnknownKbTypeError",
    "get_type",
    "type_names",
    "type_rank",
    "types_with_lookup_key",
]
