import xgboost as xgb
import joblib

from app.ml.models.base_model import BaseMLModel


class XGBoostModel(BaseMLModel):

    def __init__(self):

        self.model = xgb.XGBClassifier(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=5,
            objective="binary:logistic",
        )

    def train(self, X, y):

        self.model.fit(X, y)

    def predict(self, X):

        return self.model.predict_proba(X)

    def save(self, path):

        joblib.dump(self.model, path)