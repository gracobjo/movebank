"""Tests for missing value detection across Python and NumPy/Pandas data types."""

import math
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from movebank.domain.missing_values import is_missing_value


class TestMissingValuesNone:
    """Test detection of None as a missing value."""

    def test_none_is_missing(self):
        assert is_missing_value(None) is True


class TestMissingValuesStrings:
    """Test detection of missing values in string form."""

    def test_empty_string_is_missing(self):
        assert is_missing_value("") is True

    def test_whitespace_only_is_missing(self):
        assert is_missing_value(" ") is True
        assert is_missing_value("\t") is True
        assert is_missing_value("\n") is True
        assert is_missing_value("   \t\n  ") is True

    def test_non_empty_string_is_not_missing(self):
        assert is_missing_value("hello") is False
        assert is_missing_value("0") is False
        assert is_missing_value("False") is False
        assert is_missing_value(" x ") is False

    def test_literal_nan_string_is_not_missing(self):
        """The literal string 'NaN' should not be treated as missing."""
        assert is_missing_value("NaN") is False

    def test_literal_nat_string_is_not_missing(self):
        """The literal string 'NaT' should not be treated as missing."""
        assert is_missing_value("NaT") is False


class TestMissingValuesPandas:
    """Test detection of pandas-specific missing value markers."""

    def test_pandas_na_is_missing(self):
        assert is_missing_value(pd.NA) is True

    def test_pandas_nat_is_missing(self):
        assert is_missing_value(pd.NaT) is True


class TestMissingValuesNumPy:
    """Test detection of NumPy-specific missing value markers."""

    def test_numpy_datetime64_nat_is_missing(self):
        assert is_missing_value(np.datetime64("NaT")) is True

    def test_numpy_datetime64_valid_is_not_missing(self):
        assert is_missing_value(np.datetime64("2020-01-01")) is False


class TestMissingValuesDecimal:
    """Test detection of missing values in Decimal form."""

    def test_decimal_nan_is_missing(self):
        assert is_missing_value(Decimal("NaN")) is True

    def test_decimal_zero_is_not_missing(self):
        assert is_missing_value(Decimal("0")) is False

    def test_decimal_negative_is_not_missing(self):
        assert is_missing_value(Decimal("-1.5")) is False


class TestMissingValuesNumericNaN:
    """Test detection of numeric NaN values."""

    def test_float_nan_is_missing(self):
        assert is_missing_value(float("nan")) is True

    def test_math_nan_is_missing(self):
        """math.nan is equivalent to float('nan')."""
        assert is_missing_value(math.nan) is True

    def test_numpy_nan_is_missing(self):
        """np.nan is typically a float NaN."""
        assert is_missing_value(np.nan) is True


class TestMissingValuesZeroAndFalse:
    """Test that zero and False are not treated as missing values."""

    def test_integer_zero_is_not_missing(self):
        assert is_missing_value(0) is False

    def test_float_zero_is_not_missing(self):
        assert is_missing_value(0.0) is False

    def test_boolean_false_is_not_missing(self):
        assert is_missing_value(False) is False

    def test_negative_zero_is_not_missing(self):
        assert is_missing_value(-0.0) is False

    def test_decimal_zero_is_not_missing(self):
        assert is_missing_value(Decimal("0")) is False

    def test_string_zero_is_not_missing(self):
        """The string '0' is not empty, so it is not missing."""
        assert is_missing_value("0") is False

    def test_string_false_is_not_missing(self):
        """The string 'false' is not empty, so it is not missing."""
        assert is_missing_value("false") is False


class TestMissingValuesNumericRanges:
    """Test that normal numeric values are not treated as missing."""

    def test_positive_integer_is_not_missing(self):
        assert is_missing_value(1) is False
        assert is_missing_value(42) is False
        assert is_missing_value(1000000) is False

    def test_negative_integer_is_not_missing(self):
        assert is_missing_value(-1) is False
        assert is_missing_value(-42) is False

    def test_positive_float_is_not_missing(self):
        assert is_missing_value(1.5) is False
        assert is_missing_value(0.001) is False
        assert is_missing_value(999.999) is False

    def test_negative_float_is_not_missing(self):
        assert is_missing_value(-1.5) is False
        assert is_missing_value(-0.001) is False

    def test_very_large_number_is_not_missing(self):
        assert is_missing_value(1e308) is False
        assert is_missing_value(-1e308) is False

    def test_very_small_number_is_not_missing(self):
        """Very small numbers that are not NaN are not missing."""
        assert is_missing_value(1e-308) is False
        assert is_missing_value(-1e-308) is False


class TestMissingValuesNumericInfinity:
    """Test that infinity values are not treated as missing values."""

    def test_positive_infinity_is_not_missing(self):
        assert is_missing_value(float("inf")) is False

    def test_negative_infinity_is_not_missing(self):
        assert is_missing_value(float("-inf")) is False

    def test_numpy_positive_infinity_is_not_missing(self):
        assert is_missing_value(np.inf) is False

    def test_numpy_negative_infinity_is_not_missing(self):
        assert is_missing_value(-np.inf) is False


class TestMissingValuesNumericTypes:
    """Test missing value detection with various numeric types."""

    def test_numpy_int64_zero_is_not_missing(self):
        assert is_missing_value(np.int64(0)) is False

    def test_numpy_int64_positive_is_not_missing(self):
        assert is_missing_value(np.int64(42)) is False

    def test_numpy_float64_is_not_missing(self):
        assert is_missing_value(np.float64(1.5)) is False

    def test_numpy_float64_zero_is_not_missing(self):
        assert is_missing_value(np.float64(0.0)) is False


class TestMissingValuesContainers:
    """Test that container types are not treated as missing."""

    def test_empty_list_is_not_missing(self):
        """An empty list is an object, not a missing value."""
        assert is_missing_value([]) is False

    def test_empty_dict_is_not_missing(self):
        """An empty dict is an object, not a missing value."""
        assert is_missing_value({}) is False

    def test_non_empty_list_is_not_missing(self):
        assert is_missing_value([1, 2, 3]) is False

    def test_non_empty_dict_is_not_missing(self):
        assert is_missing_value({"key": "value"}) is False


class TestMissingValuesSpecialObjects:
    """Test that other objects are not treated as missing."""

    def test_object_instance_is_not_missing(self):
        """A generic object instance is not missing."""
        assert is_missing_value(object()) is False

    def test_callable_is_not_missing(self):
        """A function or callable is not missing."""
        assert is_missing_value(lambda: None) is False

    def test_type_is_not_missing(self):
        """A type object is not missing."""
        assert is_missing_value(str) is False
