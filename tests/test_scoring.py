from app.models import Evidence, GameEvent, ScoreObservation
from app.scoring import goal_moment, score_anchors
from tests.conftest import make_segment


def evidence(scores, final=False):
    result = []
    for i, (a, b) in enumerate(scores):
        score = ScoreObservation(
            file_time=i * 6,
            team_a="PIT",
            score_a=a,
            team_b="NYI",
            score_b=b,
            period="OT" if final else None,
            game_clock=None,
            status="final" if final and i == len(scores) - 1 else "live",
        )
        segment = make_segment(i=i, start=i * 6, sport="ice hockey", scores=[score])
        result.append(
            Evidence(citation=i + 1, segment=segment, text="Goal! Replay!", kind="timeline")
        )
    return result


def test_replays_and_celebrations_do_not_create_extra_goals():
    items = evidence(
        [
            (0, 0),
            (1, 0),
            (0, 0),
            (1, 0),
            (1, 1),
            (1, 2),
            (2, 2),
            (1, 2),
            (2, 2),
            (3, 2),
            (3, 3),
            (4, 3),
            (4, 4),
            (4, 4),
            (4, 5),
        ],
        final=True,
    )
    game = score_anchors(items)[0]
    assert len(game["transitions"]) == 9
    assert game["final"]["score"] == [4, 5]
    assert game["transitions"][-1]["team"] == "NYI"


def test_last_score_is_not_automatically_final_and_jumps_are_not_invented_goals():
    game = score_anchors(evidence([(0, 0), (1, 0), (3, 0), (3, 1)]))[0]
    assert game["final"] is None
    assert len(game["transitions"]) == 2
    assert game["gaps"]


def test_goal_time_comes_from_observed_action_not_delayed_scoreboard():
    items = evidence([(4, 4), (4, 5)], final=True)
    items[0].segment.scores[0].file_time = 647
    items[1].segment.scores[0].file_time = 656
    items[1].segment.events = [
        GameEvent(
            file_time=648,
            event_type="goal",
            description="Overtime goal",
            team="NYI",
            player=None,
            is_replay=False,
            certainty="observed",
        )
    ]
    transition = score_anchors(items)[0]["transitions"][0]
    assert goal_moment(transition, items, "one") == (648, 2)
