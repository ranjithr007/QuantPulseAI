# QuantPulseAI Walk-Forward Loss-Cluster Report

- Data cutoff: 2026-08-23T16:00:00+00:00
- Trades loaded: 158
- Ledger complete: Yes
- Staged-exit parity: Yes
- Production policy changed: No
- Holdout validation required: Yes

## Overall diagnostic

- Trades: 158
- Wins / losses / breakeven: 57 / 101 / 0
- Win rate: 36.08%
- Net PnL: -1072.33
- Sum of trade PnL percentages: -10.9788%
- Profit factor: 0.8242
- Total modeled execution costs: 1973.2
- Gross-positive trades made non-positive by costs: 0

> PnL sums combine independently replayed symbol/timeframe/direction scopes and are diagnostic, not a portfolio return.

## By Symbol

| Cluster | Trades | Win % | Net PnL | PnL % sum | PF | Costs | Loss contribution % |
|---|---:|---:|---:|---:|---:|---:|---:|
| SOLUSDT | 37 | 27.03 | -733.22 | -7.5534 | 0.5479 | 460.04 | 26.59 |
| DOGEUSDT | 41 | 31.71 | -534.5 | -5.5174 | 0.6767 | 499.5 | 27.11 |
| XRPUSDT | 43 | 39.53 | -109.71 | -1.001 | 0.9313 | 545.57 | 26.18 |
| BTCUSDT | 11 | 45.45 | 75.63 | 0.7399 | 1.2085 | 137.71 | 5.95 |
| BNBUSDT | 1 | 100.0 | 101.89 | 1.0189 | - | 12.77 | 0.0 |
| ETHUSDT | 25 | 44.0 | 127.58 | 1.3342 | 1.1476 | 317.61 | 14.17 |

## By Timeframe

| Cluster | Trades | Win % | Net PnL | PnL % sum | PF | Costs | Loss contribution % |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1h | 102 | 35.29 | -861.84 | -8.6391 | 0.7837 | 1271.21 | 65.33 |
| 4h | 34 | 29.41 | -506.61 | -5.3233 | 0.6472 | 422.06 | 23.55 |
| 2h | 20 | 45.0 | 92.12 | 0.9436 | 1.1359 | 254.61 | 11.12 |
| 1d | 2 | 100.0 | 204.0 | 2.04 | - | 25.33 | 0.0 |

## By Side

| Cluster | Trades | Win % | Net PnL | PnL % sum | PF | Costs | Loss contribution % |
|---|---:|---:|---:|---:|---:|---:|---:|
| LONG | 123 | 31.71 | -1593.62 | -16.2232 | 0.6845 | 1528.79 | 82.82 |
| SHORT | 35 | 51.43 | 521.29 | 5.2444 | 1.4977 | 444.42 | 17.18 |

## By Regime

| Cluster | Trades | Win % | Net PnL | PnL % sum | PF | Costs | Loss contribution % |
|---|---:|---:|---:|---:|---:|---:|---:|
| LIQUIDITY_GRAB_BULLISH | 36 | 22.22 | -891.04 | -9.1527 | 0.4681 | 445.64 | 27.47 |
| HIGH_VOLATILITY_BREAKOUT | 87 | 35.63 | -702.58 | -7.0705 | 0.7919 | 1083.15 | 55.35 |
| LIQUIDITY_GRAB_BEARISH | 20 | 45.0 | 105.63 | 1.1097 | 1.1553 | 254.0 | 11.15 |
| HIGH_VOLATILITY_BREAKDOWN | 15 | 60.0 | 415.66 | 4.1347 | 2.1314 | 190.42 | 6.02 |

## By Confidence Band

| Cluster | Trades | Win % | Net PnL | PnL % sum | PF | Costs | Loss contribution % |
|---|---:|---:|---:|---:|---:|---:|---:|
| 40-49.99 | 138 | 37.68 | -637.99 | -6.4833 | 0.8772 | 1723.44 | 85.21 |
| 50-59.99 | 20 | 25.0 | -434.34 | -4.4955 | 0.5186 | 249.77 | 14.79 |

## By Exit Reason

| Cluster | Trades | Win % | Net PnL | PnL % sum | PF | Costs | Loss contribution % |
|---|---:|---:|---:|---:|---:|---:|---:|
| STOP | 101 | 0.0 | -6098.12 | -61.9165 | 0.0 | 1257.35 | 100.0 |
| PROTECTED_STOP | 29 | 100.0 | 2205.03 | 22.2794 | - | 365.22 | 0.0 |
| TARGET2 | 28 | 100.0 | 2820.76 | 28.6583 | - | 350.64 | 0.0 |

## By Exit Path

| Cluster | Trades | Win % | Net PnL | PnL % sum | PF | Costs | Loss contribution % |
|---|---:|---:|---:|---:|---:|---:|---:|
| STOP | 101 | 0.0 | -6098.12 | -61.9165 | 0.0 | 1257.35 | 100.0 |
| TARGET1 -> PROTECTED_STOP | 29 | 100.0 | 2205.03 | 22.2794 | - | 365.22 | 0.0 |
| TARGET1 -> TARGET2 | 28 | 100.0 | 2820.76 | 28.6583 | - | 350.64 | 0.0 |

## By Scope

| Cluster | Trades | Win % | Net PnL | PnL % sum | PF | Costs | Loss contribution % |
|---|---:|---:|---:|---:|---:|---:|---:|
| SOLUSDT 4h LONG | 21 | 14.29 | -771.81 | -7.982 | 0.2758 | 256.95 | 17.48 |
| DOGEUSDT 1h LONG | 39 | 28.21 | -709.6 | -7.261 | 0.5708 | 474.23 | 27.11 |
| BTCUSDT 1h LONG | 8 | 25.0 | -178.07 | -1.7762 | 0.509 | 99.62 | 5.95 |
| XRPUSDT 2h SHORT | 5 | 20.0 | -169.8 | -1.7021 | 0.3033 | 63.76 | 4.0 |
| ETHUSDT 1h LONG | 16 | 37.5 | -96.12 | -0.924 | 0.844 | 203.41 | 10.11 |
| XRPUSDT 4h LONG | 6 | 33.33 | -43.05 | -0.4134 | 0.8254 | 76.29 | 4.04 |
| SOLUSDT 1h SHORT | 7 | 42.86 | 18.81 | 0.2076 | 1.0765 | 88.44 | 4.03 |
| SOLUSDT 2h SHORT | 9 | 44.44 | 19.78 | 0.221 | 1.0638 | 114.66 | 5.08 |
| ETHUSDT 4h SHORT | 4 | 50.0 | 54.55 | 0.556 | 1.4412 | 50.73 | 2.03 |
| ETHUSDT 2h SHORT | 4 | 50.0 | 67.04 | 0.6811 | 1.5398 | 50.91 | 2.04 |
| BNBUSDT 1d LONG | 1 | 100.0 | 101.89 | 1.0189 | - | 12.77 | 0.0 |
| ETHUSDT 1d SHORT | 1 | 100.0 | 102.11 | 1.0211 | - | 12.56 | 0.0 |
| XRPUSDT 1h LONG | 32 | 43.75 | 103.14 | 1.1145 | 1.0933 | 405.51 | 18.13 |
| DOGEUSDT 2h SHORT | 2 | 100.0 | 175.1 | 1.7436 | - | 25.28 | 0.0 |
| BTCUSDT 4h SHORT | 3 | 100.0 | 253.7 | 2.5161 | - | 38.09 | 0.0 |

## Research hypotheses

These are ranked loss clusters, not automatic trading blockers.

| Rank | Dimension | Cluster | Trades | Win % | Net PnL | PF | Loss contribution % |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | exit_path | STOP | 101 | 0.0 | -6098.12 | 0.0 | 100.0 |
| 2 | regime | LIQUIDITY_GRAB_BULLISH | 36 | 22.22 | -891.04 | 0.4681 | 27.47 |
| 3 | scope | SOLUSDT 4h LONG | 21 | 14.29 | -771.81 | 0.2758 | 17.48 |
| 4 | scope | DOGEUSDT 1h LONG | 39 | 28.21 | -709.6 | 0.5708 | 27.11 |
| 5 | regime | HIGH_VOLATILITY_BREAKOUT | 87 | 35.63 | -702.58 | 0.7919 | 55.35 |
| 6 | confidence_band | 50-59.99 | 20 | 25.0 | -434.34 | 0.5186 | 14.79 |
| 7 | scope | BTCUSDT 1h LONG | 8 | 25.0 | -178.07 | 0.509 | 5.95 |
| 8 | scope | XRPUSDT 2h SHORT | 5 | 20.0 | -169.8 | 0.3033 | 4.0 |

## Governance conclusion

Clusters describe this sample only. Validate hypotheses on a later untouched cutoff before changing paper-trade eligibility.
No live-trading promotion is authorized by this report.
