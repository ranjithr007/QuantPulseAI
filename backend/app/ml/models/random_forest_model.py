from sklearn.ensemble import RandomForestClassifier
import joblib

from app.ml.models.base_model import BaseMLModel


class RandomForestModel(BaseMLModel):

    def __init__(self):

        self.model = RandomForestClassifier(n_estimators=300, max_depth=8)

    def train(self, X, y):

        self.model.fit(X, y)

    def predict(self, X):

        return self.model.predict_proba(X)

    def save(self, path):

        joblib.dump(self.model, path)