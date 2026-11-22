import numpy as np
import pytest


@pytest.fixture
def synthetic_rc3_booster(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the installed rc3 feature and scoring contract without a private checkpoint."""
    from aml_ml import FEATURE_NAMES, serving_candidate

    class FixedBooster:
        def predict(self, matrix, *, pred_contribs=False):
            assert matrix.feature_names == list(FEATURE_NAMES)
            assert matrix.num_col() == 31
            rows = matrix.num_row()
            return np.zeros((rows, 32)) if pred_contribs else np.full(rows, 0.625)

    monkeypatch.setattr(serving_candidate, "load_candidate", FixedBooster)
