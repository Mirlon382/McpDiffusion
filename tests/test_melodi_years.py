"""The pure year filtering of get_melodi_observations -- the bug that used to fail whole batches."""

from typing import Any

from melodi_mcp.tools.get_observations_tool import (
    keep_requested_years,
    read_observation_year,
)


class TestReadObservationYear:
    def test_a_period_is_cut_to_its_year(self) -> None:
        observation: dict[str, Any] = {"dimensions": {"TIME_PERIOD": "2023-01"}}
        assert read_observation_year(observation) == "2023"

    def test_a_plain_year_period_needs_no_cut(self) -> None:
        observation: dict[str, Any] = {"dimensions": {"TIME_PERIOD": "2024"}}
        assert read_observation_year(observation) == "2024"

    def test_missing_dimensions_read_as_no_year(self) -> None:
        assert read_observation_year({}) == ""

    def test_null_dimensions_read_as_no_year(self) -> None:
        # The regression: a malformed row used to raise AttributeError and lose the whole batch.
        assert read_observation_year({"dimensions": None}) == ""

    def test_absent_time_period_reads_as_no_year(self) -> None:
        assert read_observation_year({"dimensions": {"GEO": "FR"}}) == ""


class TestKeepRequestedYears:
    observations: list[dict[str, Any]] = [
        {"dimensions": {"TIME_PERIOD": "2023-01"}},
        {"dimensions": {"TIME_PERIOD": "2024-06"}},
        {"dimensions": None},
    ]

    def test_an_empty_year_list_keeps_everything(self) -> None:
        assert (
            keep_requested_years(
                self.observations,
                [],
            )
            == self.observations
        )

    def test_only_the_requested_years_survive(self) -> None:
        kept = keep_requested_years(
            self.observations,
            [2024],
        )
        assert kept == [{"dimensions": {"TIME_PERIOD": "2024-06"}}]

    def test_a_malformed_row_is_dropped_not_raised(self) -> None:
        kept = keep_requested_years(
            self.observations,
            [2023, 2024],
        )
        assert len(kept) == 2

    def test_arguments_are_never_mutated(self) -> None:
        original = list(self.observations)
        keep_requested_years(
            original,
            [2099],
        )
        assert len(original) == 3
