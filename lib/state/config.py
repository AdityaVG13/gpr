"""User and per-project configuration for gpr.

Two scopes:

1. User-global config at ~/.config/gpr/config.json. Stores defaults
   that follow you across projects: viewer style, spotlight toggle,
   default theme, default agent, default budget.

2. Per-project override at .gpr/viewer-config.json. Anything set here
   trumps the user-global value for that project.

Effective config = user defaults <- project override <- env vars.

Schema is flat dotted keys: 'viewer.style', 'viewer.spotlight',
'viewer.theme', 'run.agent', 'run.deep_audit', etc. See
DEFAULTS dict for the full surface.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULTS: dict[str, Any] = {
    "viewer.style": "editorial",
    "viewer.theme": "paper",
    "viewer.spotlight": True,
    "viewer.scroll_rail": True,
    "viewer.palette": True,
    "viewer.font_size": "default",
    "run.agent": "claude",
    "run.deep_audit": False,
    "run.audit_agent": None,
    "run.max_iters": 50,
}

VALID_STYLES = {"editorial", "terminal", "notebook", "brutalist"}
VALID_THEMES = {"paper", "sepia", "dark", "arctic"}
VALID_FONT_SIZES = {"default", "compact", "large"}


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "gpr" / "config.json"


def project_config_path(project_root: Path | str) -> Path:
    return Path(project_root) / ".gpr" / "viewer-config.json"


def _load(p: Path) -> dict[str, Any]:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(p: Path, data: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(p)


def load_effective(project_root: Path | str | None = None) -> dict[str, Any]:
    """Return the effective config = defaults <- user <- project."""
    cfg = dict(DEFAULTS)
    cfg.update(_load(user_config_path()))
    if project_root is not None:
        cfg.update(_load(project_config_path(project_root)))
    # env overrides
    for k in list(cfg.keys()):
        env_key = "GPR_" + k.upper().replace(".", "_")
        if env_key in os.environ:
            cfg[k] = _coerce(k, os.environ[env_key])
    return cfg


def _coerce(key: str, value: str) -> Any:
    """Coerce a string env value to the type DEFAULTS suggests."""
    default = DEFAULTS.get(key)
    if isinstance(default, bool):
        return value.lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int):
        try:
            return int(value)
        except ValueError:
            return default
    if default is None and value.lower() in {"none", "null", ""}:
        return None
    return value


def get(key: str, project_root: Path | str | None = None) -> Any:
    return load_effective(project_root).get(key, DEFAULTS.get(key))


def set_user(key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise ValueError(f"unknown config key: {key}")
    _validate(key, value)
    p = user_config_path()
    data = _load(p)
    data[key] = value
    _save(p, data)


def set_project(project_root: Path | str, key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise ValueError(f"unknown config key: {key}")
    _validate(key, value)
    p = project_config_path(project_root)
    data = _load(p)
    data[key] = value
    _save(p, data)


def unset_user(key: str) -> bool:
    p = user_config_path()
    data = _load(p)
    if key not in data:
        return False
    del data[key]
    _save(p, data)
    return True


def unset_project(project_root: Path | str, key: str) -> bool:
    p = project_config_path(project_root)
    data = _load(p)
    if key not in data:
        return False
    del data[key]
    _save(p, data)
    return True


def reset_user() -> None:
    p = user_config_path()
    if p.exists():
        p.unlink()


def _validate(key: str, value: Any) -> None:
    if key == "viewer.style" and value not in VALID_STYLES:
        raise ValueError(f"viewer.style must be one of {sorted(VALID_STYLES)}")
    if key == "viewer.theme" and value not in VALID_THEMES:
        raise ValueError(f"viewer.theme must be one of {sorted(VALID_THEMES)}")
    if key == "viewer.font_size" and value not in VALID_FONT_SIZES:
        raise ValueError(f"viewer.font_size must be one of {sorted(VALID_FONT_SIZES)}")
    default = DEFAULTS.get(key)
    if isinstance(default, bool) and not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    if isinstance(default, int) and not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")


def list_keys() -> list[str]:
    return sorted(DEFAULTS.keys())
