# app/ml/trainer.py

import joblib
import os

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

from app.ml.dataset_builder import DatasetBuilder


MODEL_PATH = "models/quantpulse_model.pkl"


class ModelTrainer:

    def __init__(self, db):
        self.db = db
        self.model = RandomForestClassifier(n_estimators=200, random_state=42)

    def train(self):

        builder = DatasetBuilder(self.db)

        X, y = builder.build()

        if len(X) == 0:
            return {"status": "failed", "message": "No training data available"}

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, shuffle=False
        )

        self.model.fit(X_train, y_train)

        predictions = self.model.predict(X_test)

        accuracy = accuracy_score(y_test, predictions)

        os.makedirs("models", exist_ok=True)

        joblib.dump(self.model, MODEL_PATH)

        return {"status": "success", "accuracy": accuracy, "model": MODEL_PATH}