"""Request schemas shared by the company search."""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, model_validator


class CompanySource(BaseModel):
    company_id: str | None = Field(None, min_length=1, max_length=200, pattern=r"^\S(?:.*\S)?$")
    company_name: str | None = Field(None, min_length=1, max_length=300)


class LinkedInSource(CompanySource):
    company_url: str = Field(max_length=2000)  # Public company or showcase page
    provider: Literal["apify"] = "apify"
    results_limit: int = Field(20, ge=1, le=100)
    label: str | None = None

    @model_validator(mode="after")
    def validate_source(self):
        parsed = urlsplit(self.company_url)
        host = parsed.hostname or ''
        parts = parsed.path.strip('/').split('/')
        if (parsed.scheme not in {'http', 'https'} or not (host == 'linkedin.com' or host.endswith('.linkedin.com'))
                or parsed.username or parsed.password or parsed.port not in {None, 80, 443}
                or len(parts) not in {2, 3} or parts[0] not in {'company', 'showcase'}
                or not parts[1] or (len(parts) == 3 and parts[2] != 'posts')
                or any(value in parts[1].lower() for value in ('%2f', '%5c', '\\'))):
            raise ValueError('company_url must be a public LinkedIn company or showcase URL, e.g. https://www.linkedin.com/company/example/')
        self.company_url = urlunsplit(('https', 'www.linkedin.com', '/' + '/'.join(parts[:2]) + '/', '', ''))
        return self

    @property
    def url(self):
        return self.company_url

    @property
    def platform(self):
        return 'linkedin'
