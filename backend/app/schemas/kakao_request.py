from pydantic import BaseModel


class UserRequest(BaseModel):
    utterance: str


class KakaoRequest(BaseModel):
    userRequest: UserRequest
