"""
Local jurisdiction campaign finance search.

Searches city/county ethics commission and campaign finance databases.
Each jurisdiction has different data access methods.

Supported jurisdictions:
- San Francisco Ethics Commission (sfethics.org)
- LA City Ethics Commission (ethics.lacity.org)
- NYC Campaign Finance Board (nyccfb.info)
- Oakland Public Ethics Commission
- (Extensible to other jurisdictions)

When a profile is in a supported city, we also search neighboring
jurisdictions where donors commonly contribute.
"""

import re
import time
import requests
from datetime import datetime
from typing import Optional

from models import PersonProfile, Contribution, AuditQuery


# Registry of local campaign finance databases
# Each entry includes: name, base URL, search endpoint, and neighboring cities
LOCAL_DATABASES = {
    "san francisco": {
        "name": "SF Ethics Commission",
        "base_url": "https://sfethics.org",
        "api_endpoint": "/api/contributions",  # Hypothetical - actual may differ
        "neighbors": ["oakland", "berkeley", "san jose", "daly city"],
        "state": "CA",
    },
    "los angeles": {
        "name": "LA City Ethics Commission",
        "base_url": "https://ethics.lacity.org",
        "api_endpoint": "/api/search",
        "neighbors": ["santa monica", "pasadena", "long beach", "burbank"],
        "state": "CA",
    },
    "new york": {
        "name": "NYC Campaign Finance Board",
        "base_url": "https://www.nyccfb.info",
        "api_endpoint": "/searchabledb/",
        "neighbors": ["yonkers", "jersey city", "newark"],
        "state": "NY",
    },
    "oakland": {
        "name": "Oakland Public Ethics Commission",
        "base_url": "https://www.oaklandca.gov",
        "api_endpoint": "/services/public-ethics-commission",
        "neighbors": ["san francisco", "berkeley", "alameda"],
        "state": "CA",
    },
    "seattle": {
        "name": "Seattle Ethics and Elections Commission",
        "base_url": "https://web6.seattle.gov/ethics",
        "api_endpoint": "/campaigns",
        "neighbors": ["bellevue", "tacoma"],
        "state": "WA",
    },
    "chicago": {
        "name": "Illinois State Board of Elections",
        "base_url": "https://www.elections.il.gov",
        "api_endpoint": "/campaigndisclosure",
        "neighbors": ["evanston", "oak park"],
        "state": "IL",
    },
    "boston": {
        "name": "Massachusetts OCPF",
        "base_url": "https://www.ocpf.us",
        "api_endpoint": "/search",
        "neighbors": ["cambridge", "brookline", "somerville"],
        "state": "MA",
    },
    "washington": {
        "name": "DC Office of Campaign Finance",
        "base_url": "https://ocf.dc.gov",
        "api_endpoint": "/contribution-search",
        "neighbors": ["arlington", "bethesda", "alexandria"],
        "state": "DC",
    },
}

# Alternate city name mappings
CITY_ALIASES = {
    "sf": "san francisco",
    "la": "los angeles",
    "nyc": "new york",
    "dc": "washington",
}


def search_local(
    profile: PersonProfile,
) -> tuple[list[Contribution], list[AuditQuery]]:
    """
    Search local jurisdiction campaign finance databases.

    Searches the profile's home jurisdiction plus neighboring cities
    where donors commonly contribute.

    Args:
        profile: PersonProfile with city/state information

    Returns:
        Tuple of (contributions list, audit queries list)
    """
    contributions = []
    audit = []

    if not profile.city:
        # Log that we couldn't search local due to missing city
        audit.append(
            AuditQuery(
                api="local",
                endpoint="n/a",
                params={"reason": "no city in profile"},
                timestamp=datetime.now(),
                results_count=0,
                success=True,
                error="Skipped local search - no city in profile",
            )
        )
        return contributions, audit

    city_lower = _normalize_city(profile.city)
    searched_cities: set[str] = set()

    # Search primary jurisdiction
    if city_lower in LOCAL_DATABASES:
        db = LOCAL_DATABASES[city_lower]
        results, queries = _search_local_db(profile, db, city_lower)
        contributions.extend(results)
        audit.extend(queries)
        searched_cities.add(city_lower)

        # Search neighboring jurisdictions
        for neighbor in db.get("neighbors", []):
            if neighbor not in searched_cities and neighbor in LOCAL_DATABASES:
                neighbor_db = LOCAL_DATABASES[neighbor]
                n_results, n_queries = _search_local_db(
                    profile, neighbor_db, neighbor
                )
                contributions.extend(n_results)
                audit.extend(n_queries)
                searched_cities.add(neighbor)
    else:
        # City not in our database - log it
        audit.append(
            AuditQuery(
                api="local",
                endpoint="n/a",
                params={"city": city_lower},
                timestamp=datetime.now(),
                results_count=0,
                success=True,
                error=f"City '{profile.city}' not in local database registry",
            )
        )

    # Search spouse's jurisdiction if different
    if profile.spouse and profile.spouse.city:
        spouse_city = _normalize_city(profile.spouse.city)
        if spouse_city not in searched_cities and spouse_city in LOCAL_DATABASES:
            spouse_contributions, spouse_audit = search_local(profile.spouse)
            contributions.extend(spouse_contributions)
            audit.extend(spouse_audit)

    return contributions, audit


def _normalize_city(city: str) -> str:
    """Normalize city name to match database keys."""
    city_lower = city.lower().strip()

    # Check aliases
    if city_lower in CITY_ALIASES:
        return CITY_ALIASES[city_lower]

    # Remove common suffixes
    city_lower = re.sub(r"\s+city$", "", city_lower)

    return city_lower


def _search_local_db(
    profile: PersonProfile, db: dict, city_key: str
) -> tuple[list[Contribution], list[AuditQuery]]:
    """
    Search a specific local database.

    Different databases have different interfaces:
    - Some have APIs (rare)
    - Some have searchable web forms
    - Some require CSV downloads

    This function attempts the best available method for each.
    """
    contributions = []
    audit = []
    seen_ids: set[str] = set()

    for name_variant in profile.names:
        name = name_variant.value

        # Skip low confidence variants
        if name_variant.confidence < 0.6:
            continue

        # Attempt to query the database
        results, query_audit = _query_local_api(
            name=name,
            profile=profile,
            db=db,
        )
        audit.extend(query_audit)

        for result in results:
            # Generate unique ID for deduplication
            result_id = (
                f"{city_key}-{result['date']}-{result['amount']}-{result['recipient']}"
            )
            if result_id in seen_ids:
                continue
            seen_ids.add(result_id)

            # Calculate confidence
            confidence = _calculate_local_confidence(
                profile, result, name_variant.confidence
            )

            contributions.append(
                Contribution(
                    date=result["date"],
                    amount=result["amount"],
                    recipient=result["recipient"],
                    recipient_type=result.get("recipient_type"),
                    source=f"local_{city_key.replace(' ', '_')}",
                    source_id=result.get("transaction_id"),
                    confidence=confidence,
                    match_reason=f"{db['name']} search ({name_variant.type})",
                )
            )

    return contributions, audit


def _query_local_api(
    name: str, profile: PersonProfile, db: dict
) -> tuple[list[dict], list[AuditQuery]]:
    """
    Query a local database API or web interface.

    This is a framework that can be customized per-jurisdiction.
    Most local databases require HTML scraping or specific API knowledge.
    """
    results = []
    audit = []

    db_name = db["name"]
    base_url = db["base_url"]
    endpoint = db.get("api_endpoint", "")

    params = {
        "name": name,
        "contributor": name,  # Some use different param names
    }

    # Add location filters if available
    if profile.city:
        params["city"] = profile.city
    if profile.state:
        params["state"] = profile.state

    try:
        # Attempt API request
        url = f"{base_url}{endpoint}"
        response = requests.get(url, params=params, timeout=30)

        if response.status_code == 200:
            # Try to parse JSON
            try:
                data = response.json()
                records = data if isinstance(data, list) else data.get(
                    "contributions", data.get("results", [])
                )

                for record in records:
                    # Normalize field names (different DBs use different schemas)
                    results.append(
                        {
                            "date": record.get(
                                "date",
                                record.get(
                                    "contribution_date",
                                    record.get("tran_date", ""),
                                ),
                            ),
                            "amount": float(
                                record.get(
                                    "amount",
                                    record.get(
                                        "contribution_amount",
                                        record.get("tran_amt1", 0),
                                    ),
                                )
                            ),
                            "recipient": record.get(
                                "recipient",
                                record.get(
                                    "committee",
                                    record.get("filer_naml", "Unknown"),
                                ),
                            ),
                            "recipient_type": record.get(
                                "recipient_type", record.get("committee_type")
                            ),
                            "transaction_id": record.get(
                                "transaction_id",
                                record.get("tran_id"),
                            ),
                        }
                    )

                audit.append(
                    AuditQuery(
                        api=f"local_{db_name.lower().replace(' ', '_')}",
                        endpoint=endpoint,
                        params=params,
                        timestamp=datetime.now(),
                        results_count=len(results),
                        success=True,
                        error=None,
                    )
                )

            except ValueError:
                # Response is HTML - would need scraping
                audit.append(
                    AuditQuery(
                        api=f"local_{db_name.lower().replace(' ', '_')}",
                        endpoint=endpoint,
                        params=params,
                        timestamp=datetime.now(),
                        results_count=0,
                        success=True,
                        error="Response is HTML - scraping required",
                    )
                )
        else:
            audit.append(
                AuditQuery(
                    api=f"local_{db_name.lower().replace(' ', '_')}",
                    endpoint=endpoint,
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
                api=f"local_{db_name.lower().replace(' ', '_')}",
                endpoint=endpoint,
                params=params,
                timestamp=datetime.now(),
                results_count=0,
                success=False,
                error=str(e),
            )
        )

    return results, audit


def _calculate_local_confidence(
    profile: PersonProfile, result: dict, name_confidence: float
) -> float:
    """
    Calculate confidence for local contribution match.

    Local databases typically have good location data but variable
    employer/occupation data. We weight accordingly.
    """
    # Start with discounted name confidence (local data is less standardized)
    confidence = name_confidence * 0.6

    # Strong boost if in the expected city
    result_city = result.get("city", "").lower()
    if profile.city and result_city:
        if profile.city.lower() in result_city or result_city in profile.city.lower():
            confidence = min(confidence + 0.25, 0.9)

    # Boost if employer matches
    result_employer = result.get("employer", "").lower()
    if profile.current_employer and result_employer:
        employer_lower = profile.current_employer.lower()
        if employer_lower in result_employer or result_employer in employer_lower:
            confidence = min(confidence + 0.15, 0.95)

    # Slight boost if occupation matches title
    result_occupation = result.get("occupation", "").lower()
    if profile.current_title and result_occupation:
        title_words = set(profile.current_title.lower().split())
        occ_words = set(result_occupation.split())
        if title_words & occ_words:
            confidence = min(confidence + 0.1, 0.9)

    return round(confidence, 2)
