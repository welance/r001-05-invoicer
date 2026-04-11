"""Unit tests for Clockify duration parsing and rounding.

These are the guts of the money math — if these are wrong, every invoice is wrong.
"""

import pytest

from invoicer.clockify import _parse_duration_seconds, _round_up


class TestParseDurationSeconds:
    @pytest.mark.parametrize(
        "iso, expected",
        [
            ("PT1H", 3600),
            ("PT30M", 1800),
            ("PT45S", 45),
            ("PT1H30M", 5400),
            ("PT2H15M30S", 8130),
            ("PT0S", 0),
            ("PT1H0M0S", 3600),
        ],
    )
    def test_valid_iso_durations(self, iso, expected):
        assert _parse_duration_seconds(iso) == expected

    def test_none_returns_zero(self):
        assert _parse_duration_seconds(None) == 0.0

    def test_empty_returns_zero(self):
        assert _parse_duration_seconds("") == 0.0

    def test_malformed_returns_zero(self):
        # Not an ISO 8601 duration
        assert _parse_duration_seconds("1 hour") == 0.0
        assert _parse_duration_seconds("garbage") == 0.0


class TestRoundUp:
    @pytest.mark.parametrize(
        "seconds, step_minutes, expected",
        [
            # Exact boundaries: no rounding
            (0, 15, 0),
            (900, 15, 900),  # 15 min
            (1800, 15, 1800),  # 30 min
            (3600, 15, 3600),  # 60 min
            # Anything over a boundary rounds up
            (1, 15, 900),
            (899, 15, 900),
            (901, 15, 1800),
            (1799, 15, 1800),
            (1801, 15, 2700),
            # Different step sizes
            (1, 30, 1800),
            (1, 60, 3600),
            (3599, 60, 3600),
            (3601, 60, 7200),
            # step_minutes=0 should return unchanged (no rounding)
            (1234, 0, 1234),
        ],
    )
    def test_ceiling_rounding(self, seconds, step_minutes, expected):
        assert _round_up(seconds, step_minutes) == expected

    def test_round_up_never_decreases(self):
        for sec in [0, 1, 60, 3600, 7201]:
            assert _round_up(sec, 15) >= sec
