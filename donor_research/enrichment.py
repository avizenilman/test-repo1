"""
LinkedIn profile enrichment via web search aggregators.

Since LinkedIn blocks direct scraping, we search for profile data from
aggregator sites like Crunchbase, TheOrg, company pages, and news articles.

The approach:
1. Extract the LinkedIn username from the URL
2. Search for "{name} site:crunchbase.com OR site:theorg.com" etc.
3. Parse structured data from search snippets
4. Store everything in raw_text for audit purposes
"""

import re
import requests
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from models import (
    PersonProfile,
    LinkedInProfile,
    NameVariant,
    Employer,
    AuditSource,
)


def extract_profile(linkedin_url: str) -> PersonProfile:
    """
    Extract profile data from LinkedIn URL via web search aggregators.
    Stores full raw data in LinkedInProfile for audit purposes.

    Args:
        linkedin_url: Full LinkedIn profile URL

    Returns:
        PersonProfile with canonical identity and full LinkedIn data
    """
    # Step 1: Parse LinkedIn URL to get username
    username = _extract_linkedin_username(linkedin_url)

    # Step 2: Search for profile data via aggregators
    search_results = _search_aggregators(linkedin_url, username)

    # Step 3: Parse structured data from results
    parsed = _parse_aggregator_results(search_results, username)

    # Step 4: Generate name variants for fuzzy matching
    name_variants = _generate_name_variants(parsed["full_name"])

    # Step 5: Build LinkedInProfile with ALL raw data
    linkedin_profile = LinkedInProfile(
        url=linkedin_url,
        full_name=parsed["full_name"],
        headline=parsed.get("headline"),
        location=parsed.get("location"),
        about=parsed.get("about"),
        experience=[Employer(**e) for e in parsed.get("experience", [])],
        education=parsed.get("education", []),
        board_affiliations=parsed.get("boards", []),
        raw_text=parsed.get("raw_text"),
        fetched_at=datetime.now(),
    )

    # Step 6: Extract city/state from location
    city, state = _parse_location(parsed.get("location", ""))

    # Step 7: Build canonical profile
    canonical_id = _make_canonical_id(
        parsed["full_name"], parsed.get("current_employer")
    )

    return PersonProfile(
        canonical_id=canonical_id,
        names=name_variants,
        current_employer=parsed.get("current_employer"),
        current_title=parsed.get("current_title"),
        city=city,
        state=state,
        linkedin=linkedin_profile,
    )


def _extract_linkedin_username(url: str) -> str:
    """Extract username from LinkedIn URL."""
    # Handle various URL formats:
    # https://www.linkedin.com/in/johndoe
    # https://linkedin.com/in/johndoe/
    # linkedin.com/in/johndoe

    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if path.startswith("in/"):
        username = path[3:].split("/")[0]
        return username

    # Fallback: return the last path segment
    return path.split("/")[-1] or "unknown"


def _search_aggregators(linkedin_url: str, username: str) -> dict:
    """
    Search web for LinkedIn profile data via aggregators.

    Searches multiple sources:
    - Crunchbase (for executives)
    - TheOrg (org charts)
    - Company websites
    - News articles

    Returns dict with raw search results from each source.
    """
    results = {
        "linkedin_url": linkedin_url,
        "username": username,
        "sources": [],
        "raw_snippets": [],
    }

    # NOTE: In production, you would implement actual web searches here.
    # Options include:
    # 1. Use a search API (Google Custom Search, Bing, SerpAPI)
    # 2. Use a professional data provider (Clearbit, Apollo, etc.)
    # 3. Manual lookup and paste (for small batches)

    # For now, we'll try to extract what we can from the LinkedIn URL itself
    # and provide a framework for adding real search integration.

    # Placeholder: In production, replace with actual search calls
    # Example search queries that would be made:
    # f'"{username}" site:crunchbase.com'
    # f'"{username}" site:theorg.com'
    # f'"{username}" linkedin'

    return results


def _parse_aggregator_results(results: dict, username: str) -> dict:
    """
    Parse structured fields from search results.

    Extracts:
    - full_name: Best guess at full name
    - headline: Professional headline
    - location: Geographic location
    - about: Bio/summary text
    - experience: List of employers
    - education: List of schools
    - boards: Board affiliations
    - current_employer: Most recent employer
    - current_title: Most recent title
    - raw_text: Everything concatenated for audit
    """
    parsed = {
        "full_name": _username_to_name(username),
        "headline": None,
        "location": None,
        "about": None,
        "experience": [],
        "education": [],
        "boards": [],
        "current_employer": None,
        "current_title": None,
        "raw_text": "",
    }

    # Concatenate all raw snippets for audit
    raw_parts = []
    for snippet in results.get("raw_snippets", []):
        raw_parts.append(snippet)

    # Extract structured data from snippets
    for snippet in results.get("raw_snippets", []):
        # Look for name patterns
        name_match = re.search(r"^([A-Z][a-z]+ [A-Z][a-z]+)", snippet)
        if name_match and not parsed["full_name"]:
            parsed["full_name"] = name_match.group(1)

        # Look for location patterns
        location_match = re.search(
            r"((?:San Francisco|New York|Los Angeles|Chicago|Boston|Seattle|"
            r"Austin|Denver|Miami|Atlanta|Washington)[^,]*,?\s*"
            r"(?:CA|NY|IL|MA|WA|TX|CO|FL|GA|DC)?)",
            snippet,
            re.IGNORECASE,
        )
        if location_match and not parsed["location"]:
            parsed["location"] = location_match.group(1).strip()

        # Look for title @ company patterns
        title_match = re.search(
            r"(CEO|CFO|CTO|COO|President|Partner|Director|VP|"
            r"Vice President|Founder|Managing|Principal)[^@|]*"
            r"(?:@|at|,)\s*([A-Za-z0-9\s&]+)",
            snippet,
            re.IGNORECASE,
        )
        if title_match:
            if not parsed["current_title"]:
                parsed["current_title"] = title_match.group(1).strip()
            if not parsed["current_employer"]:
                parsed["current_employer"] = title_match.group(2).strip()

    parsed["raw_text"] = "\n---\n".join(raw_parts) if raw_parts else None

    return parsed


def _username_to_name(username: str) -> str:
    """
    Convert LinkedIn username to probable name.

    Handles formats like:
    - johndoe -> John Doe
    - john-doe -> John Doe
    - jdoe123 -> Jdoe123 (can't reliably parse)
    """
    # Remove numbers at the end (linkedin adds these for duplicates)
    clean = re.sub(r"\d+$", "", username)

    # Split on hyphens or detect camelCase boundaries
    if "-" in clean:
        parts = clean.split("-")
    else:
        # Try to split camelCase or just capitalize
        parts = re.findall(r"[A-Z]?[a-z]+", clean)

    if not parts:
        return username.title()

    # Capitalize each part
    return " ".join(part.capitalize() for part in parts)


def _generate_name_variants(full_name: str) -> list[NameVariant]:
    """
    Generate name variants for fuzzy matching across databases.

    FEC and other databases store names inconsistently:
    - JOHN DOE
    - John Doe
    - John M. Doe
    - John Michael Doe
    - J. Doe

    We generate variants to match against all these patterns.
    """
    variants = []
    parts = full_name.split()

    if not parts:
        return [NameVariant(value=full_name, type="current")]

    # Current name (as provided)
    variants.append(NameVariant(value=full_name, type="current", confidence=1.0))

    # First + Last only (skip middle names)
    if len(parts) >= 2:
        short_name = f"{parts[0]} {parts[-1]}"
        if short_name != full_name:
            variants.append(
                NameVariant(value=short_name, type="short", confidence=0.95)
            )

    # With middle initial
    if len(parts) == 3:
        middle_initial = f"{parts[0]} {parts[1][0]}. {parts[2]}"
        variants.append(
            NameVariant(value=middle_initial, type="middle_initial", confidence=0.9)
        )

    # First initial + last name
    if len(parts) >= 2:
        initial_last = f"{parts[0][0]}. {parts[-1]}"
        variants.append(
            NameVariant(value=initial_last, type="initial", confidence=0.7)
        )

    # All caps version (FEC often stores names this way)
    variants.append(
        NameVariant(value=full_name.upper(), type="uppercase", confidence=1.0)
    )

    return variants


def _parse_location(location: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract city and state from location string.

    Handles various formats:
    - "San Francisco, California"
    - "San Francisco, CA"
    - "SF Bay Area"
    - "Greater New York City Area"
    - "New York, NY"
    """
    if not location:
        return None, None

    location = location.strip()

    # Remove common country suffixes
    location = re.sub(r",?\s*United States\s*$", "", location, flags=re.IGNORECASE)
    location = re.sub(r",?\s*USA\s*$", "", location, flags=re.IGNORECASE)
    location = location.strip()

    # State abbreviation mapping
    state_abbrevs = {
        "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
        "california": "CA", "colorado": "CO", "connecticut": "CT",
        "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI",
        "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
        "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
        "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
        "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
        "montana": "MT", "nebraska": "NE", "nevada": "NV",
        "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
        "new york": "NY", "north carolina": "NC", "north dakota": "ND",
        "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
        "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
        "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
        "virginia": "VA", "washington": "WA", "west virginia": "WV",
        "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
    }

    # Common city -> state mappings for "Area" format
    city_state_map = {
        "san francisco": ("San Francisco", "CA"),
        "sf": ("San Francisco", "CA"),
        "los angeles": ("Los Angeles", "CA"),
        "la": ("Los Angeles", "CA"),
        "new york": ("New York", "NY"),
        "nyc": ("New York", "NY"),
        "chicago": ("Chicago", "IL"),
        "boston": ("Boston", "MA"),
        "seattle": ("Seattle", "WA"),
        "austin": ("Austin", "TX"),
        "denver": ("Denver", "CO"),
        "miami": ("Miami", "FL"),
        "atlanta": ("Atlanta", "GA"),
        "washington": ("Washington", "DC"),
        "dc": ("Washington", "DC"),
        "palo alto": ("Palo Alto", "CA"),
        "menlo park": ("Menlo Park", "CA"),
        "mountain view": ("Mountain View", "CA"),
    }

    location_lower = location.lower()

    # Handle "Greater X Area" or "X Bay Area" format
    area_match = re.search(r"(?:greater\s+)?(\w+(?:\s+\w+)?)\s+(?:bay\s+)?area", location_lower)
    if area_match:
        city_key = area_match.group(1).strip()
        if city_key in city_state_map:
            return city_state_map[city_key]

    # Handle "City, State" format
    if "," in location:
        parts = [p.strip() for p in location.split(",")]
        city = parts[0]

        if len(parts) >= 2:
            state_part = parts[-1].lower()

            # Check if it's a full state name
            if state_part in state_abbrevs:
                return city, state_abbrevs[state_part]

            # Check if it's already an abbreviation
            if state_part.upper() in state_abbrevs.values():
                return city, state_part.upper()

        return city, None

    # Check for known cities without comma
    for city_key, (city_name, state) in city_state_map.items():
        if city_key in location_lower:
            return city_name, state

    # Last resort: return as city with no state
    return location, None


def _make_canonical_id(name: str, employer: Optional[str]) -> str:
    """
    Generate canonical ID slug for file naming.

    Format: lastname-firstname-employer
    Example: doe-john-acme-corp
    """
    # Clean name
    name_parts = name.lower().split()
    if len(name_parts) >= 2:
        name_slug = f"{name_parts[-1]}-{name_parts[0]}"
    else:
        name_slug = re.sub(r"[^a-z0-9]", "-", name.lower())

    # Clean employer
    if employer:
        emp_slug = re.sub(r"[^a-z0-9]", "-", employer.lower())
        emp_slug = re.sub(r"-+", "-", emp_slug).strip("-")
    else:
        emp_slug = "unknown"

    # Combine and clean
    canonical = f"{name_slug}-{emp_slug}"
    canonical = re.sub(r"-+", "-", canonical)

    return canonical
