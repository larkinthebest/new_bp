import math


def retrieval_metrics(retrieved: list[str], relevant: dict[str, int], k: int):
    if k <= 0 or not any(v > 0 for v in relevant.values()):
        raise ValueError("Need k > 0 and at least one relevant segment")
    unique = list(dict.fromkeys(retrieved))[:k]
    gains = [relevant.get(segment, 0) for segment in unique]
    positive = sum(g > 0 for g in gains)
    ideal = sorted(relevant.values(), reverse=True)[:k]
    dcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))
    idcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return {
        "precision@k": positive / k,
        "recall@k": positive / sum(g > 0 for g in relevant.values()),
        "mrr": next((1 / (i + 1) for i, g in enumerate(gains) if g > 0), 0),
        "ndcg@k": dcg / idcg if idcg else 0,
        "hit_rate@k": float(positive > 0),
    }
