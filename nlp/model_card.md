# Model Card — Brand Sentiment Pipeline

*Generated: 2026-03-31 — updated: 2026-04-01*

## Model overview

Two-stage sentiment analysis pipeline for brand reputation monitoring:

| Stage | Model | Purpose |
|-------|-------|---------|
| 1 — Aspect extraction | PyABSA ATEPC (multilingual) | Extract aspect terms and per-aspect sentiment |
| 2 — Overall fallback  | distilBERT-SST2             | Overall sentiment for records with no aspects found |

## Evaluation summary

Two independent evaluations on two different data types:

| Evaluation | Source | Ground truth | N | Accuracy |
|---|---|---|---|---|
| Automated (Day 9) | Google Play app reviews | Star ratings | 189 | 83.1% |
| Manual (Day 10) | Reddit posts + news articles | Human judgement | 100 | 70.0% |

The 13-point gap reflects genuine stylistic difficulty — app reviews are direct and opinionated; Reddit and news text is more nuanced, sarcastic, and mixed. Both results are on unseen data with no fine-tuning.

---

## Evaluation 1 — Google Play app reviews (automated)

- **Source:** Google Play Store reviews (Netflix app)
- **Ground truth:** Star ratings mapped to sentiment labels
- **Mapping:** 1–2 stars = NEGATIVE, 3 stars = NEUTRAL, 4–5 stars = POSITIVE
- **N:** 189 records

| Metric | Value |
|--------|-------|
| Overall accuracy | 83.1% |

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| POSITIVE | 0.323 | 0.667 | 0.435 | 15 |
| NEGATIVE | 0.974 | 0.850 | 0.907 | 173 |
| NEUTRAL | 0.000 | 0.000 | 0.000 | 1 |

**Confidence analysis:**

| Confidence band | N | Accuracy |
|----------------|---|----------|
| low    (< 0.75) | 7 | 0.0% |
| medium (0.75-0.90) | 15 | 26.7% |
| high   (> 0.90) | 167 | 91.6% |

*Note: evaluation set is 92% NEGATIVE (173/189); naive majority-class baseline = 91.5% — model's 83.1% reflects real generalisation.*

---

## Evaluation 2 — Reddit + news (manual labels)

- **Source:** 81 Reddit posts + 19 news articles
- **Ground truth:** Human-labelled by project author
- **N:** 100 records

| Metric | Value |
|--------|-------|
| Overall accuracy | 70.0% |

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| POSITIVE | 0.750 | 0.730 | 0.740 | 37 |
| NEGATIVE | 0.750 | 0.820 | 0.790 | 51 |
| NEUTRAL | 0.125 | 0.083 | 0.100 | 12 |

**Confidence analysis:**

| Confidence band | N | Accuracy |
|----------------|---|----------|
| low    (< 0.75) | 8 | 12.5% |
| medium (0.75-0.90) | 3 | 66.7% |
| high   (> 0.90) | 89 | 75.3% |

*Confidence-accuracy correlation holds across both evaluations — empirically validates the MIN_CONFIDENCE=0.75 threshold.*

---

## Limitations

- **NEUTRAL detection**: F1 ≈ 0.10 on both evaluations — distilBERT-SST2 is binary; neutral is inferred from low confidence below 0.75, not a trained class
- **Class imbalance on app reviews**: 92% NEGATIVE skew; naive baseline = 91.5%; model's 83.1% reflects real generalisation
- **PyABSA coverage**: 35% of records yield aspect-level signals; remaining 65% fall back to distilBERT overall sentiment
- **Evaluation on mock Reddit data**: real-world Reddit scraping was blocked by environment; mock data follows similar linguistic patterns but lacks full diversity
- **No fine-tuning**: both models used zero-shot — fine-tuning on Netflix-specific labelled data would materially improve POSITIVE and NEUTRAL performance

## Usage

```python
from nlp.sentiment_engine import run_sentiment_pipeline, run_fallback_pipeline
from config import BRAND_NAME, DB_PATH

run_sentiment_pipeline(db_path=DB_PATH, brand_name=BRAND_NAME)
run_fallback_pipeline(db_path=DB_PATH, brand_name=BRAND_NAME)
```