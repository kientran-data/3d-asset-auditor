"""Ruleset configuration loader and canonical hash computation."""
import hashlib
import json
import os
from typing import Dict, Any, Tuple


_RULESET_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_RULESET = os.path.join(_RULESET_DIR, "technical_marketplace_v1.json")


def load_ruleset(path: str = _DEFAULT_RULESET) -> Dict[str, Any]:
    """Load and parse a ruleset JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_ruleset_hash(ruleset_data: Dict[str, Any]) -> str:
    """Compute a deterministic SHA256 hash of the ruleset configuration.

    The hash is computed from canonical JSON serialization (sorted keys,
    fixed separators, UTF-8) so that whitespace/key-order changes alone
    do not alter the hash, but any behavioural config change does.
    """
    canonical = json.dumps(
        ruleset_data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_ruleset_with_hash(path: str = _DEFAULT_RULESET) -> Tuple[Dict[str, Any], str, str]:
    """Return (ruleset_data, ruleset_version, ruleset_hash)."""
    data = load_ruleset(path)
    version = data.get("ruleset_version", "unknown")
    rhash = compute_ruleset_hash(data)
    return data, version, rhash


def get_enabled_rules(ruleset_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return only enabled rules from the ruleset."""
    return {
        code: cfg
        for code, cfg in ruleset_data.get("rules", {}).items()
        if cfg.get("enabled", False)
    }
