"""Unicode lexical TF + Qdrant corpus IDF; stable 32-bit features, no model download.

Unigrams plus adjacent bigrams preserve scores, clocks and phrases. Hash collisions
are possible; this is lexical ranking, not an exact-phrase database constraint.
"""

import hashlib
import math
import re
import unicodedata
from collections import Counter

from qdrant_client.models import SparseVector


def tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.replace("№", " ").replace("#", " ")).casefold()
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.findall(r"[^\W_]+(?:[:.-][^\W_]+)*", normalized, re.UNICODE)


def sparse(text: str) -> SparseVector:
    words = tokens(text)
    features = words + [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)]
    counts: Counter[int] = Counter()
    for feature in features:
        index = int.from_bytes(hashlib.blake2s(feature.encode(), digest_size=4).digest(), "big")
        counts[index] += 1
    indices = sorted(counts)
    return SparseVector(indices=indices, values=[1 + math.log(counts[i]) for i in indices])
