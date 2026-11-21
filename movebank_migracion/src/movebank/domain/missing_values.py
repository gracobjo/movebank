import math
from decimal import Decimal
from numbers import Real

import numpy as np
import pandas as pd


def is_missing_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, np.datetime64):
        return bool(np.isnat(value))
    if isinstance(value, Decimal):
        return value.is_nan()
    if isinstance(value, Real):
        return math.isnan(value.__float__())
    return False
