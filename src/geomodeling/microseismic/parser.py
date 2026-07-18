from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from pathlib import Path

from ..io import sha256_file
from .schemas import SourceFileManifestEntry, VelocitySample

MSVC_SPECIAL_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)?#(QNAN|SNAN|NAN|INF|IND)", re.IGNORECASE)

SOURCE_UNIT = "WL/2(km) verbatim; Vx unit pending source confirmation"


def classify_token(token: str) -> tuple[float | None, str | None, str | None]:
    text = token.strip()
    if not text:
        return None, "empty_token", "EMPTY_TOKEN"
    if MSVC_SPECIAL_RE.match(text):
        kind = text.upper()
        if "INF" in kind:
            return None, "msvc_special_infinite_token", "SOURCE_SPECIAL_INF_TOKEN"
        return None, "msvc_special_nan_token", "SOURCE_SPECIAL_NAN_TOKEN"
    try:
        value = float(text)
    except ValueError:
        return None, "non_numeric_token", "NON_NUMERIC_TOKEN"
    if math.isnan(value):
        return None, "nan_token", "NAN_TOKEN"
    if math.isinf(value):
        return None, "infinite_token", "INFINITE_TOKEN"
    return value, None, None


def split_nul_terminator(raw: bytes) -> tuple[bytes, int]:
    body = raw.rstrip(b"\r\n")
    stripped = body.rstrip(b"\x00").rstrip(b"\r\n")
    nul_count = len(body) - len(body.rstrip(b"\x00"))
    pseudo_lines = 1 if nul_count else 0
    return stripped, pseudo_lines


def parse_dat_file(path: str | Path, point_id: str, line_id: str) -> tuple[SourceFileManifestEntry, list[VelocitySample]]:
    source_path = Path(path)
    raw = source_path.read_bytes()
    sha256 = sha256_file(source_path)
    mtime = datetime.fromtimestamp(source_path.stat().st_mtime, tz=timezone.utc)
    source_file_id = f"microseismic_dat_{point_id}"
    quality_issues: list[str] = []

    content, nul_pseudo_lines = split_nul_terminator(raw)
    nul_terminator = nul_pseudo_lines > 0
    if nul_terminator:
        quality_issues.append("SOURCE_NUL_TERMINATOR")

    try:
        text = content.decode("ascii")
        encoding = "ascii"
    except UnicodeDecodeError:
        text = content.decode("ascii", errors="replace")
        encoding = "ascii_with_replacement"
        quality_issues.append("ENCODING_FALLBACK")

    lines = text.splitlines()
    header_text: str | None = None
    samples: list[VelocitySample] = []
    valid_numeric = 0
    invalid_numeric = 0
    parse_status = "parsed"

    data_started = False
    for line_number, line in enumerate(lines, start=1):
        if not data_started:
            if line.strip():
                header_text = line.strip()
                data_started = True
            continue
        if not line.strip():
            continue
        tokens = line.split()
        flags: list[str] = []
        invalid_reasons: list[str] = []
        wl_token: str | None = None
        vx_token: str | None = None
        wl_value: float | None = None
        vx_value: float | None = None
        if len(tokens) != 2:
            flags.append("FIELD_COUNT_MISMATCH")
            invalid_reasons.append(f"expected 2 whitespace-separated tokens, found {len(tokens)}")
            wl_token = tokens[0] if tokens else None
            vx_token = tokens[1] if len(tokens) > 1 else None
        else:
            wl_token, vx_token = tokens
            wl_value, wl_reason, wl_flag = classify_token(wl_token)
            vx_value, vx_reason, vx_flag = classify_token(vx_token)
            for reason, flag in [(wl_reason, wl_flag), (vx_reason, vx_flag)]:
                if reason:
                    invalid_reasons.append(reason)
                if flag:
                    flags.append(flag)
                    if flag not in quality_issues:
                        quality_issues.append(flag)
        is_valid = not invalid_reasons
        if is_valid:
            valid_numeric += 1
        else:
            invalid_numeric += 1
        samples.append(
            VelocitySample(
                sample_id=f"{point_id}:{line_number}",
                point_id=point_id,
                line_id=line_id,
                source_file_id=source_file_id,
                source_file_name=source_path.name,
                source_line_number=line_number,
                wl_half_km_raw_token=wl_token,
                vx_raw_token=vx_token,
                wl_half_km_value=wl_value,
                vx_value=vx_value,
                source_unit=SOURCE_UNIT,
                is_numeric_valid=is_valid,
                invalid_reason=";".join(invalid_reasons) if invalid_reasons else None,
                quality_flags=flags,
                included_in_raw=True,
                included_in_valid_numeric=is_valid,
                included_in_clean_candidate=False,
                outlier_reason=None,
                imputed=False,
                imputation_method=None,
                cleaning_version="none_v0.2a",
                derived_depth_m=None,
                derived_z_m=None,
                depth_derivation_status="unconfirmed",
                notes="special NaN token preserved verbatim; excluded from finite statistics" if "SOURCE_SPECIAL_NAN_TOKEN" in flags else None,
            )
        )

    if header_text is None:
        parse_status = "empty_file"
        quality_issues.append("EMPTY_FILE")

    manifest = SourceFileManifestEntry(
        source_file_id=source_file_id,
        relative_path=str(source_path),
        file_name=source_path.name,
        size_bytes=len(raw),
        sha256=sha256,
        mtime=mtime,
        encoding=encoding,
        header_text=header_text,
        nul_terminator=nul_terminator,
        nul_pseudo_line_count=nul_pseudo_lines,
        point_id=point_id,
        line_id=line_id,
        source_record_count=len(samples),
        valid_numeric_count=valid_numeric,
        invalid_numeric_count=invalid_numeric,
        parse_status=parse_status,
        quality_issues=quality_issues,
    )
    return manifest, samples
