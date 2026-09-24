"""Language extractors and the tier-1 resolver (slices 03/04)."""

from . import python, rust, typescript
from .base import (
    Extractor,
    FileExtraction,
    ImportRecord,
    RefRecord,
    SymbolRecord,
    get_extractor_for,
    hash_content,
    register,
)
from .resolve import CandidateEdge, resolve

register(python.PythonExtractor())
register(typescript.TypeScriptExtractor())
register(rust.RustExtractor())

__all__ = [
    "CandidateEdge",
    "Extractor",
    "FileExtraction",
    "ImportRecord",
    "RefRecord",
    "SymbolRecord",
    "get_extractor_for",
    "hash_content",
    "register",
    "resolve",
]
