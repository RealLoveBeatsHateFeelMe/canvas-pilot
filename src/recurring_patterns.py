"""Detect recurring assignment-name patterns in a Canvas course.

Used by canvas-bootstrap to surface the "things that repeat every week" so the
student knows what's worth automating with a per-course skill. The algorithm
is deliberately simple: normalize numbers in assignment names, bucket by
(normalized_name, submission_types), and keep the buckets that occur >= 3 times.

No classifier, no recommendation — just facts.

Also exposes `is_course_active()` so bootstrap can drop courses whose term has
already ended — students never want to install a skill on last quarter's course.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from typing import NamedTuple


class Pattern(NamedTuple):
    """One recurring assignment shape detected in a course."""
    norm_name: str
    submission_types: tuple[str, ...]
    count: int
    examples: tuple[str, ...]


def normalize(name: str) -> str:
    """Replace bare digits and Roman numerals with <N>, collapse <N> ranges."""
    s = re.sub(r'\d+', '<N>', name)
    s = re.sub(r'\b[IVX]{2,}\b', '<N>', s)
    s = re.sub(r'<N>(\s*[-–to,]+\s*<N>)+', '<N>', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def bucket_recurring(
    items: list[dict],
    min_freq: int = 3,
) -> tuple[list[Pattern], int]:
    """Group assignments into patterns and split by frequency threshold.

    Returns (patterns, sub_threshold_count):
      - patterns: clusters with count >= min_freq, sorted by count descending
      - sub_threshold_count: total assignments in clusters below the threshold
        (the "+ N one-off / sub-threshold assignments" tail)
    """
    buckets: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
    for a in items:
        name = a.get("name", "") or ""
        st = tuple(a.get("submission_types") or [])
        buckets[(normalize(name), st)].append(name)

    patterns: list[Pattern] = []
    sub_threshold = 0
    for (norm, st), names in buckets.items():
        if len(names) >= min_freq:
            patterns.append(Pattern(
                norm_name=norm,
                submission_types=st,
                count=len(names),
                examples=tuple(names[:3]),
            ))
        else:
            sub_threshold += len(names)

    patterns.sort(key=lambda p: -p.count)
    return patterns, sub_threshold


def is_course_active(course: dict, grace_days: int = 7, now: dt.datetime | None = None) -> bool:
    """Has the course's term ended (with a grace window)?

    Returns True if the course's latest known end date is at or after `now - grace_days`.
    A course with no end date (perpetual orientation spaces, etc.) is treated as active.

    Looks at both `course.end_at` and `course.term.end_at`, takes the LATEST (most
    permissive) — Canvas sometimes sets one but not the other, and a course can
    legitimately extend past its term's nominal end.

    Bootstrap uses this to drop last-quarter courses that the student no longer
    wants to install a skill on.
    """
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=grace_days)

    candidates: list[str] = []
    if course.get("end_at"):
        candidates.append(course["end_at"])
    term = course.get("term") or {}
    if term.get("end_at"):
        candidates.append(term["end_at"])

    if not candidates:
        return True  # no end date known — treat as active (e.g. perpetual spaces)

    latest = max(
        dt.datetime.fromisoformat(c.replace("Z", "+00:00"))
        for c in candidates
    )
    return latest >= cutoff
