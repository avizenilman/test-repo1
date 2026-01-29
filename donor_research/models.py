"""
Pydantic schemas for the Donor Research Tool.

Design Principles:
- Store raw data for audit (LinkedInProfile.raw_text captures everything)
- Track confidence and match_reason on every contribution for transparency
- Use AuditQuery to log every API call for reproducibility
- Generate name variants to handle different database formats (John vs J. vs Jonathan)
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class NameVariant(BaseModel):
    """
    A name variant for fuzzy matching across databases.

    Types:
    - "current": Full name as it appears on LinkedIn
    - "short": First + Last only (no middle name)
    - "middle_initial": First M. Last format
    - "maiden": Maiden name if known
    - "formal": Formal/legal name variant
    """
    value: str
    type: str
    confidence: float = 1.0


class Employer(BaseModel):
    """Employment record from LinkedIn."""
    name: str
    title: Optional[str] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None  # None = current position


class LinkedInProfile(BaseModel):
    """
    Raw enriched data from LinkedIn - stored in full for audit purposes.

    The raw_text field captures everything scraped, even if we couldn't
    parse it into structured fields. This ensures we never lose data.
    """
    url: str
    full_name: str
    headline: Optional[str] = None
    location: Optional[str] = None
    about: Optional[str] = None
    experience: list[Employer] = []
    education: list[str] = []
    board_affiliations: list[str] = []
    raw_text: Optional[str] = None
    fetched_at: datetime


class PersonProfile(BaseModel):
    """
    Canonical identity derived from LinkedIn.

    The canonical_id is a slug for file naming: lastname-firstname-employer
    This profile links to the full LinkedInProfile for audit purposes.
    """
    canonical_id: str
    names: list[NameVariant]
    current_employer: Optional[str] = None
    current_title: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    linkedin: LinkedInProfile
    spouse: Optional["PersonProfile"] = None


class Contribution(BaseModel):
    """
    A political contribution record from any source.

    The confidence score (0.0-1.0) reflects how certain we are this
    contribution belongs to our target person:
    - 1.0: Exact name + employer + state match
    - 0.8: Exact name + city + state match
    - 0.5: Name + state only
    - <0.5: Fuzzy matches that need human review

    match_reason explains why we matched (for transparency).
    """
    date: str
    amount: float
    recipient: str
    recipient_type: Optional[str] = None  # candidate, pac, party, committee
    source: str  # "fec", "ca_sos", "ny_boe", "sf_ethics", etc.
    source_id: Optional[str] = None  # FEC transaction ID, etc.
    confidence: float
    match_reason: str


class BoardPosition(BaseModel):
    """Board or trustee position at a nonprofit."""
    organization: str
    role: Optional[str] = None
    source: str  # "linkedin", "990"
    ein: Optional[str] = None
    years: Optional[str] = None


class FamilyFoundation(BaseModel):
    """Family foundation identified from 990 filings."""
    name: str
    ein: str
    total_assets: Optional[float] = None
    annual_giving: Optional[float] = None
    top_grantees: list[str] = []
    filing_year: Optional[int] = None


class AuditQuery(BaseModel):
    """
    Record of every API query made during research.

    This enables full reproducibility - if someone questions a result,
    we can show exactly what queries were run.
    """
    api: str
    endpoint: str
    params: dict
    timestamp: datetime
    results_count: int
    success: bool
    error: Optional[str] = None


class AuditSource(BaseModel):
    """Record of a source URL that was fetched."""
    url: str
    fetched_at: datetime
    fields_extracted: list[str]


class FullDossier(BaseModel):
    """
    Complete research dossier for a donor.

    Contains:
    - Profile with full LinkedIn data
    - All contributions (federal, state, local) with confidence scores
    - Board positions and family foundation info
    - Complete audit trail of all queries made
    """
    profile: PersonProfile
    contributions_federal: list[Contribution] = []
    contributions_state: list[Contribution] = []
    contributions_local: list[Contribution] = []
    boards: list[BoardPosition] = []
    family_foundation: Optional[FamilyFoundation] = None
    audit_queries: list[AuditQuery] = []
    audit_sources: list[AuditSource] = []
    generated_at: datetime
