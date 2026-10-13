"""Restaurant meals with provenance for manual checks or public page collection."""
import re
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VerifiedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Meal(VerifiedModel):
    name: str = Field(min_length=1, max_length=35)
    total_price: int = Field(strict=True, gt=0, le=1000000)
    diners: int = Field(default=1, strict=True, ge=1, le=10)
    source: str = Field(min_length=1, max_length=300)
    checked_on: date
    source_updated_on: date | None = None

    @field_validator("checked_on")
    @classmethod
    def not_future(cls, value):
        from app.services.restaurant_catalog import today_kst
        if value > today_kst():
            raise ValueError("확인일은 미래일 수 없습니다.")
        return value

    @property
    def per_person(self) -> int:
        # Round up fractional won so a set never understates its budget band.
        return (self.total_price + self.diners - 1) // self.diners


class Rating(VerifiedModel):
    score: float = Field(ge=0, le=5, allow_inf_nan=False)
    count: int = Field(strict=True, gt=0, le=100000000)
    source: Literal["kakao"] = "kakao"
    checked_at: datetime

    @field_validator("score")
    @classmethod
    def one_decimal(cls, value):
        if abs(value * 10 - round(value * 10)) > 0.000001:
            raise ValueError("평점은 소수점 한 자리까지 입력해주세요.")
        return value

    @field_validator("checked_at")
    @classmethod
    def aware_and_not_future(cls, value):
        from app.services.restaurant_catalog import now_kst
        if value.tzinfo is None or value.utcoffset() is None or value > now_kst():
            raise ValueError("평점 확인 시각은 시간대가 있는 현재/과거 시각이어야 합니다.")
        return value


class Restaurant(VerifiedModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,60}$")
    name: str = Field(min_length=1, max_length=35)
    area: Literal["궁동", "어은동", "죽동"]
    cuisine: str = Field(min_length=1, max_length=10)
    place_url: str
    enabled: bool = False
    reason: str = Field(default="", max_length=25)
    evidence: str = Field(min_length=1, max_length=300)
    meals: list[Meal] = Field(min_length=1, max_length=10)
    rating: Rating | None = None
    origin: Literal["manual", "kakao_public"] = "manual"

    @field_validator("place_url")
    @classmethod
    def kakao_place(cls, value):
        # A fixed destination prevents an operator typo becoming an open redirect.
        if not re.fullmatch(r"https?://place\.map\.kakao\.com/[0-9]+", value):
            raise ValueError("카카오맵 장소 상세 링크를 입력해주세요.")
        return value.replace("http://", "https://", 1)


class Catalog(VerifiedModel):
    schema_version: Literal[1] = 1
    revision: int = Field(default=0, strict=True, ge=0)
    ratings_enabled: bool = False
    rating_usage_basis: str = Field(default="", max_length=500)
    items: list[Restaurant] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def unique_and_authorized(self):
        for values in ([r.id for r in self.items], [urlsplit(r.place_url).path for r in self.items]):
            if len(values) != len(set(values)):
                raise ValueError("식당 ID 또는 카카오맵 장소가 중복되었습니다.")
        if self.ratings_enabled and not self.rating_usage_basis:
            raise ValueError("별점 사용 전에 데이터 이용 근거를 기록해주세요.")
        return self


class PlaceSearch(VerifiedModel):
    query: str = Field(min_length=2, max_length=80)
