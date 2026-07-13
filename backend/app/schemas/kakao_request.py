from typing import Any

from pydantic import BaseModel, Field


class KakaoUser(BaseModel):
    id: str | None = None
    type: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class UserRequest(BaseModel):
    utterance: str
    user: KakaoUser | None = None


class KakaoAction(BaseModel):
    id: str | None = None
    name: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    detailParams: dict[str, Any] = Field(default_factory=dict)
    clientExtra: dict[str, Any] | None = None


class KakaoRequest(BaseModel):
    userRequest: UserRequest
    action: KakaoAction | None = None
