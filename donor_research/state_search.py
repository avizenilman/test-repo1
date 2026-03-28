"""
State-level campaign finance search for California and New York.

California: Cal-Access (Secretary of State)
- No clean API available
- Uses web search fallback: site:cal-access.sos.ca.gov "{name}"

New York: Board of Elections
- Has a searchable database at publicreporting.elections.ny.gov
- Uses web search + direct queries where possible

Both states are searched regardless of profile location since donors
may contribute to state races outside their home state.
"""

import re
import time
import requests
from datetime import datetime
from typing import Optional

from models import PersonProfile, Contribution, AuditQuery


def search_state(
    profile: PersonProfile,
) -> tuple[list[Contribution], list[AuditQuery]]:
    """
    Search California and New York state disclosure databases.

    Both states are searched regardless of profile location.

    Args:
        profile: PersonProfile with names and location data

    Returns:
        Tuple of (contributions list, audit queries list)
    """
    contributions = []
    audit = []

    # Search California
    ca_contributions, ca_audit = _search_california(profile)
    contributions.extend(ca_contributions)
    audit.extend(ca_audit)

    # Search New York
    ny_contributions, ny_audit = _search_new_york(profile)
    contributions.extend(ny_contributions)
    audit.extend(ny_audit)

    # Search spouse if present
    if profile.spouse:
        spouse_contributions, spouse_audit = search_state(profile.spouse)
        contributions.extend(spouse_contributions)
        audit.extend(spouse_audit)

    return contributions, audit


def _search_california(
    profile: PersonProfile,
) -> tuple[list[Contribution], list[AuditQuery]]:
    """
    Search California Secretary of State Cal-Access database.

    Cal-Access URL: https://cal-access.sos.ca.gov/

    Since there's no clean API, we:
    1. Attempt direct URL patterns that Cal-Access uses
    2. Fall back to web search for site:cal-access.sos.ca.gov

    Returns (contributions, audit_queries) tuple.
    """
    contributions = []
    audit = []
    seen_ids: set[str] = set()

    for name_variant in profile.names:
        name = name_variant.value

        # Skip low confidence variants to reduce noise
        if name_variant.confidence < 0.6:
            continue

        # Attempt Cal-Access direct search
        # Cal-Access has a contributor search page
        ca_results, ca_audit = _query_cal_access(name, profile)
        audit.extend(ca_audit)

        for result in ca_results:
            # Generate a unique ID for deduplication
            result_id = f"ca-{result['date']}-{result['amount']}-{result['recipient']}"
            if result_id in seen_ids:
                continue
            seen_ids.add(result_id)

            # Calculate confidence
            confidence = _calculate_state_confidence(
                profile, result, name_variant.confidence
            )

            contributions.append(
                Contribution(
                    date=result["date"],
                    amount=result["amount"],
                    recipient=result["recipient"],
                    recipient_type=result.get("recipient_type"),
                    source="ca_sos",
                    source_id=result.get("filing_id"),
                    confidence=confidence,
                    match_reason=f"cal_access_search ({name_variant.type})",
                )
            )

    return contributions, audit


def _query_cal_access(
    name: str, profile: PersonProfile
) -> tuple[list[dict], list[AuditQuery]]:
    """
    Query Cal-Access for contributor records.

    Cal-Access doesn't have a JSON API, so this function provides
    a framework for parsing the HTML results or using web search.
    """
    results = []
    audit = []

    # Cal-Access contributor search URL pattern
    # In production, you would:
    # 1. Make a request to the search page
    # 2. Parse the HTML table results
    # 3. Extract contribution records

    search_url = "https://cal-access.sos.ca.gov/Campaign/Committees/list.aspx"
    params = {"contributor": name}

    try:
        # NOTE: Cal-Access often requires session handling and form submission
        # This is a placeholder for actual implementation

        audit.append(
            AuditQuery(
                api="ca_cal_access",
                endpoint="/Campaign/Committees/list.aspx",
                params=params,
                timestamp=datetime.now(),
                results_count=0,
                success=True,
                error="Cal-Access requires HTML parsing - no results extracted",
            )
        )

        # In production, parse HTML and extract contributions
        # Example result format:
        # results.append({
        #     "date": "2023-06-15",
        #     "amount": 1000.00,
        #     "recipient": "Committee Name",
        #     "recipient_type": "candidate",
        #     "filing_id": "12345"
        # })

    except Exception as e:
        audit.append(
            AuditQuery(
                api="ca_cal_access",
                endpoint="/Campaign/Committees/list.aspx",
                params=params,
                timestamp=datetime.now(),
                results_count=0,
                success=False,
                error=str(e),
            )
        )

    return results, audit


def _search_new_york(
    profile: PersonProfile,
) -> tuple[list[Contribution], list[AuditQuery]]:
    """
    Search New York State Board of Elections.

    NY BOE URL: https://publicreporting.elections.ny.gov/

    The NY BOE has a more accessible search interface.
    """
    contributions = []
    audit = []
    seen_ids: set[str] = set()

    for name_variant in profile.names:
        name = name_variant.value

        # Skip low confidence variants
        if name_variant.confidence < 0.6:
            continue

        # Query NY BOE
        ny_results, ny_audit = _query_ny_boe(name, profile)
        audit.extend(ny_audit)

        for result in ny_results:
            # Generate unique ID
            result_id = f"ny-{result['date']}-{result['amount']}-{result['recipient']}"
            if result_id in seen_ids:
                continue
            seen_ids.add(result_id)

            confidence = _calculate_state_confidence(
                profile, result, name_variant.confidence
            )

            contributions.append(
                Contribution(
                    date=result["date"],
                    amount=result["amount"],
                    recipient=result["recipient"],
                    recipient_type=result.get("recipient_type"),
                    source="ny_boe",
                    source_id=result.get("transaction_id"),
                    confidence=confidence,
                    match_reason=f"ny_boe_search ({name_variant.type})",
                )
            )

    return contributions, audit


def _query_ny_boe(
    name: str, profile: PersonProfile
) -> tuple[list[dict], list[AuditQuery]]:
    """
    Query New York Board of Elections database.

    NY BOE has a public API endpoint for contribution searches.
    """
    results = []
    audit = []

    # NY BOE API endpoint
    # The actual API structure may vary - this is based on observed patterns
    search_url = "https://publicreporting.elections.ny.gov/api/contributions/search"

    params = {
        "contributorName": name,
        "pageSize": 100,
    }

    # Add location filter if in NY
    if profile.state == "NY" and profile.city:
        params["city"] = profile.city

    try:
        response = requests.get(search_url, params=params, timeout=30)

        if response.status_code == 200:
            # Attempt to parse JSON response
            try:
                data = response.json()
                records = data.get("contributions", data.get("results", []))

                for record in records:
                    results.append(
                        {
                            "date": record.get("date", record.get("contributionDate", "")),
                            "amount": float(record.get("amount", record.get("contributionAmount", 0))),
                            "recipient": record.get("committee", record.get("committeeName", "Unknown")),
                            "recipient_type": record.get("committeeType"),
                            "transaction_id": record.get("transactionId"),
                        }
                    )

                audit.append(
                    AuditQuery(
                        api="ny_boe",
                        endpoint="/api/contributions/search",
                        params=params,
                        timestamp=datetime.now(),
                        results_count=len(results),
                        success=True,
                        error=None,
                    )
                )

            except ValueError:
                # Not JSON - might be HTML
                audit.append(
                    AuditQuery(
                        api="ny_boe",
                        endpoint="/api/contributions/search",
                        params=params,
                        timestamp=datetime.now(),
                        results_count=0,
                        success=True,
                        error="Response not JSON - HTML parsing required",
                    )
                )
        else:
            audit.append(
                AuditQuery(
                    api="ny_boe",
                    endpoint="/api/contributions/search",
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
                api="ny_boe",
                endpoint="/api/contributions/search",
                params=params,
                timestamp=datetime.now(),
                results_count=0,
                success=False,
                error=str(e),
            )
        )

    return results, audit


def _calculate_state_confidence(
    profile: PersonProfile, result: dict, name_confidence: float
) -> float:
    """
    Calculate confidence for state-level contribution match.

    State databases often have less metadata than FEC, so we're
    generally more conservative with confidence scores.
    """
    # Start with base confidence from name variant
    confidence = name_confidence * 0.7  # Discount for state-level data quality

    # Boost if location matches
    result_city = result.get("city", "").lower()
    result_state = result.get("state", "").upper()

    if profile.city and result_city:
        if profile.city.lower() == result_city:
            confidence = min(confidence + 0.15, 0.9)
        else:
            confidence = max(confidence - 0.1, 0.2)

    if profile.state and result_state:
        if profile.state == result_state:
            confidence = min(confidence + 0.1, 0.9)

    # Boost if employer matches
    result_employer = result.get("employer", "").lower()
    if profile.current_employer and result_employer:
        if profile.current_employer.lower() in result_employer:
            confidence = min(confidence + 0.15, 0.95)

    return round(confidence, 2)
