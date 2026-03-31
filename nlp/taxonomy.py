"""
Aspect taxonomy for Netflix brand reputation pipeline.
Maps raw PyABSA aspect terms to 5 standardised categories.
Edit the keyword lists to improve mapping accuracy.
"""

TAXONOMY = {
    "price": [
        "price",
        "cost",
        "pricing",
        "expensive",
        "cheap",
        "subscription",
        "fee",
        "worth",
        "value",
        "money",
        "afford",
        "payment",
        "charge",
        "plan",
        "tier",
        "billing",
        "increase",
        "raise",
        "hike",
    ],
    "quality": [
        "quality",
        "content",
        "show",
        "movie",
        "series",
        "original",
        "library",
        "selection",
        "catalogue",
        "4k",
        "hd",
        "resolution",
        "picture",
        "video",
        "stream",
        "streaming",
        "buffer",
        "loading",
        "connection",
        "speed",
        "performance",
        "crash",
        "bug",
        "glitch",
    ],
    "support": [
        "support",
        "customer service",
        "help",
        "response",
        "refund",
        "complaint",
        "issue",
        "problem",
        "contact",
        "chat",
        "email",
        "agent",
        "representative",
        "resolution",
        "fix",
        "solve",
    ],
    "ux": [
        "ui",
        "interface",
        "design",
        "app",
        "layout",
        "navigation",
        "menu",
        "search",
        "recommendation",
        "algorithm",
        "feature",
        "update",
        "new",
        "change",
        "profile",
        "setting",
        "download",
        "offline",
        "notification",
        "autoplay",
        "skip",
    ],
    "delivery": [
        "delivery",
        "release",
        "new episode",
        "schedule",
        "availability",
        "region",
        "country",
        "vpn",
        "geo",
        "block",
        "access",
        "launch",
        "premiere",
        "date",
        "when",
        "wait",
        "delay",
        "cancel",
    ],
}

# Minimum confidence score to trust an aspect prediction
MIN_CONFIDENCE = 0.75

# Minimum text length to run ATEPC on (very short texts give poor results)
MIN_TEXT_LENGTH = 20


def map_to_taxonomy(aspect_term: str) -> str:
    """
    Map a raw PyABSA aspect term to one of the 5 taxonomy categories.
    Returns 'other' if no match found.
    """
    term = aspect_term.lower().strip()

    # exact match first
    for category, keywords in TAXONOMY.items():
        if term in keywords:
            return category

    # partial match second
    for category, keywords in TAXONOMY.items():
        for keyword in keywords:
            if keyword in term or term in keyword:
                return category

    return "other"


if __name__ == "__main__":
    # Test the taxonomy mapping
    test_terms = [
        "price",
        "content quality",
        "customer service",
        "streaming speed",
        "user interface",
        "new episodes",
        "4K resolution",
        "app design",
        "subscription fee",
        "buffering",
        "xyz_unknown_term",
    ]

    print("Taxonomy mapping test:\n")
    for term in test_terms:
        mapped = map_to_taxonomy(term)
        print(f"  {term:30} -> {mapped}")
