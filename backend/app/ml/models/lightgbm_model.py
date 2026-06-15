import lightgbm as lgb
import joblib

from app.ml.models.base_model import BaseMLModel


class LightGBMModel(BaseMLModel):

    def __init__(self):

        self.model = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05)

    def train(self, X, y):

        self.model.fit(X, y)

    def predict(self, X):

        return self.model.predict_proba(X)

    def save(self, path):

        joblib.dump(self.model, path)