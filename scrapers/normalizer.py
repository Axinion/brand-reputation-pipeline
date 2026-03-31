import html
import re
import unicodedata


def clean_text(text):
    if not text:
        return ""

    text = html.unescape(str(text))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"\[\+\d+ chars\]", " ", text)
    text = re.sub(r"[^A-Za-z0-9\s\.,!?\-:'\"()]", " ", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_useful(text, min_length=15):
    cleaned = clean_text(text).lower().strip()
    junk = {"deleted", "removed", "edit"}
    if len(cleaned) < min_length:
        return False
    if cleaned in junk:
        return False
    return True


def normalize_mentions(mentions):
    kept = []
    dropped = 0

    for mention in mentions:
        normalized = clean_text(mention.get("text", ""))
        item = dict(mention)
        item["normalized_text"] = normalized
        if is_useful(normalized):
            kept.append(item)
        else:
            dropped += 1

    print(f"Normalization complete: kept {len(kept)}, dropped {dropped}")
    return kept
