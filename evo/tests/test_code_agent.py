"""Phase F live acceptance for code_agent (uses the local LLM router).
Runs a real generated function and executes it in a subprocess."""
import subprocess
import sys
from pathlib import Path

import pytest

from evo.coder import code_agent
from evo.core.llm_client import LLMRouter


def _backend_ready() -> bool:
    try:
        return LLMRouter().is_available()
    except Exception:
        return False


@pytest.mark.skipif(not _backend_ready(), reason="no LLM backend available")
def test_write_function_writes_and_compiles(tmp_path):
    target = tmp_path / "generated.py"
    result = code_agent.write_function(
        str(target),
        "def multiply(a: float, b: float) -> float:",
        "return a multiplied by b",
    )
    assert result["compiles"] is True
    assert result["function"] == "multiply"
    source = Path(result["written"]).read_text(encoding="utf-8")
    assert "def multiply" in source

    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys\n"
        f"sys.path.insert(0, r'{tmp_path}')\n"
        "import generated\n"
        "assert abs(generated.multiply(6, 7) - 42) < 1e-9\n"
        "print('EXEC OK')\n",
        encoding="utf-8",
    )
    out = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, timeout=60)
    assert "EXEC OK" in out.stdout, out.stderr


def test_safe_path_blocks_source_edits():
    with pytest.raises(PermissionError):
        code_agent._safe_path(str(Path(__file__).with_name("orchestrator.py")))
