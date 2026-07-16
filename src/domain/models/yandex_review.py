"""Domain model for a Yandex Maps review.

Mirrors the structure returned by Yandex's internal `/maps/api/business/fetchReviews`
endpoint (see `yandex_maps_experiment/results/06_fetch_reviews_reviews.json`).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class YandexReviewAuthor(BaseModel):
    public_id: Optional[str] = Field(None, alias="publicId")
    name: Optional[str] = None
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    profession_level: Optional[str] = Field(None, alias="professionLevel")
    rtb: Optional[str] = None
    rtb_type: Optional[str] = Field(None, alias="rtbType")
    is_subscribed: bool = Field(False, alias="isSubscribed")
    achievements: list[Any] = Field(default_factory=list)
    professions: list[Any] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class YandexBusinessComment(BaseModel):
    text: Optional[str] = None
    updated_time: Optional[str] = Field(None, alias="updatedTime")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class YandexReviewReactions(BaseModel):
    likes: int = 0
    dislikes: int = 0
    user_reaction: Optional[str] = Field("NONE", alias="userReaction")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class YandexReviewPhoto(BaseModel):
    id: Optional[str] = None
    business_id: Optional[str] = Field(None, alias="businessId")
    url_template: Optional[str] = Field(None, alias="urlTemplate")
    type: Optional[str] = None
    created_time: Optional[int] = Field(None, alias="createdTime")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class YandexReview(BaseModel):
    """A single review."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    review_id: str = Field(..., alias="reviewId")
    business_id: Optional[str] = Field(None, alias="businessId")
    author: Optional[YandexReviewAuthor] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    text: Optional[str] = None
    text_language: Optional[str] = Field(None, alias="textLanguage")
    text_translations: dict[str, str] = Field(default_factory=dict, alias="textTranslations")
    updated_time: Optional[str] = Field(None, alias="updatedTime")
    business_comment: Optional[YandexBusinessComment] = Field(None, alias="businessComment")
    reactions: Optional[YandexReviewReactions] = None
    photos: list[YandexReviewPhoto] = Field(default_factory=list)
    videos: list[dict] = Field(default_factory=list)

    raw: Optional[dict[str, Any]] = Field(
        default=None, description="Full upstream JSON"
    )

    @classmethod
    def from_yandex_item(cls, item: dict[str, Any], *, keep_raw: bool = True) -> "YandexReview":
        """Map a raw element from `fetchReviews` response to this model."""
        if not isinstance(item, dict):
            raise ValueError(f"expected dict, got {type(item)!r}")

        review_id = item.get("reviewId") or item.get("id") or item.get("publicId")
        if not review_id:
            raise ValueError("yandex review is missing reviewId/id/publicId")

        author_raw = item.get("author")
        author = (
            YandexReviewAuthor.model_validate(author_raw)
            if isinstance(author_raw, dict)
            else None
        )

        bc_raw = item.get("businessComment")
        business_comment = (
            YandexBusinessComment.model_validate(bc_raw)
            if isinstance(bc_raw, dict)
            else None
        )

        reactions_raw = item.get("reactions")
        reactions = (
            YandexReviewReactions.model_validate(reactions_raw)
            if isinstance(reactions_raw, dict)
            else None
        )

        photos_raw = item.get("photos") or []
        photos = [
            YandexReviewPhoto.model_validate(p) for p in photos_raw if isinstance(p, dict)
        ]

        translations_raw = item.get("textTranslations") or {}
        translations = {
            str(k): str(v)
            for k, v in (translations_raw.items() if isinstance(translations_raw, dict) else [])
        }

        return cls(
            review_id=str(review_id),
            business_id=str(item["businessId"]) if item.get("businessId") else None,
            author=author,
            rating=int(item["rating"]) if isinstance(item.get("rating"), (int, float)) else None,
            text=item.get("text"),
            text_language=item.get("textLanguage"),
            text_translations=translations,
            updated_time=item.get("updatedTime"),
            business_comment=business_comment,
            reactions=reactions,
            photos=photos,
            videos=item.get("videos") or [],
            raw=item if keep_raw else None,
        )
