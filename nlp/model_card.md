# Model Card — Brand Sentiment Pipeline

*Generated: 2026-04-01*

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

## Manual evaluation (Reddit + news)

- **Labelled by:** human annotator
- **Sample size:** 100 records
- **Overall accuracy:** 70.0%

| Source | N | Accuracy |
|--------|---|----------|
| news | 19 | 36.8% |
| reddit | 81 | 77.8% |

| Class | Precision | Recall | F1 |
|-------|-----------|--------|----|
| POSITIVE | 0.750 | 0.730 | 0.740 |
| NEGATIVE | 0.750 | 0.824 | 0.785 |
| NEUTRAL | 0.125 | 0.083 | 0.100 |

## Limitations

- **NEUTRAL detection**: F1 ≈ 0.10 on both evaluations — distilBERT-SST2 is a binary classifier; neutral is inferred from confidence below 0.75, not a trained class. A three-class fine-tuned model would improve this materially
- **News accuracy (36.8%)**: news articles often mention Netflix incidentally alongside competitors; a relevance filter upstream would remove these before the sentiment model sees them
- **PyABSA aspect coverage**: 35% of records yield aspect-level signals; the remaining 65% fall back to distilBERT overall sentiment
- **Mock Reddit data**: live Reddit scraping was blocked by the environment; mock data follows similar linguistic patterns but lacks full diversity. Real Reddit data will improve coverage and evaluation quality
- **No fine-tuning**: both models are used zero-shot — fine-tuning on Netflix-specific labelled data would materially improve POSITIVE and NEUTRAL class performance

## Usage

```python
from nlp.sentiment_engine import run_sentiment_pipeline, run_fallback_pipeline
from config import BRAND_NAME, DB_PATH

run_sentiment_pipeline(db_path=DB_PATH, brand_name=BRAND_NAME)
run_fallback_pipeline(db_path=DB_PATH, brand_name=BRAND_NAME)
```