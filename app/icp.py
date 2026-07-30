"""Loads icp_profile.yaml and renders it for the system prompt.

The YAML is rendered back to YAML rather than being templated into prose: it keeps
the structure the model can reason over, and it means adding a new key to the file
needs no code change here.
"""

from functools import lru_cache
from pathlib import Path

import yaml

ICP_PATH = Path(__file__).resolve().parent.parent / "icp_profile.yaml"


@lru_cache
def load_icp() -> dict:
    if not ICP_PATH.exists():
        raise FileNotFoundError(
            f"icp_profile.yaml not found at {ICP_PATH}. The agent cannot score leads "
            "without an ICP definition."
        )
    with ICP_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not data:
        raise ValueError("icp_profile.yaml is empty")
    return data


@lru_cache
def render_icp() -> str:
    return yaml.safe_dump(load_icp(), sort_keys=False, allow_unicode=True, width=100)


def company_name() -> str:
    return load_icp().get("company", "our company")
