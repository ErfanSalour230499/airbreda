"""Train a simple linear regression on training_data.csv and save model.pkl."""
import joblib
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

df = pd.read_csv("training_data.csv")
X = df[["total_intensity_veh_per_hr", "hour_of_day"]]
y = df["no2_ug_m3"]
print("rows:", len(df))

if len(df) >= 20:
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)
else:
    # Too few rows for a meaningful hold-out set: evaluate in-sample and say so.
    Xtr, Xte, ytr, yte = X, X, y, y
    print("WARNING: <20 rows, no real test set. Scores below are in-sample only.")

model = LinearRegression().fit(Xtr, ytr)
pred = model.predict(Xte)
print("R2 :", round(r2_score(yte, pred), 3) if len(yte) > 1 else "n/a")
print("MAE:", round(mean_absolute_error(yte, pred), 2), "ug/m3")
print("coef (traffic, hour):", model.coef_, "intercept:", model.intercept_)
joblib.dump(model, "model.pkl")
import json, datetime
json.dump({"rows": len(df), "in_sample": len(df) < 20,
           "r2": round(float(r2_score(yte, pred)), 3) if len(yte) > 1 else None,
           "mae": round(float(mean_absolute_error(yte, pred)), 2),
           "trained_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"),
           "features": ["total_intensity_veh_per_hr", "hour_of_day"]}, open("model_info.json", "w"))
print("saved model.pkl")
