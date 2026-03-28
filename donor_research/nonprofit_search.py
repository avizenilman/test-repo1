"""
Nonprofit and foundation search via ProPublica + Open990.

Searches for:
1. Board positions (from LinkedIn profile + 990 officer search)
2. Family foundations (lastname Family Foundation, lastname Foundation, etc.)
3. 990 filing details (assets, giving, grantees)

Data sources:
- ProPublica API: https://projects.propublica.org/nonprofits/api
- Open990 API: https://www.open990.org/api/ (has officer name search!)

The key insight: Open990 indexes 990 officers/trustees by name, so we can
search "Alison Pincus" and find every nonprofit where she's listed.
"""

import re
import time
import requests
from datetime import datetime
from typing import Optional

from models import (
    PersonProfile,
    BoardPosition,
    FamilyFoundation,
    AuditQuery,
)


PROPUBLICA_BASE = "https://projects.propublica.org/nonprofits/api/v2"
OPEN990_BASE = "https://www.open990.org/api"

# Common family foundation naming patterns
FOUNDATION_PATTERNS = [
    "{last} Family Foundation",
    "{last} Foundation",
    "{last} Charitable Foundation",
    "{last} Charitable Trust",
    "{last} Family Fund",
    "{full} Foundation",
    "{full} Family Foundation",
]


def search_nonprofits(
    profile: PersonProfile,
) -> tuple[list[BoardPosition], Optional[FamilyFoundation], list[AuditQuery]]:
    """
    Search ProPublica Nonprofit Explorer for board positions and family foundations.

    Args:
        profile: PersonProfile with names and LinkedIn data

    Returns:
        Tuple of (board_positions, family_foundation, audit_queries)
    """
    boards = []
    foundation = None
    audit = []

    # Step 1: Add board positions from LinkedIn (already extracted)
    linkedin_boards = _extract_linkedin_boards(profile)
    boards.extend(linkedin_boards)

    # Step 2: Search Open990 for officer/trustee positions by name
    # This is the key reverse lookup - find all 990s where this person is listed
    open990_boards, open990_audit = _search_open990_officers(profile)
    boards.extend(open990_boards)
    audit.extend(open990_audit)

    # Step 3: Search for family foundation
    foundation, foundation_audit = _search_family_foundation(profile)
    audit.extend(foundation_audit)

    # Step 4: Look up EINs for LinkedIn board positions
    for board in linkedin_boards:
        if not board.ein:
            ein, ein_audit = _lookup_organization_ein(board.organization)
            audit.extend(ein_audit)
            if ein:
                board.ein = ein

    # Step 5: Search spouse if present
    if profile.spouse:
        spouse_boards, spouse_foundation, spouse_audit = search_nonprofits(
            profile.spouse
        )
        boards.extend(spouse_boards)
        audit.extend(spouse_audit)

        # Use spouse foundation if we didn't find one for primary
        if not foundation and spouse_foundation:
            foundation = spouse_foundation

    return boards, foundation, audit


def _extract_linkedin_boards(profile: PersonProfile) -> list[BoardPosition]:
    """
    Extract board positions from LinkedIn profile data.

    LinkedIn board affiliations are stored in profile.linkedin.board_affiliations.
    """
    boards = []

    for affiliation in profile.linkedin.board_affiliations:
        # Parse role if included (e.g., "Board Member, Acme Foundation")
        role = None
        org = affiliation

        # Common patterns: "Role, Organization" or "Organization - Role"
        if "," in affiliation:
            parts = affiliation.split(",", 1)
            if any(
                keyword in parts[0].lower()
                for keyword in ["board", "trustee", "director", "advisor"]
            ):
                role = parts[0].strip()
                org = parts[1].strip()
            else:
                org = parts[0].strip()
                role = parts[1].strip() if len(parts) > 1 else None
        elif " - " in affiliation:
            parts = affiliation.split(" - ", 1)
            org = parts[0].strip()
            role = parts[1].strip() if len(parts) > 1 else None

        boards.append(
            BoardPosition(
                organization=org,
                role=role,
                source="linkedin",
                ein=None,
                years=None,
            )
        )

    # Also extract from experience if title suggests board role
    for exp in profile.linkedin.experience:
        if exp.title and any(
            keyword in exp.title.lower()
            for keyword in ["board", "trustee", "director"]
        ):
            # Check if this looks like a nonprofit
            if any(
                indicator in exp.name.lower()
                for indicator in [
                    "foundation",
                    "fund",
                    "trust",
                    "institute",
                    "council",
                    "society",
                    "association",
                ]
            ):
                years = None
                if exp.start_year:
                    end = exp.end_year or "Present"
                    years = f"{exp.start_year}-{end}"

                boards.append(
                    BoardPosition(
                        organization=exp.name,
                        role=exp.title,
                        source="linkedin",
                        ein=None,
                        years=years,
                    )
                )

    return boards


def _search_open990_officers(
    profile: PersonProfile,
) -> tuple[list[BoardPosition], list[AuditQuery]]:
    """
    Search Open990 for organizations where this person is listed as officer/trustee.

    This is the reverse lookup approach - instead of searching by foundation name,
    we search by person name and find all their 990 affiliations.

    Open990 API: https://www.open990.org/api/
    """
    boards = []
    audit = []
    seen_eins: set[str] = set()

    for name_variant in profile.names:
        # Skip low confidence variants
        if name_variant.confidence < 0.7:
            continue

        name = name_variant.value

        try:
            # Open990 officer search endpoint
            response = requests.get(
                f"{OPEN990_BASE}/officers/",
                params={
                    "name": name,
                    "limit": 50,
                },
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                results = data if isinstance(data, list) else data.get("results", [])

                audit.append(
                    AuditQuery(
                        api="open990",
                        endpoint="/officers/",
                        params={"name": name},
                        timestamp=datetime.now(),
                        results_count=len(results),
                        success=True,
                        error=None,
                    )
                )

                for result in results:
                    ein = str(result.get("ein", ""))
                    if ein in seen_eins:
                        continue
                    seen_eins.add(ein)

                    # Extract organization and role info
                    org_name = result.get("organization_name", result.get("name", "Unknown"))
                    role = result.get("title", result.get("role", "Officer/Trustee"))
                    year = result.get("tax_year", result.get("year"))

                    boards.append(
                        BoardPosition(
                            organization=org_name,
                            role=role,
                            source="990",
                            ein=ein if ein else None,
                            years=str(year) if year else None,
                        )
                    )

            else:
                audit.append(
                    AuditQuery(
                        api="open990",
                        endpoint="/officers/",
                        params={"name": name},
                        timestamp=datetime.now(),
                        results_count=0,
                        success=False,
                        error=f"HTTP {response.status_code}",
                    )
                )

        except requests.exceptions.RequestException as e:
            audit.append(
                AuditQuery(
                    api="open990",
                    endpoint="/officers/",
                    params={"name": name},
                    timestamp=datetime.now(),
                    results_count=0,
                    success=False,
                    error=str(e),
                )
            )

        # Small delay between requests
        time.sleep(0.3)

    return boards, audit


def _search_family_foundation(
    profile: PersonProfile,
) -> tuple[Optional[FamilyFoundation], list[AuditQuery]]:
    """
    Search for family foundation using name patterns.

    Common patterns:
    - {LastName} Family Foundation
    - {LastName} Foundation
    - {FullName} Foundation
    """
    audit = []

    # Extract last name and full name
    full_name = profile.names[0].value
    name_parts = full_name.split()
    last_name = name_parts[-1] if name_parts else full_name

    # Generate search terms from patterns
    search_terms = []
    for pattern in FOUNDATION_PATTERNS:
        term = pattern.format(last=last_name, full=full_name)
        search_terms.append(term)

    # Deduplicate while preserving order
    seen = set()
    unique_terms = []
    for term in search_terms:
        term_lower = term.lower()
        if term_lower not in seen:
            seen.add(term_lower)
            unique_terms.append(term)

    # Search ProPublica for each term
    for search_term in unique_terms:
        foundation, search_audit = _search_propublica(search_term, profile)
        audit.extend(search_audit)

        if foundation:
            return foundation, audit

        # Small delay between requests
        time.sleep(0.3)

    return None, audit


def _search_propublica(
    search_term: str, profile: PersonProfile
) -> tuple[Optional[FamilyFoundation], list[AuditQuery]]:
    """
    Search ProPublica Nonprofit Explorer API.

    API endpoint: /search.json?q={query}
    """
    audit = []
    params = {"q": search_term}

    try:
        response = requests.get(
            f"{PROPUBLICA_BASE}/search.json",
            params=params,
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            organizations = data.get("organizations", [])

            audit.append(
                AuditQuery(
                    api="propublica_nonprofits",
                    endpoint="/search.json",
                    params=params,
                    timestamp=datetime.now(),
                    results_count=len(organizations),
                    success=True,
                    error=None,
                )
            )

            # Look for matching foundation
            for org in organizations:
                if _is_likely_family_foundation(profile, org):
                    # Get detailed 990 data
                    ein = org.get("ein")
                    details = _get_990_details(ein)

                    return (
                        FamilyFoundation(
                            name=org.get("name", "Unknown"),
                            ein=str(ein),
                            total_assets=details.get("totassetsend"),
                            annual_giving=details.get("totfuncexpns"),
                            top_grantees=details.get("grantees", []),
                            filing_year=details.get("tax_prd_yr"),
                        ),
                        audit,
                    )
        else:
            audit.append(
                AuditQuery(
                    api="propublica_nonprofits",
                    endpoint="/search.json",
                    params=params,
                    timestamp=datetime.now(),
                    results_count=0,
                    success=False,
                    error=f"HTTP {response.status_code}",
                )
            )

    except requests.exceptions.RequestException as e:
        audit.append(
            AuditQuery(
                api="propublica_nonprofits",
                endpoint="/search.json",
                params=params,
                timestamp=datetime.now(),
                results_count=0,
                success=False,
                error=str(e),
            )
        )

    return None, audit


def _is_likely_family_foundation(profile: PersonProfile, org: dict) -> bool:
    """
    Check if organization is likely the person's family foundation.

    Criteria:
    - Organization name contains person's last name
    - Organization is a foundation/fund type
    - Location matches (if available)
    """
    full_name = profile.names[0].value
    name_parts = full_name.split()
    last_name = name_parts[-1].lower() if name_parts else ""

    org_name = org.get("name", "").lower()

    # Must contain last name
    if last_name not in org_name:
        return False

    # Should be foundation-like
    foundation_keywords = [
        "foundation",
        "fund",
        "trust",
        "charitable",
        "family",
    ]
    if not any(keyword in org_name for keyword in foundation_keywords):
        return False

    # Location match is a strong signal (but not required)
    org_state = org.get("state", "").upper()
    if profile.state and org_state:
        if profile.state == org_state:
            return True

    # Check city if available
    org_city = org.get("city", "").lower()
    if profile.city and org_city:
        if profile.city.lower() in org_city or org_city in profile.city.lower():
            return True

    # If no location match but name is very specific, still accept
    # E.g., "John Smith Family Foundation" is likely even without location
    first_name = name_parts[0].lower() if name_parts else ""
    if first_name and first_name in org_name:
        return True

    return True  # Accept if last name matches and is foundation-type


def _get_990_details(ein: int) -> dict:
    """
    Get detailed 990 filing data for an organization.

    Returns most recent filing with key financial data.
    """
    try:
        response = requests.get(
            f"{PROPUBLICA_BASE}/organizations/{ein}.json",
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            org_data = data.get("organization", {})
            filings = data.get("filings_with_data", [])

            if filings:
                # Return most recent filing
                latest = filings[0]
                return {
                    "totassetsend": latest.get("totassetsend"),
                    "totfuncexpns": latest.get("totfuncexpns"),
                    "tax_prd_yr": latest.get("tax_prd_yr"),
                    "grantees": [],  # Would need to parse 990-PF for grantees
                }

    except requests.exceptions.RequestException:
        pass

    return {}


def _lookup_organization_ein(org_name: str) -> tuple[Optional[str], list[AuditQuery]]:
    """
    Look up EIN for an organization by name.

    Used to enrich LinkedIn board positions with EIN data.
    """
    audit = []
    params = {"q": org_name}

    try:
        response = requests.get(
            f"{PROPUBLICA_BASE}/search.json",
            params=params,
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            organizations = data.get("organizations", [])

            audit.append(
                AuditQuery(
                    api="propublica_nonprofits",
                    endpoint="/search.json",
                    params=params,
                    timestamp=datetime.now(),
                    results_count=len(organizations),
                    success=True,
                    error=None,
                )
            )

            # Find best match
            org_lower = org_name.lower()
            for org in organizations:
                name = org.get("name", "").lower()
                # Exact match or close match
                if org_lower in name or name in org_lower:
                    return str(org.get("ein")), audit

        else:
            audit.append(
                AuditQuery(
                    api="propublica_nonprofits",
                    endpoint="/search.json",
                    params=params,
                    timestamp=datetime.now(),
                    results_count=0,
                    success=False,
                    error=f"HTTP {response.status_code}",
                )
            )

    except requests.exceptions.RequestException as e:
        audit.append(
            AuditQuery(
                api="propublica_nonprofits",
                endpoint="/search.json",
                params=params,
                timestamp=datetime.now(),
                results_count=0,
                success=False,
                error=str(e),
            )
        )

    return None, audit
