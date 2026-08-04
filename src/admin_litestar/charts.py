"""Server-rendered chart geometry.

The package ships no charting library and loads nothing at runtime, so the shapes
are computed here and the templates only place them. Two forms, chosen by the job
the data does: magnitude across labelled categories, and change over time.

Both are drawn in a single hue. That is not a limitation worked around -- a bar
whose category is already written beside it gains nothing from a second encoding,
and the six group hues this admin uses for navigation are not a valid categorical
series palette: the azure and violet steps differ by ΔE 1.3 under deuteranopia
(8.6 with full colour vision), which is fine for accents that never sit adjacent
and wrong for marks that do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

# Geometry of the sparkline's own coordinate space. The SVG scales to its box, so
# these are ratios rather than pixels.
SPARK_WIDTH = 100
SPARK_HEIGHT = 28
SPARK_PADDING = 2
NEGATIVE_MESSAGE = (
    "bar values must be zero or greater; a measure that goes negative needs a "
    "form with a baseline, which this admin does not ship"
)


@dataclass(frozen=True, slots=True)
class Bar:
    """One labelled magnitude.

    Attributes:
        label: The category, written beside the bar rather than in a legend.
        value: The measure, shown as a number as well as a length.
        share: Length as a fraction of the largest bar, 0 to 1.
    """

    label: str
    value: Any
    share: float

    @property
    def percent(self) -> float:
        """Share as a percentage, for a CSS width."""
        return round(self.share * 100, 2)


def bars(data: Sequence[tuple[str, Any]]) -> tuple[Bar, ...]:
    """Scale labelled values into bars, longest filling the track.

    Scaled against the largest value, not against their sum: this answers "how do
    these compare", and a share-of-total reading belongs to a different chart.

    Raises:
        ValueError: If any value is negative, which this form cannot draw
            truthfully.
    """
    values = [float(value) for _, value in data]
    if any(value < 0 for value in values):
        raise ValueError(NEGATIVE_MESSAGE)
    largest = max(values, default=0.0)
    return tuple(
        Bar(
            label=label,
            value=value,
            # All-zero data draws no bars rather than dividing by zero.
            share=0.0 if largest == 0 else float(value) / largest,
        )
        for label, value in data
    )


@dataclass(frozen=True, slots=True)
class Spark:
    """A line over evenly spaced points.

    Attributes:
        points: ``x,y`` pairs in the SVG's own coordinate space.
        first: The earliest value, labelled at the start.
        last: The latest value, labelled at the end.
        low: The smallest value in the series.
        high: The largest value in the series.
    """

    points: str
    first: Any
    last: Any
    low: Any
    high: Any


def spark(values: Sequence[Any]) -> Spark | None:
    """Plot a series as a polyline, or None when there is nothing to plot.

    A flat series is drawn along the middle rather than at the bottom, because a
    constant is not a zero. One point is not a line and returns None: a single
    reading has no shape, and a dot pretending to be a trend is worse than no
    chart.
    """
    numbers = [float(value) for value in values]
    if len(numbers) < 2:
        return None
    low, high = min(numbers), max(numbers)
    span = high - low
    inner_height = SPARK_HEIGHT - SPARK_PADDING * 2
    step = (SPARK_WIDTH - SPARK_PADDING * 2) / (len(numbers) - 1)
    points = []
    for index, number in enumerate(numbers):
        # y grows downward in SVG, so a larger value sits nearer the top.
        ratio = 0.5 if span == 0 else (number - low) / span
        x = SPARK_PADDING + step * index
        y = SPARK_PADDING + inner_height * (1 - ratio)
        points.append(f"{round(x, 2)},{round(y, 2)}")
    return Spark(
        points=" ".join(points),
        first=values[0],
        last=values[-1],
        low=min(values, key=float),
        high=max(values, key=float),
    )
