"""Pydantic schemas for every tracked CSV in the platform.

Each model's field order defines the canonical column order for its CSV. `common.checks`
and the writer scripts import these models to validate rows before they are persisted.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Scope = Literal["PT", "EU", "World"]
Grade = Literal["A", "B", "C"]
SourceNature = Literal["primary", "secondary", "news"]
SourceStatus = Literal["tested", "excluded"]
ClaimType = Literal["data", "fact", "event", "link"]
BreakType = Literal["level", "slope", "peak"]
LinkStatus = Literal["linked", "break_without_event", "event_without_effect"]

EVENT_TYPES = [
    "lei_ou_decreto_lei",
    "orcamento_do_estado",
    "mudanca_de_governo",
    "eleicao",
    "diretiva_ou_regulamento_europeu",
    "programa_ou_plano_nacional",
    "crise_economica_ou_intervencao_externa",
    "pandemia_ou_crise_sanitaria",
    "catastrofe_natural_ou_climatica",
    "greve_ou_conflito_laboral",
    "evento_internacional_relevante",
]


class Event(BaseModel):
    id: str
    start_date: dt.date
    end_date: dt.date | None = None
    scope: Scope
    type: str
    title_pt: str
    title_en: str
    description_pt: str
    description_en: str
    primary_source_url: str
    secondary_source_url: str | None = None
    access_date: dt.date
    topics: str  # semicolon-separated list
    verified: Literal["yes", "no"]


class DataSource(BaseModel):
    id: str
    axis: str
    name: str
    organisation: str
    url: str
    format: str
    license: str
    temporal_coverage: str
    geographic_coverage: str
    status: SourceStatus
    exclusion_reason: str | None = None
    verification_date: dt.date | None = None


class Break(BaseModel):
    id: str
    series: str
    axis: str
    date: dt.date
    type: BreakType
    magnitude: float
    method: str
    ci_low: dt.date | None = None
    ci_high: dt.date | None = None
    note: str | None = None


class EventLink(BaseModel):
    id: str
    break_id: str | None = None
    event_id: str | None = None
    status: LinkStatus
    grade: Grade | None = None
    justification_window: str
    justification_pt: str
    justification_en: str


class Claim(BaseModel):
    id: str = Field(pattern=r"^c\d+$")
    type: ClaimType
    text_pt: str
    text_en: str
    value: str | None = None
    unit: str | None = None
    source_id: str
    url: str
    access_date: dt.date
    excerpt: str
    source_nature: SourceNature
    location: str
    clean_file: str | None = None
    calculation: str | None = None
    grade: Grade | None = None
    verification_status: Literal["pending", "confirmed", "failed"] = "pending"


CSV_SCHEMAS: dict[str, type[BaseModel]] = {
    "events.csv": Event,
    "sources.csv": DataSource,
    "breaks.csv": Break,
    "event_links.csv": EventLink,
    "claims.csv": Claim,
}
