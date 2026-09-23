"""Public API schema; decimal response strings preserve exact values."""
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, field_validator

from .catalog import Origin
from .matching_models import Exclusion, MatchCounts, MatchStatus, RecommendationQuery, RejectionCode

Blank = Annotated[str, StringConstraints(pattern=r'^\s*$')]


class RecommendationRequest(RecommendationQuery):
    budget_kzt: StrictInt = Field(gt=0, le=9_007_199_254_740_991)

    @field_validator('duration_hours', mode='before', json_schema_input_type=float | Blank | None)
    @classmethod
    def duration_input_schema(cls, value: Any) -> Any:
        # Actual strict validation is inherited from RecommendationQuery.
        return value


EvidenceValue = str | int | bool | list[str] | None


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    field: str
    profile_value: EvidenceValue = None
    requested_value: EvidenceValue = None
    quote: str | None = None
    text: str
    display_is_cleaned: bool = False


class DataWarning(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    message: str
    evidence: Evidence | None = None
    profile_id: str | None = None


class RecommendationCard(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    anon_name: str
    category: str
    categories: list[str]
    city: str
    price_from_kzt: int
    price_label: str
    event_date: date
    availability_text: str
    languages: list[str]
    max_hours: str | None
    duration_text: str
    explanation: str
    evidence: list[Evidence]
    synthetic: bool
    city_imputed: bool
    price_imputed: bool
    origin: Origin
    labels: list[str]
    warnings: list[DataWarning]


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: MatchStatus
    message: str
    query: RecommendationQuery
    catalog_version: str
    ranking_version: str
    explanation_version: str
    counts: MatchCounts
    rejections: dict[RejectionCode, int]
    cards: list[RecommendationCard] = Field(max_length=3)
    warnings: list[DataWarning]
    eligible_ids: tuple[str, ...]
    exclusions: tuple[Exclusion, ...]


class ErrorIssue(BaseModel):
    field: str
    message: str


class ErrorResponse(BaseModel):
    code: Literal['INVALID_QUERY', 'CATALOG_LOAD_FAILED', 'INTERNAL_ERROR']
    message: str
    issues: list[ErrorIssue] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal['ready']
    profile_count: int
    catalog_version: str


class CatalogDictionaries(BaseModel):
    city: list[str]
    categories: list[str]
    event_formats: list[str]
    languages: list[str]


class CalendarWindow(BaseModel):
    start: date
    end: date


class QualityStats(BaseModel):
    synthetic: int
    city_imputed: int
    price_imputed: int
    null_max_hours: int


class CatalogMetadata(BaseModel):
    status: Literal['ready']
    catalog_version: str
    source_sha256: str
    origin: Origin
    profile_count: int
    calendar: CalendarWindow
    dictionaries: CatalogDictionaries
    quality: QualityStats
    city_counts: dict[str, int]
    category_counts: dict[str, int]
