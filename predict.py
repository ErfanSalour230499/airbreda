"""Load model.pkl and turn traffic + hour into a NO2 prediction and exceedance risk."""
import joblib
import numpy as np
import pandas as pd

# Threshold: 40 ug/m3 is the EU annual limit value (WHO's 2021 annual guideline is
# stricter, 10). Both are ANNUAL averages and we predict HOURLY values, so this is
# only a reasonable starting point, not a legal exceedance test.
THRESHOLD = 40.0
_model = joblib.load("model.pkl")


def exceedance_risk(predicted_no2, threshold=THRESHOLD, steepness=0.2):
    return float(1 / (1 + np.exp(-steepness * (predicted_no2 - threshold))))


def predict(total_intensity_veh_per_hr, hour_of_day):
    X = pd.DataFrame([[total_intensity_veh_per_hr, hour_of_day]],
                     columns=["total_intensity_veh_per_hr", "hour_of_day"])
    no2 = float(max(0.0, _model.predict(X)[0]))   # concentration cannot be negative
    return {"no2_ug_m3_predicted": no2, "no2_exceedance_risk": exceedance_risk(no2)}
