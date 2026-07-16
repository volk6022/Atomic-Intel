"""Models for the supply-side catalog scrapers (kwork gigs, fl.ru freelancers)."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# kwork gig catalog
# --------------------------------------------------------------------------- #
class Gig(BaseModel):
    """One kwork gig (услуга) list row. Mirrors kwork_services_scrape.LIST_FIELDS."""

    id: Optional[int] = None
    url: Optional[str] = None
    gtitle: Optional[str] = None
    price: Optional[int] = None
    days: Optional[int] = None
    queueCount: Optional[int] = None
    userId: Optional[int] = None
    userName: Optional[str] = None
    convertedUserRating: Optional[Any] = None
    userRating: Optional[Any] = None
    userRatingCount: Optional[Any] = None
    sellerLevel: Optional[Any] = None
    rating: Optional[Any] = None
    topBadge: Optional[Any] = None
    baseVolume: Optional[Any] = None
    baseVolumeShortName: Optional[str] = None
    parent: Optional[str] = None
    leaf: Optional[str] = None


class KworkServicesRequest(BaseModel):
    parent: str = Field(..., description="category parent slug, e.g. script-programming")
    leaf: str = Field("", description="leaf slug (empty = parent-level catalog)")
    max_pages: int = Field(8, ge=1, le=40)
    cards: int = Field(0, ge=0, le=50, description="how many gig cards to enrich (0 = none)")


class KworkServicesResponse(BaseModel):
    parent: str
    leaf: str
    total: int
    gigs: list[Gig]
    cards: list[dict[str, Any]] = Field(default_factory=list)


class KworkProfilesRequest(BaseModel):
    usernames: list[str] = Field(..., min_length=1)
    with_gigs: bool = True


class KworkProfilesResponse(BaseModel):
    total: int
    profiles: list[dict[str, Any]]


# --------------------------------------------------------------------------- #
# fl.ru freelancer catalog
# --------------------------------------------------------------------------- #
class FreelancerProfile(BaseModel):
    """One fl.ru freelancer catalog row. Mirrors fl_freelancers_scrape.parse_rows."""

    uid: Optional[str] = None
    login: Optional[str] = None
    name: Optional[str] = None
    anonymized: bool = False
    spec_group: Optional[str] = None
    spec_slug: Optional[str] = None
    spec_text: Optional[str] = None
    experience_years: Optional[int] = None
    portfolio_works: Optional[int] = None
    reviews: Optional[int] = None
    deals: Optional[int] = None
    is_pro: bool = False
    is_verified: bool = False
    profession: Optional[str] = None


class FLFreelancersRequest(BaseModel):
    profession: str = Field(..., description="fl.ru profession slug, e.g. neironnye-seti")
    max_pages: int = Field(5, ge=1, le=30)
    profiles: int = Field(0, ge=0, le=50, description="profiles to sample for rate (0 = none)")


class FLFreelancersResponse(BaseModel):
    profession: str
    total: int
    freelancers: list[FreelancerProfile]
    rates: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
