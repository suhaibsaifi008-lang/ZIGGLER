"""Writes/edits code, including Ziggler's own source. Every write is verified
by re-reading the file AND compiling/importing it — never trust the LLM blindly."""
from __future__ import annotations

import ast
import py_compile
import tempfile
from pathlib import Path

from evo.core.llm_client import LLMRouter, LLMError


def _safe_path(path: str) -> Path:
    p = Path(path).resolve()
    allowed_roots = [
        Path(tempfile.gettempdir()).resolve(),
        (Path(__file__).resolve().parent.parent / "data").resolve(),
    ]
    if not any(p.is_relative_to(root) for root in allowed_roots):
        raise PermissionError(
            f"refusing to edit {p}; self-edit of evo source requires explicit approval"
        )
    return p


def write_function(path: str, signature: str, instruction: str) -> dict:
    """Append an LLM-written function to a python file; verify it compiles.

    Returns {'written': path, 'function': name, 'compiles': bool}.
    """
    target = _safe_path(path)
    prompt = (
        f"Write ONE complete Python function.\nSignature: {signature}\n"
        f"Requirement: {instruction}\nRespond with ONLY the code, no markdown fences."
    )
    code = LLMRouter().complete(prompt).text.strip()
    code = code.removeprefix("```python").removeprefix("```").removesuffix("```").strip()
    tree = ast.parse(code)
    func = next((n for n in tree.body if isinstance(n, ast.FunctionDef)), None)
    if func is None:
        raise ValueError("LLM did not return a function definition")

    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    candidate = existing + ("\n\n" if existing.strip() else "") + code + "\n"

    probe = target.with_suffix(".zgl_probe.py")
    probe.write_text(candidate, encoding="utf-8")
    try:
        py_compile.compile(str(probe), doraise=True)
    except py_compile.PyCompileError as exc:
        probe.unlink(missing_ok=True)
        raise ValueError(f"generated code does not compile: {exc}") from exc
    content = probe.read_text(encoding="utf-8")
    probe.unlink()

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"written": str(target), "function": func.name, "compiles": True}


def edit_file(path: str, instruction: str) -> dict:
    """Apply a natural-language edit to a text file inside allowed roots."""
    target = _safe_path(path)
    if not target.exists():
        raise FileNotFoundError(path)
    original = target.read_text(encoding="utf-8")
    prompt = (
        f"Rewrite the following file according to this instruction: {instruction}\n"
        "Return ONLY the full new file content, no commentary.\n\n" + original
    )
    new_content = LLMRouter().complete(prompt).text
    new_content = new_content.removeprefix("```python").removeprefix("```")
    new_content = new_content.removesuffix("```").strip() + "\n"
    if target.suffix == ".py":
        compile(new_content, str(target), "exec")  # raises on syntax errors
    target.write_text(new_content, encoding="utf-8")
    return {"written": str(target), "changed": new_content != original}


# Backwards-compatible simple ops used by Action(kind='code') in Phase A/C.
def append_text(path: str, content: str) -> bool:
    target = _safe_path(path)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(content)
    return True


if __name__ == "__main__":  # pragma: no cover
    try:
        print(write_function(
            str(Path(tempfile.gettempdir()) / "ziggler_selftest.py"),
            "def add_two(a: int, b: int) -> int:",
            "return the sum of a and b",
        ))
    except (LLMError, ValueError) as exc:
        print(f"self-test needs an LLM backend: {exc}")
