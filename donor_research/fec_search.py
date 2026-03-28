"""
FEC (Federal Election Commission) contribution search.

Searches Schedule A (individual contributions) for all election cycles
from 2008 to present. Uses query variants with decreasing confidence:

1. Name + Employer + State (confidence: 1.0)
2. Name + City + State (confidence: 0.8)
3. Name + State only (confidence: 0.5)

Each result includes a confidence score and match_reason for transparency.
"""

import time
import requests
from datetime import datetime
from typing import Optional

from models import PersonProfile, Contribution, AuditQuery


FEC_BASE = "https://api.open.fec.gov/v1"

# Election cycles to search (2008 to present)
ELECTION_CYCLES = [2008, 2010, 2012, 2014, 2016, 2018, 2020, 2022, 2024]

# Rate limiting settings
MAX_RETRIES = 4
INITIAL_BACKOFF = 2  # seconds


def search_fec(
    profile: PersonProfile, api_key: str
) -> tuple[list[Contribution], list[AuditQuery]]:
    """
    Search FEC for federal contributions from 2008 cycle to present.

    Args:
        profile: PersonProfile with names, employer, location
        api_key: FEC API key

    Returns:
        Tuple of (contributions list, audit queries list)
    """
    contributions = []
    audit = []
    seen_ids: set[str] = set()  # For deduplication

    # Build query variants in priority order
    queries = _build_query_variants(profile)

    for query_params, confidence_base, match_reason in queries:
        # Search each election cycle
        cycle_contributions, cycle_audit = _search_all_cycles(
            query_params=query_params,
            api_key=api_key,
            profile=profile,
            confidence_base=confidence_base,
            match_reason=match_reason,
            seen_ids=seen_ids,
        )
        contributions.extend(cycle_contributions)
        audit.extend(cycle_audit)

    # Also search for spouse if present
    if profile.spouse:
        spouse_contributions, spouse_audit = search_fec(profile.spouse, api_key)
        contributions.extend(spouse_contributions)
        audit.extend(spouse_audit)

    return contributions, audit


def _build_query_variants(
    profile: PersonProfile,
) -> list[tuple[dict, float, str]]:
    """
    Build query variants in priority order with base confidence scores.

    Returns list of (params_dict, base_confidence, match_reason) tuples.
    Queries are ordered from most specific (highest confidence) to least.
    """
    queries = []

    for name_variant in profile.names:
        name = name_variant.value
        name_confidence = name_variant.confidence

        # Skip very low confidence name variants to avoid noise
        if name_confidence < 0.5:
            continue

        # Highest confidence: name + employer + state
        if profile.current_employer and profile.state:
            queries.append(
                (
                    {
                        "contributor_name": name,
                        "contributor_employer": profile.current_employer,
                        "contributor_state": profile.state,
                    },
                    min(1.0, name_confidence),
                    f"exact_name_employer_state ({name_variant.type})",
                )
            )

        # High confidence: name + city + state
        if profile.city and profile.state:
            queries.append(
                (
                    {
                        "contributor_name": name,
                        "contributor_city": profile.city,
                        "contributor_state": profile.state,
                    },
                    min(0.85, name_confidence * 0.85),
                    f"exact_name_city_state ({name_variant.type})",
                )
            )

        # Medium confidence: name + state only
        if profile.state:
            # Lower confidence for non-current name variants
            state_confidence = 0.5 if name_variant.type == "current" else 0.4
            queries.append(
                (
                    {
                        "contributor_name": name,
                        "contributor_state": profile.state,
                    },
                    min(state_confidence, name_confidence * state_confidence),
                    f"name_state_only ({name_variant.type})",
                )
            )

    return queries


def _search_all_cycles(
    query_params: dict,
    api_key: str,
    profile: PersonProfile,
    confidence_base: float,
    match_reason: str,
    seen_ids: set[str],
) -> tuple[list[Contribution], list[AuditQuery]]:
    """Search all election cycles for a given query."""
    contributions = []
    audit = []

    for cycle in ELECTION_CYCLES:
        cycle_params = query_params.copy()
        cycle_params["two_year_transaction_period"] = cycle

        cycle_contributions, cycle_audit = _search_cycle(
            query_params=cycle_params,
            api_key=api_key,
            profile=profile,
            confidence_base=confidence_base,
            match_reason=match_reason,
            seen_ids=seen_ids,
        )
        contributions.extend(cycle_contributions)
        audit.extend(cycle_audit)

    return contributions, audit


def _search_cycle(
    query_params: dict,
    api_key: str,
    profile: PersonProfile,
    confidence_base: float,
    match_reason: str,
    seen_ids: set[str],
) -> tuple[list[Contribution], list[AuditQuery]]:
    """Search a single election cycle with pagination."""
    contributions = []
    audit = []

    # Set up pagination
    params = query_params.copy()
    params["api_key"] = api_key
    params["per_page"] = 100
    params["sort"] = "-contribution_receipt_date"

    page = 1
    last_indexes = None

    while True:
        if last_indexes:
            params["last_index"] = last_indexes
            params["last_contribution_receipt_date"] = params.get(
                "last_contribution_receipt_date"
            )

        # Make request with retry logic
        response_data, query_audit = _make_request(
            endpoint="/schedules/schedule_a/",
            params=params,
        )
        audit.append(query_audit)

        if not query_audit.success or not response_data:
            break

        results = response_data.get("results", [])
        if not results:
            break

        # Process results
        for result in results:
            tx_id = result.get("transaction_id") or result.get("sub_id")
            if not tx_id or tx_id in seen_ids:
                continue
            seen_ids.add(tx_id)

            # Calculate confidence based on field alignment
            confidence = _calculate_confidence(profile, result, confidence_base)

            # Extract recipient info
            committee = result.get("committee") or {}
            recipient_name = committee.get("name") or result.get(
                "committee_name", "Unknown"
            )
            recipient_type = committee.get("committee_type_full") or result.get(
                "committee_type_full"
            )

            contributions.append(
                Contribution(
                    date=result.get("contribution_receipt_date", ""),
                    amount=float(result.get("contribution_receipt_amount", 0)),
                    recipient=recipient_name,
                    recipient_type=recipient_type,
                    source="fec",
                    source_id=str(tx_id),
                    confidence=confidence,
                    match_reason=match_reason,
                )
            )

        # Check for more pages
        pagination = response_data.get("pagination", {})
        if page >= pagination.get("pages", 1):
            break

        last_indexes = pagination.get("last_indexes", {}).get("last_index")
        if not last_indexes:
            break

        page += 1

        # Small delay between pages to be respectful of API
        time.sleep(0.2)

    return contributions, audit


def _make_request(
    endpoint: str,
    params: dict,
) -> tuple[Optional[dict], AuditQuery]:
    """
    Make FEC API request with exponential backoff retry.

    Returns (response_data, audit_query) tuple.
    """
    url = f"{FEC_BASE}{endpoint}"
    # Don't log the API key
    log_params = {k: v for k, v in params.items() if k != "api_key"}

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                return data, AuditQuery(
                    api="fec",
                    endpoint=endpoint,
                    params=log_params,
                    timestamp=datetime.now(),
                    results_count=len(data.get("results", [])),
                    success=True,
                    error=None,
                )

            elif response.status_code == 429:
                # Rate limited - back off and retry
                backoff = INITIAL_BACKOFF * (2**attempt)
                time.sleep(backoff)
                continue

            else:
                # Other HTTP error
                return None, AuditQuery(
                    api="fec",
                    endpoint=endpoint,
                    params=log_params,
                    timestamp=datetime.now(),
                    results_count=0,
                    success=False,
                    error=f"HTTP {response.status_code}: {response.text[:200]}",
                )

        except requests.exceptions.Timeout:
            backoff = INITIAL_BACKOFF * (2**attempt)
            time.sleep(backoff)
            continue

        except requests.exceptions.RequestException as e:
            return None, AuditQuery(
                api="fec",
                endpoint=endpoint,
                params=log_params,
                timestamp=datetime.now(),
                results_count=0,
                success=False,
                error=f"Request error: {str(e)}",
            )

    # All retries exhausted
    return None, AuditQuery(
        api="fec",
        endpoint=endpoint,
        params=log_params,
        timestamp=datetime.now(),
        results_count=0,
        success=False,
        error=f"Max retries ({MAX_RETRIES}) exceeded",
    )


def _calculate_confidence(
    profile: PersonProfile, result: dict, base: float
) -> float:
    """
    Calculate final confidence based on field alignment.

    Boosts confidence if employer matches.
    Reduces confidence if expected city doesn't match.
    """
    confidence = base

    # Boost if employer matches
    result_employer = (result.get("contributor_employer") or "").lower()
    if profile.current_employer:
        employer_lower = profile.current_employer.lower()
        if employer_lower in result_employer or result_employer in employer_lower:
            confidence = min(confidence + 0.1, 1.0)

    # Reduce if city doesn't match when we have city data
    result_city = (result.get("contributor_city") or "").lower()
    if profile.city and result_city:
        if profile.city.lower() != result_city:
            confidence = max(confidence - 0.1, 0.1)

    # Check occupation alignment with title
    result_occupation = (result.get("contributor_occupation") or "").lower()
    if profile.current_title:
        title_words = set(profile.current_title.lower().split())
        occupation_words = set(result_occupation.split())
        if title_words & occupation_words:  # Any overlap
            confidence = min(confidence + 0.05, 1.0)

    return round(confidence, 2)
