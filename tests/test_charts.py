"""Chart geometry: the shapes, computed here so templates only place them."""

import pytest

from admin_litestar.charts import NEGATIVE_MESSAGE, bars, spark


def test_bars_scale_against_the_largest_value() -> None:
    """The question a bar chart answers is how these compare to each other."""
    drawn = bars([("paid", 40), ("pending", 20), ("void", 10)])
    assert [bar.percent for bar in drawn] == [100.0, 50.0, 25.0]
    assert [bar.label for bar in drawn] == ["paid", "pending", "void"]
    # the value is kept for the label, not replaced by its length
    assert [bar.value for bar in drawn] == [40, 20, 10]


def test_all_zero_data_draws_no_bars_rather_than_dividing_by_zero() -> None:
    """A quiet week is a real answer, not an error."""
    assert [bar.percent for bar in bars([("a", 0), ("b", 0)])] == [0.0, 0.0]


def test_no_data_draws_nothing() -> None:
    """An empty series is empty, and the template says so."""
    assert bars([]) == ()


def test_a_negative_value_is_refused_rather_than_mis_drawn() -> None:
    """A bar has no baseline here, so a negative would draw as a short positive.

    Refusing is the honest option: the alternative is a chart that reads as small
    when the number is in fact below zero.
    """
    with pytest.raises(ValueError, match="zero or greater"):
        bars([("profit", 10), ("loss", -4)])
    assert "baseline" in NEGATIVE_MESSAGE


def test_a_spark_plots_evenly_spaced_points_within_its_box() -> None:
    """Points stay inside the viewBox, and larger values sit nearer the top."""
    plotted = spark([1, 9])
    assert plotted is not None
    pairs = [tuple(float(n) for n in pair.split(",")) for pair in plotted.points.split()]
    assert pairs[0][0] == 2.0 and pairs[-1][0] == 98.0
    assert pairs[0][1] > pairs[-1][1], "9 is higher up the box than 1"
    assert all(0 <= x <= 100 and 0 <= y <= 28 for x, y in pairs)


def test_a_flat_series_is_drawn_down_the_middle() -> None:
    """A constant is not a zero, and a line along the floor would say it was."""
    plotted = spark([4, 4, 4])
    assert plotted is not None
    heights = {pair.split(",")[1] for pair in plotted.points.split()}
    assert len(heights) == 1
    assert heights == {"14.0"}, "mid-box, not the baseline"


def test_one_reading_is_not_a_line() -> None:
    """A dot pretending to be a trend is worse than saying there is no trend."""
    assert spark([7]) is None
    assert spark([]) is None


def test_a_spark_reports_its_ends_and_its_range() -> None:
    """The caption carries the numbers, so the line itself needs no labels."""
    plotted = spark([5, 12, 3, 8])
    assert plotted is not None
    assert (plotted.first, plotted.last) == (5, 8)
    assert (plotted.low, plotted.high) == (3, 12)
