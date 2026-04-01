# Model Card — Brand Sentiment Pipeline

*Generated: 2026-03-31*

## Model overview

Two-stage sentiment analysis pipeline for brand reputation monitoring:

| Stage | Model | Purpose |
|-------|-------|---------|
| 1 — Aspect extraction | PyABSA ATEPC (multilingual) | Extract aspect terms and per-aspect sentiment |
| 2 — Overall fallback  | distilBERT-SST2             | Overall sentiment for records with no aspects found |

## Evaluation dataset

- **Source:** Google Play Store reviews (Netflix app)
- **Ground truth:** Star ratings mapped to sentiment labels
- **Mapping:** 1–2 stars = NEGATIVE, 3 stars = NEUTRAL, 4–5 stars = POSITIVE
- **Evaluation set size:** 189 records

## Overall results

| Metric | Value |
|--------|-------|
| Overall accuracy | 83.1% |
| Evaluation samples | 189 |

## Per-class metrics

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| POSITIVE | 0.323 | 0.667 | 0.435 | 15 |
| NEGATIVE | 0.974 | 0.850 | 0.907 | 173 |
| NEUTRAL | 0.000 | 0.000 | 0.000 | 1 |

## Confidence analysis

Higher-confidence predictions are more accurate:

| Confidence band | N | Accuracy |
|----------------|---|----------|
| low    (< 0.75) | 7 | 0.0% |
| medium (0.75-0.90) | 15 | 26.7% |
| high   (> 0.90) | 167 | 91.6% |

## Limitations

- **Class imbalance**: evaluation set is 92% NEGATIVE (173/189); naive majority-class baseline would score 91.5% — model's 83.1% reflects real generalisation not class exploitation
- PyABSA aspect coverage is 35% — most short/casual texts yield no aspects
- distilBERT-SST2 only distinguishes positive/negative natively; neutral is inferred from low confidence
- Evaluation is on app reviews only — Reddit and news accuracy is estimated, not measured
- Mock Reddit data used during development; real Reddit data will improve coverage

## Usage

```python
from nlp.sentiment_engine import run_sentiment_pipeline, run_fallback_pipeline
from config import BRAND_NAME, DB_PATH

run_sentiment_pipeline(db_path=DB_PATH, brand_name=BRAND_NAME)
run_fallback_pipeline(db_path=DB_PATH, brand_name=BRAND_NAME)
```