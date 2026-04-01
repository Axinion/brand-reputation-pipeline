import json
import sys
import warnings
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Allow imports from project root regardless of where the script is invoked from
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import sqlite_utils
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix


warnings.filterwarnings("ignore")


LABEL_ORDER = ["POSITIVE", "NEGATIVE", "NEUTRAL"]


def _map_stars_to_label(stars):
    try:
        s = int(stars)
    except Exception:
        return None
    if s <= 2:
        return "NEGATIVE"
    if s == 3:
        return "NEUTRAL"
    return "POSITIVE"


def load_ground_truth(db_path, brand_name):
    """
    Load Google Play reviews with both star rating (ground truth)
    and distilBERT prediction (model output) for evaluation.
    """
    db = sqlite_utils.Database(db_path)

    rows = list(
        db.execute(
            '''
        SELECT
            sm.mention_id,
            sm.sentiment       AS predicted_label,
            sm.confidence,
            rm.score           AS star_rating,
            sm.original_text   AS text
        FROM scored_mentions sm
        JOIN raw_mentions rm
          ON sm.mention_id = rm.id
        WHERE rm.source_detail = "google_play"
        AND   sm.aspect        = "overall"
        AND   rm.score         IS NOT NULL
        AND   rm.brand         = ?
    ''',
            [brand_name],
        ).fetchall()
    )

    print(f"Ground truth records found: {len(rows)}")

    records = []
    for row in rows:
        mention_id, predicted, confidence, stars, text = row

        # map star rating to true label
        stars = int(stars)
        if stars <= 2:
            true_label = "NEGATIVE"
        elif stars == 3:
            true_label = "NEUTRAL"
        else:
            true_label = "POSITIVE"

        records.append(
            {
                "mention_id": mention_id,
                "true_label": true_label,
                "predicted_label": predicted,
                "confidence": confidence,
                "star_rating": stars,
                "text": text,
            }
        )

    df = pd.DataFrame(records)
    print(f"Label distribution (ground truth):")
    print(df["true_label"].value_counts().to_string())
    print(f"\nLabel distribution (predicted):")
    print(df["predicted_label"].value_counts().to_string())

    return df


def compute_metrics(df):
    """Compute classification metrics against ground truth star ratings."""
    y_true = df["true_label"].tolist()
    y_pred = df["predicted_label"].tolist()

    labels = ["POSITIVE", "NEGATIVE", "NEUTRAL"]

    # overall accuracy
    accuracy = sum(t == p for t, p in zip(y_true, y_pred)) / len(y_true)

    # per-class report
    report = classification_report(
        y_true, y_pred,
        labels=labels,
        output_dict=True,
        zero_division=0
    )

    # formatted string version for printing
    report_str = classification_report(
        y_true, y_pred,
        labels=labels,
        zero_division=0
    )

    # confusion matrix
    cm = confusion_matrix(y_true, y_pred, labels=labels)

    metrics = {
        "accuracy": round(accuracy, 4),
        "report": report,
        "report_str": report_str,
        "confusion_matrix": cm.tolist(),
        "labels": labels,
        "n_samples": len(y_true),
    }

    print(f"\n{'='*50}")
    print(f"Overall accuracy: {accuracy:.1%}")
    print(f"\nClassification report:")
    print(report_str)

    print(f"Confusion matrix (rows=true, cols=predicted):")
    print(f"{'':12}", end="")
    for l in labels:
        print(f"{l:>10}", end="")
    print()
    for i, row_label in enumerate(labels):
        print(f"{row_label:12}", end="")
        for val in cm[i]:
            print(f"{val:>10}", end="")
        print()

    return metrics


def evaluate_by_confidence(df):
    """
    Show how model accuracy varies by prediction confidence.
    Higher confidence should mean higher accuracy.
    """
    df = df.copy()
    df["correct"] = df["true_label"] == df["predicted_label"]

    bins = {
        "low    (< 0.75)": df[df["confidence"] < 0.75],
        "medium (0.75-0.90)": df[(df["confidence"] >= 0.75) & (df["confidence"] < 0.90)],
        "high   (> 0.90)": df[df["confidence"] >= 0.90],
    }

    print(f"\nAccuracy by confidence band:")
    print(f"{'Band':25}  {'N':>5}  {'Accuracy':>9}")
    print("-" * 45)

    results = {}
    for band_name, subset in bins.items():
        if len(subset) == 0:
            print(f"{band_name:25}  {'0':>5}  {'n/a':>9}")
            continue
        acc = subset["correct"].mean()
        print(f"{band_name:25}  {len(subset):>5}  {acc:>9.1%}")
        results[band_name] = {
            "n": len(subset),
            "accuracy": round(float(acc), 4),
        }

    return results


def evaluate_by_source(db_path, brand_name):
    db = sqlite_utils.Database(db_path)
    rows = list(
        db.query(
            """
            SELECT
                rm.source,
                rm.source_detail,
                rm.score AS star_rating,
                sm.sentiment AS predicted_label
            FROM raw_mentions rm
            LEFT JOIN scored_mentions sm
              ON rm.id = sm.mention_id
             AND sm.aspect = 'overall'
            WHERE rm.brand = ?
            """,
            [brand_name],
        )
    )

    grouped = {}
    for r in rows:
        src = r["source"] or "unknown"
        grouped.setdefault(src, []).append(r)

    result = {}
    for src, items in grouped.items():
        eval_rows = []
        for r in items:
            true_label = _map_stars_to_label(r["star_rating"])
            pred = r["predicted_label"]
            if true_label is None or pred is None:
                continue
            eval_rows.append((true_label, str(pred).upper()))

        if not eval_rows:
            result[src] = {"n": 0, "accuracy": None, "note": "No star-rating ground truth"}
            continue

        y_true = [x[0] for x in eval_rows]
        y_pred = [x[1] for x in eval_rows]
        result[src] = {
            "n": len(eval_rows),
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "label_counts": dict(Counter(y_true)),
        }
    return result


def write_model_card(metrics, conf_analysis, output_path="nlp/model_card.md"):
    """Write a markdown model card with all evaluation results."""
    from datetime import datetime

    report = metrics["report"]
    labels = metrics["labels"]
    acc = metrics["accuracy"]
    n = metrics["n_samples"]

    lines = [
        "# Model Card — Brand Sentiment Pipeline",
        "",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d')}*",
        "",
        "## Model overview",
        "",
        "Two-stage sentiment analysis pipeline for brand reputation monitoring:",
        "",
        "| Stage | Model | Purpose |",
        "|-------|-------|---------|",
        "| 1 — Aspect extraction | PyABSA ATEPC (multilingual) | Extract aspect terms and per-aspect sentiment |",
        "| 2 — Overall fallback  | distilBERT-SST2             | Overall sentiment for records with no aspects found |",
        "",
        "## Evaluation dataset",
        "",
        f"- **Source:** Google Play Store reviews (Netflix app)",
        f"- **Ground truth:** Star ratings mapped to sentiment labels",
        f"- **Mapping:** 1–2 stars = NEGATIVE, 3 stars = NEUTRAL, 4–5 stars = POSITIVE",
        f"- **Evaluation set size:** {n} records",
        "",
        "## Overall results",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Overall accuracy | {acc:.1%} |",
        f"| Evaluation samples | {n} |",
        "",
        "## Per-class metrics",
        "",
        "| Class | Precision | Recall | F1 | Support |",
        "|-------|-----------|--------|----|---------|",
    ]

    for label in labels:
        if label in report:
            r = report[label]
            lines.append(
                f"| {label} | {r['precision']:.3f} | {r['recall']:.3f} "
                f"| {r['f1-score']:.3f} | {int(r['support'])} |"
            )

    lines += [
        "",
        "## Confidence analysis",
        "",
        "Higher-confidence predictions are more accurate:",
        "",
        "| Confidence band | N | Accuracy |",
        "|----------------|---|----------|",
    ]

    for band, vals in conf_analysis.items():
        lines.append(
            f"| {band.strip()} | {vals['n']} | {vals['accuracy']:.1%} |"
        )

    lines += [
        "",
        "## Limitations",
        "",
        "- PyABSA aspect coverage is 35% — most short/casual texts yield no aspects",
        "- distilBERT-SST2 only distinguishes positive/negative natively; neutral is inferred from low confidence",
        "- Evaluation is on app reviews only — Reddit and news accuracy is estimated, not measured",
        "- Mock Reddit data used during development; real Reddit data will improve coverage",
        "",
        "## Usage",
        "",
        "```python",
        "from nlp.sentiment_engine import run_sentiment_pipeline, run_fallback_pipeline",
        "from config import BRAND_NAME, DB_PATH",
        "",
        "run_sentiment_pipeline(db_path=DB_PATH, brand_name=BRAND_NAME)",
        "run_fallback_pipeline(db_path=DB_PATH, brand_name=BRAND_NAME)",
        "```",
    ]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines))
    print(f"\nModel card written to: {output_path}")


def main():
    import warnings
    warnings.filterwarnings("ignore")

    from config import BRAND_NAME, DB_PATH

    print("=" * 60)
    print(f"Model Evaluation | Brand: {BRAND_NAME}")
    print("=" * 60)

    # load ground truth
    df = load_ground_truth(DB_PATH, BRAND_NAME)

    if len(df) == 0:
        print("No ground truth records found. Check that:")
        print("  1. run_fallback_pipeline has been run")
        print("  2. Google Play reviews have score field populated")
        return

    # compute metrics
    metrics = compute_metrics(df)

    # confidence analysis
    conf_analysis = evaluate_by_confidence(df)

    # write model card
    write_model_card(metrics, conf_analysis)

    # save raw metrics as JSON for later use
    import json
    metrics_out = {
        "accuracy":          metrics["accuracy"],
        "n_samples":         metrics["n_samples"],
        "report":            metrics["report"],
        "confidence_bands":  conf_analysis,
    }
    Path("nlp/metrics.json").write_text(
        json.dumps(metrics_out, indent=2)
    )
    print("Raw metrics saved to nlp/metrics.json")


if __name__ == "__main__":
    main()
