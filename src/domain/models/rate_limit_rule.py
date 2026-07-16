import re
from pydantic import BaseModel, Field, field_validator


class RateLimitRule(BaseModel):
    domain_pattern: str = Field(..., min_length=1)
    requests_per_hour: int = Field(..., ge=1, le=10000)
    enabled: bool = Field(default=True)

    @field_validator("domain_pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        if "*" in v or "?" in v:
            return v
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"Invalid pattern: {e}")
        return v

    def matches_domain(self, domain: str) -> bool:
        if not self.enabled:
            return False

        pattern = self.domain_pattern

        if "*" in pattern or "?" in pattern:
            regex_pattern = (
                "^" + re.escape(pattern).replace(r"\?", ".").replace(r"\*", ".*") + "$"
            )
            try:
                return bool(re.match(regex_pattern, domain))
            except re.error:
                return False

        try:
            return bool(re.fullmatch(pattern, domain))
        except re.error:
            return False
