"""Preregistered policy, not an arbitrary statistical-options API."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class Protocol(BaseModel):
    version: str = 'student-bundle-v1'
    policy_version: Literal['student-bundle-v1'] = 'student-bundle-v1'
    policy_checksum: str = ''
    eligibility_version: str = 'inline-common-v1'
    click_filter_version: Literal['signed-external-v1'] = 'signed-external-v1'
    total_users: int = Field(default=2200, ge=100, le=100000)
    observation_hours: Literal[168] = 168
    max_enrollment_days: Literal[28] = 28
    aa_enrollment_days: Literal[7] = 7
    collection_grace_hours: Literal[24] = 24
    alpha: Literal[0.05] = 0.05
    minimum_effect: float = Field(default=0.01, gt=0, lt=1)
    minimum_ci_lower: float = Field(default=0.005, gt=0, lt=1)
    target_effect: float = Field(default=0.025, gt=0, lt=1)
    safety_margin: float = Field(default=-0.20, lt=0)
    theta: float = Field(default=0.42026, ge=0, le=5)
    baseline_rate: float | None = Field(default=None, gt=0, lt=1)
    baseline_as_of: datetime | None = None
    baseline_source: str = ''
    simulation_seed: int = 20261008
    simulation_iterations: int = Field(default=100000, ge=1000, le=1000000)
    p95_limit_ms: float | None = Field(default=None, gt=0)
    minimum_bundle_completion: float | None = Field(default=None, gt=0, le=1)
    readiness_notes: str = ''
    device_qa_notes: str = ''
    aa_experiment_id: int | None = None

    @model_validator(mode='after')
    def validate_effects(self):
        if self.minimum_ci_lower > self.minimum_effect or self.minimum_effect > self.target_effect:
            raise ValueError('효과 기준은 CI 하한 ≤ 관측 최소 효과 ≤ 목표 효과여야 합니다.')
        if self.baseline_rate is not None and self.baseline_rate + self.target_effect >= 1:
            raise ValueError('기준율 + 목표 효과는 100% 미만이어야 합니다.')
        if self.baseline_as_of is not None and self.baseline_as_of.tzinfo is None:
            raise ValueError('기준 시각에 timezone을 포함하세요.')
        return self


class DesignInput(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    hypothesis: str = Field(min_length=3, max_length=2000)
    kind: Literal['aa', 'ab'] = 'ab'
    protocol: Protocol = Field(default_factory=Protocol)


class ActionInput(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class EnrollmentInput(ActionInput):
    action: Literal['start', 'pause', 'resume', 'close']


class AnalysisInput(ActionInput):
    idempotency_key: str = Field(min_length=1, max_length=100)
    watermark: datetime
    data_complete: bool = False

    @model_validator(mode='after')
    def aware(self):
        if self.watermark.tzinfo is None:
            raise ValueError('watermark에 timezone을 포함하세요.')
        return self


class PreviewInput(BaseModel):
    variant: Literal['A', 'B'] = 'B'


class DecisionInput(ActionInput):
    run_id: int
    choice: Literal['adopt', 'keep', 'inconclusive', 'followup']
