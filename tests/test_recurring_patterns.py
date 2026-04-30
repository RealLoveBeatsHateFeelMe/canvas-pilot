"""Unit tests for src/recurring_patterns.py.

Run: pytest tests/test_recurring_patterns.py -v

Fixture data mirrors the shape of Canvas list_assignments() output. The
end-to-end tests cover four typical course archetypes:

  - two-pattern code course (problem sets + projects)
  - mixed-pattern document course (twice-weekly scans + many one-offs)
  - single-pattern quiz course (weekly quizzes + a few one-offs)
  - empty course (no assignments yet)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datetime as dt

from src.recurring_patterns import normalize, bucket_recurring, is_course_active, Pattern


# ---------- normalize() ----------

def test_normalize_bare_digit():
    assert normalize("Set 3 Problem 4") == "Set <N> Problem <N>"

def test_normalize_no_space_digits():
    assert normalize("Tue Wk5 HW Scan") == "Tue Wk<N> HW Scan"

def test_normalize_section_in_phrase():
    assert normalize("Quiz on Section 17 reading and lecture") \
        == "Quiz on Section <N> reading and lecture"

def test_normalize_range():
    assert normalize("Attendance/Participation Wks 1-5") \
        == "Attendance/Participation Wks <N>"

def test_normalize_em_dash_range():
    assert normalize("Reading 3–5") == "Reading <N>"

def test_normalize_roman_numeral():
    assert normalize("Project II") == "Project <N>"
    assert normalize("Module IV homework") == "Module <N> homework"

def test_normalize_single_letter_not_roman():
    # "I" alone shouldn't be replaced — too aggressive, would eat pronouns
    assert normalize("What I learned this week") == "What I learned this week"

def test_normalize_collapses_whitespace():
    assert normalize("Set  3   Problem  4") == "Set <N> Problem <N>"

def test_normalize_no_digits_passthrough():
    assert normalize("Final Paper") == "Final Paper"
    assert normalize("Academic Honesty Contract") == "Academic Honesty Contract"


# ---------- bucket_recurring() ----------

def _items(*specs):
    """Build a list of fake assignment dicts. Each spec is (name, submission_types)."""
    return [{"name": n, "submission_types": list(st)} for n, st in specs]


def test_bucket_groups_by_normalized_name():
    items = _items(
        ("Set 1 Problem 1", ["online_upload"]),
        ("Set 1 Problem 2", ["online_upload"]),
        ("Set 2 Problem 1", ["online_upload"]),
    )
    patterns, tail = bucket_recurring(items, min_freq=3)
    assert len(patterns) == 1
    assert patterns[0].norm_name == "Set <N> Problem <N>"
    assert patterns[0].count == 3
    assert tail == 0


def test_bucket_separates_different_submission_types():
    """Same name shape but different submission_types must NOT merge."""
    items = _items(
        ("Quiz 1", ["online_quiz"]),
        ("Quiz 2", ["online_quiz"]),
        ("Quiz 3", ["online_quiz"]),
        ("Quiz 4", ["online_upload"]),
    )
    patterns, tail = bucket_recurring(items, min_freq=3)
    assert len(patterns) == 1
    assert patterns[0].submission_types == ("online_quiz",)
    assert patterns[0].count == 3
    assert tail == 1  # the online_upload one falls below threshold


def test_bucket_below_threshold_goes_to_tail():
    items = _items(
        ("Set 1 Problem 1", ["online_upload"]),
        ("Set 1 Problem 2", ["online_upload"]),  # only 2 — sub-threshold
        ("Final Exam", ["on_paper"]),
        ("Attendance", ["none"]),
    )
    patterns, tail = bucket_recurring(items, min_freq=3)
    assert patterns == []
    assert tail == 4


def test_bucket_sorted_by_count_descending():
    items = _items(
        ("Foo 1", ["online_upload"]),
        ("Foo 2", ["online_upload"]),
        ("Foo 3", ["online_upload"]),
        ("Bar 1", ["online_quiz"]),
        ("Bar 2", ["online_quiz"]),
        ("Bar 3", ["online_quiz"]),
        ("Bar 4", ["online_quiz"]),
        ("Bar 5", ["online_quiz"]),
    )
    patterns, _ = bucket_recurring(items, min_freq=3)
    assert [p.count for p in patterns] == [5, 3]
    assert patterns[0].norm_name == "Bar <N>"


def test_bucket_examples_capped_at_3():
    items = _items(*[(f"Item {i}", ["online_upload"]) for i in range(1, 11)])
    patterns, _ = bucket_recurring(items, min_freq=3)
    assert len(patterns) == 1
    assert len(patterns[0].examples) == 3


def test_bucket_handles_missing_submission_types():
    items = [
        {"name": "X 1"},
        {"name": "X 2"},
        {"name": "X 3"},
    ]
    patterns, tail = bucket_recurring(items, min_freq=3)
    assert len(patterns) == 1
    assert patterns[0].submission_types == ()
    assert tail == 0


def test_bucket_empty_input():
    patterns, tail = bucket_recurring([], min_freq=3)
    assert patterns == []
    assert tail == 0


# ---------- end-to-end: four typical course archetypes ----------

def test_e2e_two_pattern_code_course():
    """17 problem-set items + 3 projects, all online_upload."""
    items = _items(
        *[(f"Set {s} Problem {p}", ["online_upload"])
          for s in range(1, 5) for p in range(1, 5)],
        ("Set 5 Problem 1", ["online_upload"]),
        ("Project 0", ["online_upload"]),
        ("Project 1", ["online_upload"]),
        ("Project 2", ["online_upload"]),
    )
    assert len(items) == 20
    patterns, tail = bucket_recurring(items, min_freq=3)
    assert tail == 0
    assert len(patterns) == 2
    counts = sorted([p.count for p in patterns], reverse=True)
    assert counts == [17, 3]


def test_e2e_document_course_with_long_tail():
    """8 Thu HW Scan + 7 Tue HW Scan + 12 sub-threshold (mixed)."""
    items = _items(
        *[(f"Thu Wk{w} HW Scan", ["online_upload"]) for w in range(1, 9)],
        *[(f"Tue Wk{w} HW Scan", ["online_upload"]) for w in range(2, 9)],
        ("Student Info Sheet", ["online_upload"]),
        ("Academic Honesty Contract", ["online_upload"]),
        ("Final Exam (In-Class Essay)", ["on_paper"]),
        ("Attendance/Participation Wks 1-5", ["none"]),
        ("Attendance/Participation Wks 6-10", ["none"]),
        *[(f"Note Taking R{i} (At home)", ["external_tool"]) for i in range(1, 5)],
        *[(f"Response Paper Draft {i}", ["external_tool"]) for i in (1, 2)],
        ("Response Paper Final Draft", ["external_tool"]),
    )
    patterns, tail = bucket_recurring(items, min_freq=3)
    pattern_names = {p.norm_name for p in patterns}
    assert "Thu Wk<N> HW Scan" in pattern_names
    assert "Tue Wk<N> HW Scan" in pattern_names
    # The 4 Note Taking + 3 Response Paper would also clear threshold given
    # this fixture; tail is everything below 3.
    assert tail >= 3  # at least the 3 unique singletons


def test_e2e_single_pattern_quiz_course():
    """17 weekly quizzes + 3 one-off non-quiz items."""
    items = _items(
        *[(f"Quiz on Section {s} reading and lecture", ["online_quiz"])
          for s in range(1, 18)],
        ("Final Paper", ["external_tool"]),
        ("Extra Credit Evaluation", ["none"]),
        ("iClicker Lecture Attendance", ["external_tool"]),
    )
    assert len(items) == 20
    patterns, tail = bucket_recurring(items, min_freq=3)
    assert len(patterns) == 1
    assert patterns[0].count == 17
    assert patterns[0].submission_types == ("online_quiz",)
    assert tail == 3


def test_e2e_empty_course():
    """0 assignments — no patterns, no tail."""
    patterns, tail = bucket_recurring([], min_freq=3)
    assert patterns == [] and tail == 0


# ---------- is_course_active() ----------

NOW = dt.datetime(2026, 4, 30, tzinfo=dt.timezone.utc)


def test_active_no_end_date_treated_as_active():
    """Perpetual spaces (no end_at, no term.end_at) are treated as active."""
    assert is_course_active({"end_at": None, "term": {"end_at": None}}, now=NOW) is True
    assert is_course_active({}, now=NOW) is True


def test_active_term_end_in_future():
    """Term ends after now → active."""
    course = {"term": {"end_at": "2026-06-19T07:00:00Z"}}
    assert is_course_active(course, now=NOW) is True


def test_active_term_ended_outside_grace():
    """Term ended >7 days ago → not active."""
    course = {"term": {"end_at": "2026-03-27T07:00:00Z"}}  # 34 days before NOW
    assert is_course_active(course, now=NOW) is False


def test_active_term_ended_within_grace():
    """Term ended 5 days ago → still within 7-day grace, active."""
    course = {"term": {"end_at": "2026-04-25T07:00:00Z"}}  # 5 days before NOW
    assert is_course_active(course, now=NOW) is True


def test_active_uses_latest_of_course_and_term_end():
    """course.end_at is later than term.end_at → use the later one (most permissive)."""
    course = {
        "end_at": "2026-08-28T06:59:00Z",       # far future
        "term": {"end_at": "2025-09-09T07:00:00Z"},  # last year
    }
    assert is_course_active(course, now=NOW) is True


def test_active_only_course_end_set():
    """No term info but course.end_at is set."""
    assert is_course_active({"end_at": "2026-06-19T07:00:00Z"}, now=NOW) is True
    assert is_course_active({"end_at": "2025-12-01T07:00:00Z"}, now=NOW) is False


def test_active_grace_zero():
    """grace_days=0 — no buffer."""
    course = {"term": {"end_at": "2026-04-29T07:00:00Z"}}  # 1 day before NOW
    assert is_course_active(course, grace_days=0, now=NOW) is False  # ended yesterday
    assert is_course_active(course, grace_days=7, now=NOW) is True   # within 7-day buffer
