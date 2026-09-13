"""Validated administrator request bodies, shared by HTTP endpoints."""
from typing import Any
from pydantic import BaseModel, Field


class VariantInput(BaseModel):
    variant_key: str
    label: str
    config: dict[str, Any] = Field(default_factory=dict)
    weight: int = Field(default=50, ge=0)


class ExperimentInput(BaseModel):
    experiment_key: str | None = None
    name: str
    hypothesis: str
    primary_metric: str
    guardrail_metric: str | None = None
    unit: str = "user"
    alpha: float = Field(default=0.05, gt=0, lt=1)
    power: float = Field(default=0.8, gt=0, lt=1)
    baseline_rate: float | None = Field(default=None, gt=0, lt=1)
    mde: float | None = Field(default=0.03, gt=0, lt=1)
    variants: list[VariantInput] = Field(min_length=2)


class SuggestInput(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)


class ShareTextInput(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
