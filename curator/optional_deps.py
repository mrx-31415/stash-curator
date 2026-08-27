"""Optional accelerated dependency (numpy) for the dev/test oracle.

The compiled core is the single runtime implementation, so numpy is not shipped
or used by the plugin. It is imported by the differential-test oracle
(`tests/oracle.py`) so the Go kernels can be pinned against an independent
reference on seeded synthetic corpora.
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

try:
    import networkx as _nx  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised only in networkx-less environments
    _nx = None

NETWORKX_AVAILABLE: bool = _nx is not None
# Module alias stays untyped so graph code can call nx.pagerank(...) freely.
nx: Any = _nx if NETWORKX_AVAILABLE else cast(Any, None)
