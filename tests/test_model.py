import joblib

from predict import predict


def test_model_loads():
    assert joblib.load("model.pkl") is not None


def test_predict_returns_plausible_values():
    out = predict(4500, 14)
    assert isinstance(out["no2_ug_m3_predicted"], float)
    assert 0 <= out["no2_ug_m3_predicted"] <= 200
    assert 0 <= out["no2_exceedance_risk"] <= 1
