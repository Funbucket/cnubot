"""Shared, atomically saved promotion configuration in the persistent data volume."""
import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

DISCLOSURE = "이 포스팅은 토스쇼핑 쉐어링크 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."


def validate_link(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"https://toss\.im/_m/[A-Za-z0-9_-]+", value):
        raise ValueError("https://toss.im/_m/ 형태의 토스 공유 링크를 입력해주세요.")
    return value


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    url: str
    button_label: str = Field(default="상품 가격 보기", min_length=1, max_length=14)
    description: str = Field(default="", max_length=180)
    image_url: str = Field(default="", max_length=2000)
    enabled: bool = True

    _link = field_validator("url")(validate_link)

    @field_validator("image_url")
    @classmethod
    def image_link(cls, value):
        parsed = urlparse(value)
        if value and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password):
            raise ValueError("이미지는 HTTPS URL이어야 합니다.")
        return value


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    revision: int = Field(default=0, ge=0)
    mode: Literal["algorithm", "fixed"] = "algorithm"
    menu_button_label: str = Field(default="", max_length=14)
    quick_reply_label: str = Field(default="", max_length=20)
    products: list[Product] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_products(self):
        links = [p.url for p in self.products]
        if len(links) != len(set(links)):
            raise ValueError("같은 공유 링크가 중복되었습니다.")
        active = sum(p.enabled for p in self.products)
        if active > 6:
            raise ValueError("노출 상품은 최대 6개입니다. 나머지는 숨김으로 보관해주세요.")
        if self.mode == "fixed" and not active:
            raise ValueError("고정 모드에는 노출할 상품이 최소 1개 필요합니다.")
        return self


def settings_path() -> Path:
    return Path(os.getenv("MENU_DATA_DIR", "/data/menus")) / "promotion_settings.json"


def read_settings() -> Settings:
    try:
        return Settings.model_validate_json(settings_path().read_text())
    except FileNotFoundError:
        return Settings()


def save_settings(settings: Settings) -> Settings:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = read_settings()
        if current.revision != settings.revision:
            raise ValueError("다른 창에서 설정이 변경되었습니다. 새로고침 후 다시 저장해주세요.")
        saved = settings.model_copy(update={"revision": settings.revision + 1})
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".promotion-")
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(saved.model_dump_json(indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return saved


def product_key(url: str) -> str:
    return "fixed_" + hashlib.sha256(url.encode()).hexdigest()[:16]


def fixed_products(settings: Settings) -> list[tuple[str, dict]]:
    return [(product_key(p.url), {**p.model_dump(), "selection_mode": "fixed",
             "candidate_sources": ["admin_fixed"], "settings_revision": settings.revision})
            for p in settings.products if p.enabled]


def parse_share_text(text: str) -> Product:
    urls = re.findall(r"https?://[^\s<>]+", text)
    if len(urls) != 1:
        raise ValueError("상품 하나의 공유 문구와 링크 하나를 붙여넣어주세요.")
    url = validate_link(urls[0])
    lines = [line.strip() for line in text.replace(url, "").splitlines()
             if line.strip() and not any(word in line for word in ("수수료", "쉐어링크 활동"))]
    return Product(title=" ".join(lines) or "토스쇼핑 상품", url=url)


def enrich_product(product: Product) -> Product:
    """Optional OpenGraph lookup; preserve the exact affiliate URL and supplied title."""
    url = product.url
    allowed = {"toss.im", "toss.shopping", "shopping.toss.im"}
    for _ in range(4):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.port not in (None, 443) or parsed.username:
            raise ValueError("지원하지 않는 링크 이동입니다.")
        with requests.get(url, allow_redirects=False, timeout=(3, 5), stream=True) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
                continue
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2_000_000:
                    raise ValueError("상품 페이지가 너무 큽니다.")
                chunks.append(chunk)
        soup = BeautifulSoup(b"".join(chunks), "html.parser")
        image = soup.find("meta", property="og:image")
        title = soup.find("meta", property="og:title")
        data = product.model_dump()
        if image:
            data["image_url"] = image.get("content", "")
        if product.title == "토스쇼핑 상품" and title:
            data["title"] = title.get("content", product.title)[:200]
        return Product.model_validate(data)
    raise ValueError("상품 링크 이동이 너무 많습니다.")
