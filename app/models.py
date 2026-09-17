from typing import Annotated, Literal
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Name = Annotated[str, Field(min_length=1, max_length=160)]


class Metadata(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    match_id: str | None = Field(None, max_length=200)
    teams: list[Name] = Field(default_factory=list, max_length=20)
    players: list[Name] = Field(default_factory=list, max_length=100)
    competition: str | None = Field(None, max_length=200)
    season: str | None = Field(None, max_length=40)
    half: str | None = Field(None, max_length=50)
    # Match clock offset is supplied by the user, never inferred from video time.
    match_clock_offset: float | None = None
    source_url: str | None = Field(None, max_length=2000)

    @field_validator("source_url")
    @classmethod
    def safe_source_url(cls, value):
        if value is not None:
            url = urlparse(value)
            if url.scheme not in {"http", "https"} or not url.netloc:
                raise ValueError("source_url must be an HTTP(S) URL")
        return value


class ScoreObservation(BaseModel):
    file_time: float = Field(ge=0)
    team_a: str
    score_a: int = Field(ge=0, le=200)
    team_b: str
    score_b: int = Field(ge=0, le=200)
    period: str | None
    game_clock: str | None
    status: Literal["live", "replay", "final", "unknown"]


class GameEvent(BaseModel):
    file_time: float = Field(ge=0)
    event_type: Literal["goal", "shot", "save", "penalty", "period_end", "game_end", "other"]
    description: str
    team: str | None
    player: str | None
    is_replay: bool | None
    certainty: Literal["observed", "possible"]


class VideoObservation(BaseModel):
    sport: str
    description: str
    scores: list[ScoreObservation] = Field(max_length=6)
    events: list[GameEvent] = Field(max_length=6)


class TimelineFinding(BaseModel):
    description: str
    citations: list[int] = Field(min_length=1, max_length=8)


class TimelineReview(BaseModel):
    findings: list[TimelineFinding] = Field(max_length=24)


class GoalExplanation(BaseModel):
    scorer: str | None
    mechanism: str
    citations: list[int] = Field(min_length=1, max_length=6)


class Segment(Metadata):
    content_id: str
    segment_id: str
    content_type: Literal["video", "audio", "document"]
    segment_index: int = Field(ge=0)
    source: str
    start_time: float | None = Field(None, ge=0)
    end_time: float | None = Field(None, ge=0)
    transcript: str = ""
    visual_description: str = ""
    audio_description: str = ""
    page: int | None = None
    index_version: str = ""
    state: str = "staged"
    ingestion_version: str = "legacy-v1"
    frame_times: list[float] = Field(default_factory=list)
    sport: str | None = None
    scores: list[ScoreObservation] = Field(default_factory=list)
    events: list[GameEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_times(self):
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("Both timestamps are required")
        if self.start_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must exceed start_time")
        return self

    def text(self) -> str:
        fields = {
            "source": self.source,
            "match": self.match_id,
            "teams": self.teams,
            "players": self.players,
            "competition": self.competition,
            "season": self.season,
            "half": self.half,
            "video_time": self.start_time,
            "transcript": self.transcript,
            "visual": self.visual_description,
            "audio": self.audio_description,
            "score_observations": [s.model_dump() for s in self.scores],
            "events": [e.model_dump() for e in self.events],
        }
        return "\n".join(f"{key}: {value}" for key, value in fields.items() if value)


def segment_id(content_id: str, index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"touchline:{content_id}:{index}"))


class QueryPlan(BaseModel):
    resolved_query: str = Field(max_length=2000)
    queries: list[str] = Field(max_length=4)
    focus: Literal["balanced", "transcript", "visual", "audio"]
    neighbor_seconds: int = Field(ge=15, le=30)
    scope: Literal["local", "whole_match"] = "local"


class RankItem(BaseModel):
    segment_id: str
    relevance: float = Field(ge=0, le=1)


class Ranking(BaseModel):
    items: list[RankItem]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    content_ids: list[str] = Field(default_factory=list, max_length=30)
    match_id: str | None = None
    top_k: int = Field(6, ge=1, le=8)

    @field_validator("query")
    @classmethod
    def non_blank_query(cls, value):
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20000)


class ChatRequest(SearchRequest):
    chat_id: str | None = None
    incognito: bool = False
    history: list[Turn] = Field(default_factory=list, max_length=12)


class Hit(BaseModel):
    segment: Segment
    score: float
    kind: Literal["match", "neighbor"] = "match"


class Evidence(BaseModel):
    citation: int
    segment: Segment
    kind: str
    text: str

    def prompt_data(self):
        s = self.segment
        return {
            "citation": self.citation,
            "kind": self.kind,
            "content_id": s.content_id,
            "source": s.source,
            "file_start": s.start_time,
            "file_end": s.end_time,
            "match_id": s.match_id,
            "page": s.page,
            "sport": s.sport,
            "half": s.half,
            "match_clock_offset": s.match_clock_offset,
            "transcript": s.transcript,
            "visual": s.visual_description,
            "audio": s.audio_description,
            "scores": [x.model_dump() for x in s.scores],
            "events": [x.model_dump() for x in s.events],
        }


class Coverage(BaseModel):
    mode: Literal["local", "whole_match"]
    scanned_segments: int
    included_segments: int
    complete: bool
    content_ids: list[str]
    note: str
