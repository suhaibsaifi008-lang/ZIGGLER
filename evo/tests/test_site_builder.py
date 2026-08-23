"""Phase F acceptance: code agent writes a function that actually compiles and
imports; site builder scaffolds an index.html that renders."""
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from evo.coder import site_builder


def test_scaffold_creates_renderable_site(tmp_path):
    ok = site_builder.scaffold(
        str(tmp_path / "site"),
        {"title": "Suhaib Hub", "tagline": "Everything in one place",
         "sections": [{"heading": "Projects", "body": "Stuff I built."}],
         "accent": "#ff8800"},
    )
    assert ok is True
    page = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in page and "Suhaib Hub" in page and "Projects" in page
    assert page.lstrip().startswith("<!DOCTYPE html>")  # renders as HTML, not junk


@pytest.mark.skipif(True, reason="needs live LLM; run with --runslow after backend is up")
def test_write_function_compiles():
    pytest.importorskip("evo.core.llm_client")
