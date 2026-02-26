from __future__ import annotations

"""
iThenticate connector stub.

Why stub?
- iThenticate API requires a paid account / credentials.
- This module defines a minimal interface so you can plug it in later.

Docs (public):
- iThenticate API overview (may require account access).
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any

from auto_paper.config import settings


class IThenticateError(RuntimeError):
    pass


@dataclass
class SimilarityReport:
    similarity_percent: float
    report_url: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class IThenticateClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.enabled = settings.ithenticate_enabled
        self.api_key = api_key or settings.ithenticate_api_key
        self.base_url = base_url or settings.ithenticate_base_url
        if self.enabled and (not self.api_key or not self.base_url):
            raise IThenticateError("ITHENTICATE is enabled but api_key/base_url is missing.")

    def submit_document(self, title: str, text: str) -> str:
        """
        Submit a document and return a job_id.
        Implement this for your iThenticate plan.
        """
        raise NotImplementedError("Connect this to your iThenticate account/API.")

    def fetch_report(self, job_id: str) -> SimilarityReport:
        """
        Fetch a similarity report.
        """
        raise NotImplementedError("Connect this to your iThenticate account/API.")
