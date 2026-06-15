import pandas as pd


class FeatureEncoder:

    def encode(self, rows):

        data = []

        for x in rows:

            data.append(
                {
                    # Feature Factory
                    "trend_score": x.trend_score,
                    "momentum_score": x.momentum_score,
                    "volatility_score": x.volatility_score,
                    # Regime
                    "regime_confidence": x.regime_confidence,
                    "regime_bull": 1 if x.regime == "TRENDING_BULL" else 0,
                    "regime_bear": 1 if x.regime == "TRENDING_BEAR" else 0,
                    # Order Flow
                    "cvd": x.cvd,
                    "delta": x.delta,
                    # SMC
                    "smc_confidence": x.smc_confidence,
                    "smc_bull": 1 if x.smc_bias == "BULLISH" else 0,
                    "smc_bear": 1 if x.smc_bias == "BEARISH" else 0,
                }
            )

        return pd.DataFrame(data)