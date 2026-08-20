from collections.abc import Callable
from typing import TypeVar, cast

T = TypeVar("T")

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _cast_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ValueError(f"not a boolean: {value!r}")


def env(
    key: str,
    default: str | None = None,
    cast_to: Callable[[str], T] | None = None,
    required: bool = False,
) -> T | None:
    """Read a value from os.environ with optional type casting.

    Falls back to ``default`` (also cast). When ``required=True`` and the
    variable is missing/empty, raises RuntimeError so misconfigured
    deployments fail loudly.
    """
    import os

    raw = os.environ.get(key)
    if raw is None or raw == "":
        if required:
            raise RuntimeError(f"Missing required environment variable: {key}")
        if default is None:
            return None
        if cast_to is None:
            return cast(T | None, default)
        try:
            return cast_to(default)
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                f"Default for {key}={default!r} cannot be parsed as "
                f"{getattr(cast_to, '__name__', cast_to)}"
            ) from exc

    if cast_to is None:
        return cast(T | None, raw)
    try:
        return cast_to(raw)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"Environment variable {key}={raw!r} cannot be parsed as "
            f"{getattr(cast_to, '__name__', cast_to)}"
        ) from exc


def env_bool(key: str, default: str = "0", required: bool = False) -> bool | None:
    """env() with a boolean cast (accepts 1/0/true/false/yes/no/on/off)."""
    return env(key, default=default, cast_to=_cast_bool, required=required)
