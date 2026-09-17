"""Scoreboard anchors for goal sports; visual goal detections are not a goal counter."""

import re
from collections import Counter


def goal_moment(transition, evidence, content_id):
    lower = transition["before"]["file_time"] - 12
    upper = transition["after"]["file_time"] + 2
    team = re.sub(r"\W", "", transition["team"]).upper()
    moments = [
        (event.file_time, item.citation)
        for item in evidence
        if item.segment.content_id == content_id
        for event in item.segment.events
        if event.event_type == "goal"
        and event.certainty == "observed"
        and event.is_replay is not True
        and re.sub(r"\W", "", event.team or "").upper() == team
        and lower <= event.file_time <= upper
    ]
    return min(moments) if moments else None


def score_anchors(evidence):
    sports = " ".join(e.segment.sport or "" for e in evidence).lower()
    if not any(s in sports for s in ("hockey", "soccer", "association football")):
        return []
    results = []
    for content_id in dict.fromkeys(e.segment.content_id for e in evidence):
        records = []
        for item in evidence:
            if item.segment.content_id != content_id:
                continue
            for score in item.segment.scores:
                if score.status == "replay":
                    continue
                a, b = (re.sub(r"\W", "", t).upper() for t in (score.team_a, score.team_b))
                if not a or not b or a == b:
                    continue
                records.append((tuple(sorted((a, b))), a, b, score, item.citation))
        if not records:
            continue
        # Do not guess aliases: inconsistent team readings remain in the original evidence.
        pair = Counter(r[0] for r in records).most_common(1)[0][0]
        main = sorted((r for r in records if r[0] == pair), key=lambda r: r[3].file_time)
        first = main[0]
        team_a, team_b = first[3].team_a, first[3].team_b
        last, final, transitions, gaps = None, None, [], []
        for _, a, _, score, citation in main:
            values = (
                (score.score_a, score.score_b) if a == first[1] else (score.score_b, score.score_a)
            )
            current = {
                "score": list(values),
                "file_time": score.file_time,
                "period": score.period,
                "game_clock": score.game_clock,
                "citation": citation,
            }
            if last is None:
                last = current
                if values != (0, 0):
                    gaps.append("The first visible score is not 0–0.")
            elif values != tuple(last["score"]):
                delta = [n - old for n, old in zip(values, last["score"], strict=True)]
                if min(delta) < 0:
                    # A replay/OCR error/correction cannot establish a new goal.
                    continue
                if sum(delta) == 1:
                    transitions.append(
                        {"before": last, "after": current, "team": team_a if delta[0] else team_b}
                    )
                else:
                    gaps.append("A scoreboard jump contains unobserved intermediate scores.")
                last = current
            else:
                last = current
            if score.status == "final":
                final = current
        if transitions:
            results.append(
                {
                    "content_id": content_id,
                    "team_a": team_a,
                    "team_b": team_b,
                    "transitions": transitions,
                    "final": final,
                    "gaps": gaps,
                }
            )
    return results
