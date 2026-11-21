"""Tests for event normalization and validation."""

import math
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from movebank.domain.event_normalization import (
    EventNormalizationResult,
    events_for_analysis,
    normalize_events,
)


def base_valid_row():
    """Helper to create a valid base row with all required fields for Event."""
    return {
        "event_id": 1,
        "timestamp": "2020-01-01T00:00:00Z",
        "location_lat": "40.0",
        "location_long": "-74.0",
        "individual_id": "1",
    }


class TestEventsForAnalysis:
    """Test filtering of events for analysis based on visibility."""

    def test_visible_true_included_by_default(self):
        rows = [{"visible": True}, {"visible": False}, {"visible": None}]
        result = events_for_analysis(rows)
        assert len(result) == 1
        assert result[0]["visible"] is True

    def test_visible_false_excluded_by_default(self):
        rows = [{"visible": True}, {"visible": False}, {"visible": None}]
        result = events_for_analysis(rows)
        assert not any(r["visible"] is False for r in result)

    def test_unknown_visibility_excluded_by_default(self):
        rows = [{"visible": True}, {"visible": False}, {"visible": None}]
        result = events_for_analysis(rows)
        assert not any(r["visible"] is None for r in result)

    def test_unknown_visibility_included_when_requested(self):
        rows = [{"visible": True}, {"visible": False}, {"visible": None}]
        result = events_for_analysis(rows, include_unknown_visibility=True)
        assert len(result) == 2
        assert any(r["visible"] is True for r in result)
        assert any(r["visible"] is None for r in result)

    def test_empty_list(self):
        result = events_for_analysis([])
        assert result == []

    def test_no_visible_field(self):
        """Rows without 'visible' field are excluded (treated as falsy)."""
        rows = [{"other_field": "value"}]
        result = events_for_analysis(rows)
        assert result == []


class TestEventNormalizationResultProperties:
    """Test properties of EventNormalizationResult."""

    def test_accepted_count(self):
        events = [{"visible": True}, {"visible": False}]
        result = EventNormalizationResult(events, {})
        assert result.accepted_count == 2

    def test_rejected_count(self):
        result = EventNormalizationResult([], {"invalid": 2, "missing": 1})
        assert result.rejected_count == 3

    def test_hidden_count(self):
        events = [{"visible": True}, {"visible": False}, {"visible": False}]
        result = EventNormalizationResult(events, {})
        assert result.hidden_count == 2

    def test_unknown_visibility_count(self):
        events = [{"visible": True}, {"visible": None}, {"visible": None}]
        result = EventNormalizationResult(events, {})
        assert result.unknown_visibility_count == 2

    def test_unknown_visibility_events(self):
        events = [{"visible": True}, {"visible": None}, {"visible": False}]
        result = EventNormalizationResult(events, {})
        unknown = result.unknown_visibility_events
        assert len(unknown) == 1
        assert unknown[0]["visible"] is None

    def test_result_events_for_analysis_method(self):
        """Test the events_for_analysis method on the result object."""
        events = [{"visible": True}, {"visible": None}, {"visible": False}]
        result = EventNormalizationResult(events, {})
        analysis = result.events_for_analysis()
        assert len(analysis) == 1
        assert analysis[0]["visible"] is True


class TestNormalizeVisibility:
    """Test normalization of the 'visible' field."""

    def test_boolean_true_preserved(self):
        row = base_valid_row()
        row["visible"] = True
        result = normalize_events([row])
        assert result.events[0]["visible"] is True

    def test_boolean_false_preserved(self):
        row = base_valid_row()
        row["visible"] = False
        result = normalize_events([row])
        assert result.events[0]["visible"] is False

    def test_string_true_case_insensitive(self):
        for val in ["true", "True", "TRUE", "tRuE"]:
            row = base_valid_row()
            row["visible"] = val
            result = normalize_events([row])
            assert result.events[0]["visible"] is True

    def test_string_false_case_insensitive(self):
        for val in ["false", "False", "FALSE", "fAlSe"]:
            row = base_valid_row()
            row["visible"] = val
            result = normalize_events([row])
            assert result.events[0]["visible"] is False

    def test_string_1_becomes_true(self):
        row = base_valid_row()
        row["visible"] = "1"
        result = normalize_events([row])
        assert result.events[0]["visible"] is True

    def test_string_0_becomes_false(self):
        row = base_valid_row()
        row["visible"] = "0"
        result = normalize_events([row])
        assert result.events[0]["visible"] is False

    def test_int_1_becomes_true(self):
        row = base_valid_row()
        row["visible"] = 1
        result = normalize_events([row])
        assert result.events[0]["visible"] is True

    def test_int_0_becomes_false(self):
        row = base_valid_row()
        row["visible"] = 0
        result = normalize_events([row])
        assert result.events[0]["visible"] is False

    def test_none_becomes_none(self):
        row = base_valid_row()
        row["visible"] = None
        result = normalize_events([row])
        assert result.events[0]["visible"] is None

    def test_empty_string_becomes_none(self):
        row = base_valid_row()
        row["visible"] = ""
        result = normalize_events([row])
        assert result.events[0]["visible"] is None

    def test_whitespace_becomes_none(self):
        row = base_valid_row()
        row["visible"] = "   "
        result = normalize_events([row])
        assert result.events[0]["visible"] is None

    def test_pandas_na_becomes_none(self):
        row = base_valid_row()
        row["visible"] = pd.NA
        result = normalize_events([row])
        assert result.events[0]["visible"] is None

    def test_numpy_nan_becomes_none(self):
        row = base_valid_row()
        row["visible"] = np.nan
        result = normalize_events([row])
        assert result.events[0]["visible"] is None

    def test_invalid_visibility_rejected(self):
        row = base_valid_row()
        row["visible"] = "maybe"
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason["invalid_visible"] == 1

    def test_unrecognized_number_rejected(self):
        """Numbers other than 0 and 1 are rejected."""
        row = base_valid_row()
        row["visible"] = 2
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason["invalid_visible"] == 1

    def test_literal_nan_string_rejected(self):
        """The literal string 'NaN' should be rejected as invalid visibility."""
        row = base_valid_row()
        row["visible"] = "NaN"
        result = normalize_events([row])
        assert result.rejected_count == 1

    def test_literal_nat_string_rejected(self):
        """The literal string 'NaT' should be rejected as invalid visibility."""
        row = base_valid_row()
        row["visible"] = "NaT"
        result = normalize_events([row])
        assert result.rejected_count == 1


class TestNormalizeCoordinates:
    """Test normalization of location coordinates."""

    def test_valid_coordinates_accepted(self):
        row = base_valid_row()
        row["location_lat"] = "40.7128"
        row["location_long"] = "-74.0060"
        result = normalize_events([row])
        assert result.accepted_count == 1
        assert isinstance(result.events[0]["location_lat"], float)
        assert isinstance(result.events[0]["location_long"], float)
        assert abs(result.events[0]["location_lat"] - 40.7128) < 0.0001

    def test_integer_coordinates_converted_to_float(self):
        row = base_valid_row()
        row["location_lat"] = 40
        row["location_long"] = -74
        result = normalize_events([row])
        assert result.accepted_count == 1
        assert isinstance(result.events[0]["location_lat"], float)

    def test_decimal_coordinates_converted(self):
        row = base_valid_row()
        row["location_lat"] = Decimal("40.7128")
        row["location_long"] = Decimal("-74.0060")
        result = normalize_events([row])
        assert result.accepted_count == 1

    def test_missing_coordinate_rejected(self):
        row = base_valid_row()
        row["location_lat"] = None
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason["missing_coordinates"] == 1

    def test_missing_long_coordinate_rejected(self):
        row = base_valid_row()
        row["location_long"] = ""
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason["missing_coordinates"] == 1

    def test_missing_coordinate_field_rejected(self):
        """If a coordinate field is missing, it's counted as missing_coordinates."""
        row = {
            "event_id": 1,
            "timestamp": "2020-01-01T00:00:00Z",
            "location_lat": "40.7128",
            "individual_id": "1",
        }
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason["missing_coordinates"] == 1

    def test_non_numeric_coordinate_rejected(self):
        row = base_valid_row()
        row["location_lat"] = "not_a_number"
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason["invalid_coordinates"] == 1

    def test_nan_coordinate_rejected(self):
        row = base_valid_row()
        row["location_lat"] = float("nan")
        result = normalize_events([row])
        assert result.rejected_count == 1
        # NaN is detected as invalid during coordinate normalization
        assert "invalid" in result.rejected_by_reason or "coordinates" in str(result.rejected_by_reason)

    def test_infinity_coordinate_rejected(self):
        row = base_valid_row()
        row["location_lat"] = float("inf")
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason["invalid_coordinates"] == 1

    def test_coordinate_out_of_range_rejected(self):
        """Event model validation rejects coordinates outside geographic bounds."""
        row = base_valid_row()
        row["location_lat"] = 91.0  # > 90
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason["invalid_coordinates"] == 1


class TestNormalizeTimestamp:
    """Test validation of timestamps."""

    def test_valid_iso_timestamp_accepted(self):
        row = base_valid_row()
        result = normalize_events([row])
        assert result.accepted_count == 1

    def test_missing_timestamp_rejected(self):
        row = base_valid_row()
        row["timestamp"] = None
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason["invalid_timestamp"] == 1

    def test_empty_timestamp_rejected(self):
        row = base_valid_row()
        row["timestamp"] = ""
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason["invalid_timestamp"] == 1

    def test_pandas_nat_timestamp_rejected(self):
        """pandas.NaT is properly rejected as an invalid timestamp.
        
        pandas.NaT (Not-a-Time) is a special value that cannot be converted to a
        standard Python datetime. The test verifies that it is rejected with the
        'invalid_timestamp' reason and does not appear in accepted events.
        """
        row = base_valid_row()
        result = normalize_events([row.copy() | {"timestamp": pd.NaT}])
        assert result.rejected_count == 1
        assert result.rejected_by_reason.get("invalid_timestamp") == 1
        assert result.accepted_count == 0

    def test_numpy_nat_timestamp_rejected(self):
        """numpy.datetime64('NaT') is properly rejected as an invalid timestamp."""
        row = base_valid_row()
        row["timestamp"] = np.datetime64("NaT")
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason.get("invalid_timestamp") == 1
        assert result.accepted_count == 0


class TestNormalizeIndividualId:
    """Test validation of individual_id."""

    def test_missing_individual_id_rejected(self):
        row = base_valid_row()
        row["individual_id"] = None
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason["invalid_event"] == 1

    def test_empty_individual_id_rejected(self):
        row = base_valid_row()
        row["individual_id"] = ""
        result = normalize_events([row])
        assert result.rejected_count == 1

    def test_valid_individual_id_accepted(self):
        row = base_valid_row()
        result = normalize_events([row])
        assert result.accepted_count == 1


class TestNormalizeOptionalFields:
    """Test normalization of optional fields like identifiers and taxon."""

    def test_none_identifier_becomes_none(self):
        row = base_valid_row()
        row["individual_local_identifier"] = None
        result = normalize_events([row])
        assert result.accepted_count == 1
        assert result.events[0].get("individual_local_identifier") is None

    def test_empty_identifier_becomes_none(self):
        row = base_valid_row()
        row["individual_local_identifier"] = ""
        result = normalize_events([row])
        assert result.accepted_count == 1
        assert result.events[0].get("individual_local_identifier") is None

    def test_whitespace_identifier_preserved(self):
        """Whitespace-only identifiers are preserved by Event, not converted to None."""
        row = base_valid_row()
        row["individual_local_identifier"] = "   "
        result = normalize_events([row])
        assert result.accepted_count == 1
        # normalize_events doesn't strip whitespace from identifiers
        assert result.events[0].get("individual_local_identifier") == "   "

    def test_valid_identifier_preserved(self):
        row = base_valid_row()
        row["individual_local_identifier"] = "bird_42"
        result = normalize_events([row])
        assert result.accepted_count == 1
        assert result.events[0]["individual_local_identifier"] == "bird_42"

    def test_literal_nan_identifier_preserved(self):
        """The literal string 'NaN' in identifier should be preserved, not treated as missing."""
        row = base_valid_row()
        row["individual_local_identifier"] = "NaN"
        result = normalize_events([row])
        assert result.accepted_count == 1
        assert result.events[0]["individual_local_identifier"] == "NaN"


class TestNormalizeEventsPriorityOrder:
    """Test that validation errors are classified with correct priority."""

    def test_coordinate_error_detected_before_timestamp(self):
        """Coordinate validation errors are detected before timestamp validation errors.
        
        When a row has both invalid coordinates and invalid timestamp, the row is rejected
        with the coordinate error reason, as coordinate validation happens first in the
        normalize_events processing order.
        """
        row = base_valid_row()
        row["timestamp"] = None
        row["location_lat"] = "not_a_number"
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert "invalid_coordinates" in result.rejected_by_reason

    def test_coordinate_error_before_other_errors(self):
        """Coordinate errors are detected before other Event model errors."""
        row = base_valid_row()
        row["location_lat"] = "not_numeric"
        row["individual_id"] = None
        result = normalize_events([row])
        assert result.rejected_count == 1
        assert result.rejected_by_reason.get("invalid_coordinates", 0) > 0


class TestNormalizeEventsMultiple:
    """Test processing multiple rows."""

    def test_multiple_rows_mixed_valid_invalid(self):
        rows = [
            base_valid_row(),
            {
                "event_id": 2,
                "timestamp": "2020-01-02T00:00:00Z",
                "location_lat": "not_numeric",
                "location_long": "-74.0060",
                "individual_id": "1",
            },
            {
                "event_id": 3,
                "timestamp": "2020-01-03T00:00:00Z",
                "location_lat": "40.0",
                "location_long": "-74.0",
                "individual_id": "2",
            },
        ]
        result = normalize_events(rows)
        assert result.accepted_count == 2
        assert result.rejected_count == 1

    def test_non_mapping_row_rejected(self):
        """A row that is not a Mapping should be rejected."""
        rows = ["not a mapping", base_valid_row()]
        result = normalize_events(rows)
        assert result.rejected_count >= 1
        assert result.rejected_by_reason["invalid_row"] == 1

    def test_empty_input(self):
        result = normalize_events([])
        assert result.accepted_count == 0
        assert result.rejected_count == 0


class TestNormalizeEventsVisibilityTracking:
    """Test that visibility and hidden counts are tracked accurately."""

    def test_counts_visible_true_hidden_false_unknown_none(self):
        rows = [
            {
                "event_id": 1,
                "timestamp": "2020-01-01T00:00:00Z",
                "location_lat": "40.0",
                "location_long": "-74.0",
                "individual_id": "1",
                "visible": True,
            },
            {
                "event_id": 2,
                "timestamp": "2020-01-02T00:00:00Z",
                "location_lat": "40.1",
                "location_long": "-74.1",
                "individual_id": "1",
                "visible": False,
            },
            {
                "event_id": 3,
                "timestamp": "2020-01-03T00:00:00Z",
                "location_lat": "40.2",
                "location_long": "-74.2",
                "individual_id": "1",
                "visible": None,
            },
        ]
        result = normalize_events(rows)
        assert result.accepted_count == 3
        assert result.hidden_count == 1
        assert result.unknown_visibility_count == 1

    def test_visibility_field_missing_defaults_to_none(self):
        """When 'visible' field is not provided, it should default to None."""
        row = base_valid_row()
        result = normalize_events([row])
        assert result.accepted_count == 1
        assert result.events[0].get("visible") is None


class TestNormalizeEventsRejectionReasons:
    """Test that rejection reasons are recorded accurately."""

    def test_multiple_rejection_reasons_counted_separately(self):
        rows = [
            {"visible": "invalid"},
            {
                "event_id": 2,
                "timestamp": "2020-01-02T00:00:00Z",
                "location_lat": "not_numeric",
                "location_long": "-74.0",
                "individual_id": "1",
            },
            {
                "event_id": 3,
                "timestamp": None,
                "location_lat": "40.0",
                "location_long": "-74.0",
                "individual_id": "1",
            },
        ]
        result = normalize_events(rows)
        assert result.rejected_count >= 3
        assert result.rejected_by_reason.get("invalid_visible", 0) >= 1
        assert result.rejected_by_reason["invalid_coordinates"] == 1
        assert result.rejected_by_reason["invalid_timestamp"] == 1
