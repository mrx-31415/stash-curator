"""Optional accelerated dependencies with a pure-Python fallback.

The plugin ships without third-party packages. When the "Install optional
dependencies" task has installed numpy into the plugin-local venv, the accelerated
model stages use it; every other environment keeps the pure-Python implementations.
"""

from __future__ import annotations

from typing import Any, cast

try:
    import numpy as _np
except ImportError:  # pragma: no cover - exercised only in numpy-less environments
    _np = None  # type: ignore[assignment]

NUMPY_AVAILABLE: bool = _np is not None
# Module alias stays untyped so accelerated code can call np.array(...) freely.
np: Any = _np if NUMPY_AVAILABLE else cast(Any, None)
