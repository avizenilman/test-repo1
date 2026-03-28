#!/usr/bin/env python3
"""
Web search enrichment using DSPy for structured extraction.

This module searches the web for information about each person and uses
DSPy to extract structured data (location, employer, spouse, net worth,
political history, etc.).

DSPy optimizes the prompts for consistent, accurate extraction.
"""

import os
import re
import json
from datetime import datetime
from typing import Optional
import requests

# DSPy for structured LLM extraction
try:
    import dspy
    DSPY_AVAILABLE = True
except ImportError:
    DSPY_AVAILABLE = False
    print("⚠️  DSPy not installed. Run: pip install dspy-ai")

from models import PersonProfile, LinkedInProfile, NameVariant, Employer


# ============================================================
# DSPy SIGNATURES - Define what we want to extract
# ============================================================

if DSPY_AVAILABLE:
    class ExtractPersonInfo(dspy.Signature):
        """Extract structured information about a person from web search results."""

        search_results: str = dspy.InputField(desc="Raw web search results about a person")
        person_name: str = dspy.InputField(desc="The person's name we're researching")
        known_context: str = dspy.InputField(desc="What we already know about them")

        full_name: str = dspy.OutputField(desc="Full legal name")
        current_employer: str = dspy.OutputField(desc="Current company/organization")
        current_title: str = dspy.OutputField(desc="Current job title")
        city: str = dspy.OutputField(desc="City of residence")
        state: str = dspy.OutputField(desc="State (2-letter code)")
        spouse_name: str = dspy.OutputField(desc="Spouse's full name if mentioned, else 'Unknown'")
        spouse_employer: str = dspy.OutputField(desc="Spouse's employer if mentioned, else 'Unknown'")
        estimated_net_worth: str = dspy.OutputField(desc="Estimated net worth if mentioned, else 'Unknown'")
        political_affiliation: str = dspy.OutputField(desc="Political leaning/party if evident")
        notable_donations: str = dspy.OutputField(desc="Any mentioned political donations or causes")
        board_positions: str = dspy.OutputField(desc="Nonprofit board positions, comma-separated")
        key_facts: str = dspy.OutputField(desc="3-5 key facts relevant to donor research")

    class ExtractSpouseInfo(dspy.Signature):
        """Extract information about a person's spouse from search results."""

        search_results: str = dspy.InputField(desc="Web search results")
        primary_person: str = dspy.InputField(desc="The primary person we're researching")
        spouse_name: str = dspy.InputField(desc="The spouse's name")

        spouse_full_name: str = dspy.OutputField(desc="Spouse's full legal name")
        spouse_employer: str = dspy.OutputField(desc="Spouse's current employer")
        spouse_title: str = dspy.OutputField(desc="Spouse's job title")
        spouse_city: str = dspy.OutputField(desc="City")
        spouse_state: str = dspy.OutputField(desc="State (2-letter code)")
        spouse_net_worth: str = dspy.OutputField(desc="Spouse's estimated net worth if known")
        spouse_notable: str = dspy.OutputField(desc="Notable facts about spouse")


# ============================================================
# WEB SEARCH FUNCTION
# ============================================================

def web_search(query: str, num_results: int = 10) -> list[dict]:
    """
    Perform web search and return results.

    Uses multiple search strategies:
    1. DuckDuckGo Instant Answer API (free, no key)
    2. Fallback to scraping if needed
    """
    results = []

    # Try DuckDuckGo
    try:
        ddg_results = _search_duckduckgo(query, num_results)
        results.extend(ddg_results)
    except Exception as e:
        print(f"  DDG search failed: {e}")

    return results


def _search_duckduckgo(query: str, num_results: int = 10) -> list[dict]:
    """Search using DuckDuckGo."""
    results = []

    # DuckDuckGo Instant Answer API
    url = "https://api.duckduckgo.com/"
    params = {
        "q": query,
        "format": "json",
        "no_html": 1,
        "skip_disambig": 1,
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()

            # Abstract
            if data.get("Abstract"):
                results.append({
                    "title": data.get("Heading", query),
                    "snippet": data.get("Abstract"),
                    "url": data.get("AbstractURL", ""),
                })

            # Related topics
            for topic in data.get("RelatedTopics", [])[:num_results]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "title": topic.get("Text", "")[:100],
                        "snippet": topic.get("Text", ""),
                        "url": topic.get("FirstURL", ""),
                    })
    except Exception as e:
        print(f"  DuckDuckGo error: {e}")

    return results


def format_search_results(results: list[dict]) -> str:
    """Format search results into a string for LLM processing."""
    if not results:
        return "No search results found."

    formatted = []
    for i, r in enumerate(results, 1):
        formatted.append(f"[{i}] {r.get('title', 'No title')}")
        formatted.append(f"    {r.get('snippet', 'No snippet')}")
        formatted.append(f"    URL: {r.get('url', 'No URL')}")
        formatted.append("")

    return "\n".join(formatted)


# ============================================================
# ENRICHMENT FUNCTIONS
# ============================================================

def enrich_person(
    name: str,
    known_context: str = "",
    known_employer: str = None,
    known_location: str = None,
    known_spouse: str = None,
) -> dict:
    """
    Enrich a person's profile using web search + DSPy extraction.

    Args:
        name: Person's name
        known_context: Any context we already have
        known_employer: Known employer if any
        known_location: Known location if any
        known_spouse: Known spouse name if any

    Returns:
        Dictionary with extracted information
    """
    print(f"\n🔍 Enriching: {name}")

    enriched = {
        "name": name,
        "searched_at": datetime.now().isoformat(),
        "search_queries": [],
        "raw_results": [],
    }

    # Build search queries
    queries = [
        f'"{name}" professional background',
        f'"{name}" linkedin',
    ]

    if known_employer:
        queries.append(f'"{name}" {known_employer}')

    if known_spouse:
        queries.append(f'"{name}" {known_spouse} married')

    # Donor-specific queries
    queries.extend([
        f'"{name}" political donations donor',
        f'"{name}" foundation nonprofit board',
        f'"{name}" net worth wealth',
    ])

    # Run searches
    all_results = []
    for query in queries[:5]:  # Limit to 5 queries
        print(f"  Searching: {query[:50]}...")
        enriched["search_queries"].append(query)

        results = web_search(query, num_results=5)
        all_results.extend(results)

    enriched["raw_results"] = all_results

    # Format for LLM
    formatted_results = format_search_results(all_results)

    # Extract structured data with DSPy (or fallback)
    if DSPY_AVAILABLE and os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"):
        extracted = _extract_with_dspy(name, formatted_results, known_context)
    else:
        extracted = _extract_with_patterns(name, formatted_results, known_context)

    enriched.update(extracted)

    # Search for spouse if found
    spouse_name = extracted.get("spouse_name")
    if spouse_name and spouse_name != "Unknown" and spouse_name != known_spouse:
        print(f"  Found spouse: {spouse_name}, enriching...")
        spouse_info = _enrich_spouse(name, spouse_name, formatted_results)
        enriched["spouse_info"] = spouse_info
    elif known_spouse:
        print(f"  Enriching known spouse: {known_spouse}")
        spouse_info = _enrich_spouse(name, known_spouse, "")
        enriched["spouse_info"] = spouse_info

    return enriched


def _extract_with_dspy(name: str, search_results: str, known_context: str) -> dict:
    """Extract structured info using DSPy."""

    # Configure DSPy with available LLM
    if os.getenv("ANTHROPIC_API_KEY"):
        lm = dspy.Claude(model="claude-3-haiku-20240307")
    elif os.getenv("OPENAI_API_KEY"):
        lm = dspy.OpenAI(model="gpt-3.5-turbo")
    else:
        return _extract_with_patterns(name, search_results, known_context)

    dspy.configure(lm=lm)

    # Create extractor module
    extractor = dspy.ChainOfThought(ExtractPersonInfo)

    try:
        result = extractor(
            search_results=search_results[:8000],  # Truncate if needed
            person_name=name,
            known_context=known_context or "No prior context",
        )

        return {
            "full_name": result.full_name,
            "current_employer": result.current_employer,
            "current_title": result.current_title,
            "city": result.city,
            "state": result.state,
            "spouse_name": result.spouse_name,
            "spouse_employer": result.spouse_employer,
            "estimated_net_worth": result.estimated_net_worth,
            "political_affiliation": result.political_affiliation,
            "notable_donations": result.notable_donations,
            "board_positions": result.board_positions,
            "key_facts": result.key_facts,
            "extraction_method": "dspy",
        }
    except Exception as e:
        print(f"  DSPy extraction failed: {e}")
        return _extract_with_patterns(name, search_results, known_context)


def _extract_with_patterns(name: str, search_results: str, known_context: str) -> dict:
    """Fallback: Extract info using regex patterns (no LLM needed)."""

    text = search_results.lower()

    extracted = {
        "full_name": name,
        "current_employer": None,
        "current_title": None,
        "city": None,
        "state": None,
        "spouse_name": "Unknown",
        "spouse_employer": "Unknown",
        "estimated_net_worth": "Unknown",
        "political_affiliation": "Unknown",
        "notable_donations": "Unknown",
        "board_positions": "",
        "key_facts": "",
        "extraction_method": "patterns",
    }

    # Extract employer patterns
    employer_patterns = [
        r"(?:ceo|founder|partner|director|vp|president|coo|cfo|cto)\s+(?:at|of)\s+([A-Z][A-Za-z\s&]+)",
        r"works?\s+at\s+([A-Z][A-Za-z\s&]+)",
        r"([A-Z][A-Za-z\s&]+)\s+(?:ceo|founder|partner)",
    ]

    for pattern in employer_patterns:
        match = re.search(pattern, search_results, re.IGNORECASE)
        if match:
            extracted["current_employer"] = match.group(1).strip()
            break

    # Extract location
    location_patterns = [
        r"(?:based in|lives in|from)\s+([A-Z][a-z]+(?:,\s*[A-Z]{2})?)",
        r"([A-Z][a-z]+),\s*(CA|NY|TX|FL|WA|MA|GA|IL|PA|CO)",
    ]

    for pattern in location_patterns:
        match = re.search(pattern, search_results)
        if match:
            if "," in match.group(0):
                parts = match.group(0).split(",")
                extracted["city"] = parts[0].strip()
                extracted["state"] = parts[1].strip() if len(parts) > 1 else None
            else:
                extracted["city"] = match.group(1)
            break

    # Extract spouse
    spouse_patterns = [
        rf"{name.split()[0]}(?:'s)?\s+(?:wife|husband|spouse|partner)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)",
        r"married to\s+([A-Z][a-z]+\s+[A-Z][a-z]+)",
    ]

    for pattern in spouse_patterns:
        match = re.search(pattern, search_results, re.IGNORECASE)
        if match:
            extracted["spouse_name"] = match.group(1).strip()
            break

    # Extract net worth
    worth_match = re.search(r"\$?([\d.]+)\s*(million|billion|M|B)", search_results, re.IGNORECASE)
    if worth_match:
        amount = float(worth_match.group(1))
        unit = worth_match.group(2).lower()
        if unit in ["billion", "b"]:
            extracted["estimated_net_worth"] = f"${amount}B"
        else:
            extracted["estimated_net_worth"] = f"${amount}M"

    # Political indicators
    if "democrat" in text or "democratic" in text or "biden" in text or "liberal" in text:
        extracted["political_affiliation"] = "Democratic/Liberal"
    elif "republican" in text or "trump" in text or "conservative" in text:
        extracted["political_affiliation"] = "Republican/Conservative"

    return extracted


def _enrich_spouse(primary_name: str, spouse_name: str, existing_results: str) -> dict:
    """Enrich spouse information."""

    # Search for spouse
    queries = [
        f'"{spouse_name}" professional',
        f'"{spouse_name}" {primary_name}',
    ]

    all_results = []
    for query in queries:
        results = web_search(query, num_results=3)
        all_results.extend(results)

    formatted = format_search_results(all_results)

    # Use pattern extraction for spouse (simpler)
    return _extract_with_patterns(spouse_name, formatted + "\n" + existing_results, "")


def enrich_from_targets(targets: list[dict]) -> list[dict]:
    """Enrich all targets from research_targets.json."""

    enriched_targets = []

    for target in targets:
        name = target["name"]

        enriched = enrich_person(
            name=name,
            known_context=target.get("notes", ""),
            known_employer=target.get("employer"),
            known_location=target.get("location"),
            known_spouse=target.get("spouse"),
        )

        # Merge with original target
        merged = {**target, **enriched}
        enriched_targets.append(merged)

    return enriched_targets


def create_enriched_profile(enriched_data: dict) -> PersonProfile:
    """Create a PersonProfile from enriched data."""

    name = enriched_data.get("full_name") or enriched_data.get("name")

    # Generate name variants
    variants = []
    parts = name.split()
    variants.append(NameVariant(value=name, type="current", confidence=1.0))
    if len(parts) >= 2:
        variants.append(NameVariant(value=f"{parts[0]} {parts[-1]}", type="short", confidence=0.95))
    variants.append(NameVariant(value=name.upper(), type="uppercase", confidence=1.0))

    # Build experience
    experience = []
    if enriched_data.get("current_employer"):
        experience.append(Employer(
            name=enriched_data["current_employer"],
            title=enriched_data.get("current_title"),
        ))

    # Parse board positions
    boards = []
    if enriched_data.get("board_positions"):
        boards = [b.strip() for b in enriched_data["board_positions"].split(",") if b.strip()]

    # Create LinkedIn profile
    linkedin = LinkedInProfile(
        url=f"https://linkedin.com/in/{name.lower().replace(' ', '')}",
        full_name=name,
        headline=enriched_data.get("current_title", ""),
        location=f"{enriched_data.get('city', '')}, {enriched_data.get('state', '')}".strip(", "),
        about=enriched_data.get("key_facts", ""),
        experience=experience,
        board_affiliations=boards,
        fetched_at=datetime.now(),
    )

    # Create profile
    profile = PersonProfile(
        canonical_id=name.lower().replace(" ", "-"),
        names=variants,
        current_employer=enriched_data.get("current_employer"),
        current_title=enriched_data.get("current_title"),
        city=enriched_data.get("city"),
        state=enriched_data.get("state"),
        linkedin=linkedin,
    )

    # Add spouse if found
    spouse_info = enriched_data.get("spouse_info")
    if spouse_info or enriched_data.get("spouse_name") not in [None, "Unknown"]:
        spouse_name = spouse_info.get("full_name") if spouse_info else enriched_data.get("spouse_name")
        if spouse_name and spouse_name != "Unknown":
            profile.spouse = create_enriched_profile(spouse_info or {"name": spouse_name})

    return profile


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        name = " ".join(sys.argv[1:])
        result = enrich_person(name)
        print(json.dumps(result, indent=2, default=str))
    else:
        print("Usage: python web_enrichment.py 'Person Name'")
        print("Example: python web_enrichment.py 'Jeremy Liew'")
