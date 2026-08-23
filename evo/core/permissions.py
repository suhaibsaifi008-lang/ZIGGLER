"""Tiered permission system (3-tier design carried over from the Pluton work)."""
from __future__ import annotations


TIERS = ("read_only", "confirmed", "autonomous")

GRANTS_PATH = "permissions.json"


def check(action_kind: str, tier: str) -> bool:
    raise NotImplementedError("permissions gate wires into orchestrator in Phase C+")


def grant(action_kind: str, tier: str) -> None:
    raise NotImplementedError("permissions gate wires into orchestrator in Phase C+")
