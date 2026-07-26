from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Sequence

import pandas as pd

from .schemas import DerivedVelocitySample, RejectedFilteredSample

__all__ = [
    "ACCEPTED_COLUMNS",
    "REJECTED_COLUMNS",
    "accepted_csv_bytes",
    "rejected_csv_bytes",
    "write_canonical_bytes",
]

# Golden column contracts: the accepted header is exactly the uppercased
# DerivedVelocitySample.model_dump() key order; the rejected header appends
# the four filter-outcome aliases in schema definition order.
_ACCEPTED_FIELDS = tuple(DerivedVelocitySample.model_fields)
ACCEPTED_COLUMNS = tuple(name.upper() for name in _ACCEPTED_FIELDS)
_REJECTED_FIELDS = tuple(RejectedFilteredSample.model_fields)[len(_ACCEPTED_FIELDS) :]
REJECTED_COLUMNS = ACCEPTED_COLUMNS + tuple(
    str(RejectedFilteredSample.model_fields[name].serialization_alias) for name in _REJECTED_FIELDS
)


def _cell(value: object) -> object:
    """Render one value with the golden table's byte-level rules.

    Booleans become lowercase text; whole-number floats become integers so
    400.0 serializes as 400; every other float keeps Python's shortest repr.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _canonical_bytes(
    rows: Sequence[DerivedVelocitySample],
    fields: tuple[str, ...],
    columns: tuple[str, ...],
) -> bytes:
    frame = pd.DataFrame(
        [
            {column: _cell(getattr(row, field)) for field, column in zip(fields, columns, strict=True)}
            for row in rows
        ],
        columns=list(columns),
        # Object dtype stops pandas from coercing mixed int/float cells to
        # float64; each cell keeps the _cell formatting above.
        dtype=object,
    )
    # Never the process locale or the platform-default newline.
    return frame.to_csv(
        None,
        index=False,
        lineterminator="\r\n",
    ).encode("utf-8-sig")


def accepted_csv_bytes(rows: Sequence[DerivedVelocitySample]) -> bytes:
    """Canonical golden bytes of the accepted table, in source order."""
    return _canonical_bytes(rows, _ACCEPTED_FIELDS, ACCEPTED_COLUMNS)


def rejected_csv_bytes(rows: Sequence[RejectedFilteredSample]) -> bytes:
    """Canonical golden bytes of the rejected table, in source order."""
    return _canonical_bytes(rows, _ACCEPTED_FIELDS + _REJECTED_FIELDS, REJECTED_COLUMNS)


def write_canonical_bytes(path: str | Path, payload: bytes) -> Path:
    """Write payload to path via a sibling temporary file and os.replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(temporary, target)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise
    return target
