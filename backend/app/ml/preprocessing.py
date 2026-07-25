"""One leakage-safe preprocessing implementation for training and inference."""

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.preprocessing import StandardScaler
from sklearn.utils.validation import check_is_fitted

from backend.app.ml.schema import PCA_FEATURES, RAW_FEATURES

PREPROCESSING_VERSION = "preprocessing.v1"
MODEL_FEATURE_ORDER = (*PCA_FEATURES, "log1p_Amount")


class ULBPreprocessor(TransformerMixin, BaseEstimator):
    """Drop Time, log-transform Amount, and scale using training rows only."""

    def __init__(self) -> None:
        self.scaler = StandardScaler()

    def _validate_and_build(self, values: Any) -> np.ndarray:
        if not isinstance(values, pd.DataFrame):
            raise TypeError("ULBPreprocessor requires a pandas DataFrame")
        if tuple(values.columns) != RAW_FEATURES:
            raise ValueError(f"expected ordered fields {RAW_FEATURES}; got {tuple(values.columns)}")
        numeric = values.loc[:, RAW_FEATURES].to_numpy(dtype=np.float64)
        if not np.isfinite(numeric).all():
            raise ValueError("all model features must be finite")
        amount = numeric[:, -1]
        if (amount < 0).any():
            raise ValueError("Amount cannot be negative")
        pca_values = numeric[:, 1:-1]
        transformed_amount = np.log1p(amount).reshape(-1, 1)
        return np.concatenate([pca_values, transformed_amount], axis=1)

    def fit(self, X: Any, y: Any = None) -> "ULBPreprocessor":
        del y
        transformed = self._validate_and_build(X)
        self.scaler.fit(transformed)
        self.n_features_in_ = len(RAW_FEATURES)
        self.feature_names_in_ = np.asarray(RAW_FEATURES, dtype=object)
        return self

    def transform(self, X: Any) -> np.ndarray:
        check_is_fitted(self, attributes=("n_features_in_", "feature_names_in_"))
        transformed = self._validate_and_build(X)
        return np.asarray(self.scaler.transform(transformed), dtype=np.float64)

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        del input_features
        check_is_fitted(self, attributes=("n_features_in_",))
        return np.asarray(MODEL_FEATURE_ORDER, dtype=object)
