#!/usr/bin/env python3
"""
Batch research script for processing the target list.

Loads research_targets.json and runs FEC + nonprofit searches on each person.
Outputs individual dossiers to outputs/ directory.

Usage:
    python batch_research.py                    # Process all targets
    python batch_research.py "Jeremy Liew"      # Process single person
    python batch_research.py --enrich           # Web search enrichment first
"""

import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from models import PersonProfile, LinkedInProfile, NameVariant, Employer
from fec_search import search_fec
from nonprofit_search import search_nonprofits
from synthesis import generate_dossier, save_outputs, dossier_to_markdown


def load_targets(filepath: str = "research_targets.json") -> list[dict]:
    """Load research targets from JSON file."""
    with open(filepath, "r") as f:
        data = json.load(f)
    return data.get("research_list", [])


def create_profile_from_target(target: dict) -> PersonProfile:
    """Create a PersonProfile from a research target entry."""

    name = target["name"]
    location = target.get("location", "")
    employer = target.get("employer")
    notes = target.get("notes", "")

    # Parse location
    city, state = None, None
    if location:
        parts = [p.strip() for p in location.split(",")]
        city = parts[0] if parts else None
        if len(parts) >= 2:
            state = parts[-1].replace("CA", "CA").replace("NY", "NY").strip()
            if len(state) > 2:
                # Map full state names
                state_map = {"California": "CA", "New York": "NY", "Georgia": "GA", "Texas": "TX"}
                state = state_map.get(state, state)

    # Generate name variants
    name_variants = _generate_name_variants(name)

    # Build experience from employer
    experience = []
    if employer:
        experience.append(Employer(name=employer, title=None, start_year=None))

    # Create LinkedIn profile placeholder
    linkedin = LinkedInProfile(
        url=f"https://linkedin.com/in/{name.lower().replace(' ', '')}",
        full_name=name,
        headline=notes,
        location=location,
        about=notes,
        experience=experience,
        board_affiliations=[],
        fetched_at=datetime.now(),
    )

    # Create main profile
    profile = PersonProfile(
        canonical_id=name.lower().replace(" ", "-"),
        names=name_variants,
        current_employer=employer,
        current_title=None,
        city=city,
        state=state,
        linkedin=linkedin,
    )

    # Add spouse if known
    spouse_name = target.get("spouse")
    if spouse_name:
        spouse_profile = _create_spouse_profile(spouse_name, target.get("spouse_notes", ""))
        profile.spouse = spouse_profile

    return profile


def _generate_name_variants(full_name: str) -> list[NameVariant]:
    """Generate name variants for FEC matching."""
    variants = []
    parts = full_name.split()

    variants.append(NameVariant(value=full_name, type="current", confidence=1.0))

    if len(parts) >= 2:
        variants.append(NameVariant(value=f"{parts[0]} {parts[-1]}", type="short", confidence=0.95))

    if len(parts) == 3:
        variants.append(NameVariant(value=f"{parts[0]} {parts[1][0]}. {parts[2]}", type="middle_initial", confidence=0.9))

    variants.append(NameVariant(value=full_name.upper(), type="uppercase", confidence=1.0))

    return variants


def _create_spouse_profile(name: str, notes: str) -> PersonProfile:
    """Create a minimal spouse profile for searching."""
    linkedin = LinkedInProfile(
        url=f"https://linkedin.com/in/{name.lower().replace(' ', '')}",
        full_name=name,
        headline=notes,
        location=None,
        fetched_at=datetime.now(),
    )

    return PersonProfile(
        canonical_id=name.lower().replace(" ", "-"),
        names=_generate_name_variants(name),
        current_employer=None,
        current_title=None,
        city=None,
        state=None,
        linkedin=linkedin,
    )


def research_person(target: dict, api_key: str, output_dir: str = "outputs") -> dict:
    """Run full research pipeline on a single person."""

    name = target["name"]
    print(f"\n{'='*60}")
    print(f"Researching: {name}")
    print(f"{'='*60}")

    # Create profile
    profile = create_profile_from_target(target)
    print(f"Location: {profile.city}, {profile.state}")
    print(f"Employer: {profile.current_employer or 'Unknown'}")
    if profile.spouse:
        print(f"Spouse: {profile.spouse.names[0].value}")

    # Search FEC
    print("\n🔍 Searching FEC...")
    federal, federal_audit = search_fec(profile, api_key)
    print(f"   Found {len(federal)} federal contributions")

    if federal:
        total = sum(c.amount for c in federal)
        print(f"   Total: ${total:,.0f}")

    # Search nonprofits
    print("\n🏛️ Searching nonprofits...")
    boards, foundation, nonprofit_audit = search_nonprofits(profile)
    print(f"   Found {len(boards)} board positions")
    if foundation:
        print(f"   Family foundation: {foundation.name}")

    # Generate dossier
    all_audit = federal_audit + nonprofit_audit

    dossier = generate_dossier(
        profile=profile,
        federal=federal,
        state=[],  # Skip state for batch (slower)
        local=[],  # Skip local for batch
        boards=boards,
        foundation=foundation,
        audit=all_audit,
    )

    # Save outputs
    md_path, json_path = save_outputs(dossier, output_dir)
    print(f"\n📄 Saved: {md_path}")

    return {
        "name": name,
        "federal_total": sum(c.amount for c in federal),
        "federal_count": len(federal),
        "boards": len(boards),
        "foundation": foundation.name if foundation else None,
        "md_path": md_path,
        "json_path": json_path,
    }


def main():
    api_key = os.getenv("FEC_API_KEY")
    if not api_key:
        print("❌ No FEC_API_KEY in .env file")
        print("   Get free key at: https://api.open.fec.gov/developers/")
        sys.exit(1)

    print(f"✅ FEC API key loaded: {api_key[:8]}...")

    # Load targets
    targets = load_targets()
    print(f"📋 Loaded {len(targets)} research targets")

    # Check for single-person mode
    if len(sys.argv) > 1 and sys.argv[1] != "--enrich":
        search_name = sys.argv[1]
        targets = [t for t in targets if search_name.lower() in t["name"].lower()]
        if not targets:
            print(f"❌ No target found matching '{search_name}'")
            sys.exit(1)
        print(f"   Filtering to: {[t['name'] for t in targets]}")

    # Run research
    results = []
    for target in targets:
        try:
            result = research_person(target, api_key)
            results.append(result)
        except Exception as e:
            print(f"❌ Error researching {target['name']}: {e}")
            results.append({"name": target["name"], "error": str(e)})

    # Summary
    print("\n" + "="*60)
    print("BATCH RESEARCH SUMMARY")
    print("="*60)

    total_federal = sum(r.get("federal_total", 0) for r in results)
    total_records = sum(r.get("federal_count", 0) for r in results)

    print(f"\nProcessed: {len(results)} people")
    print(f"Total federal contributions found: ${total_federal:,.0f} ({total_records} records)")

    print("\nTop donors by federal contributions:")
    sorted_results = sorted(results, key=lambda x: x.get("federal_total", 0), reverse=True)
    for r in sorted_results[:10]:
        if r.get("federal_total", 0) > 0:
            print(f"  ${r['federal_total']:>12,.0f} | {r['name']}")

    print(f"\n📁 Dossiers saved to: outputs/")


if __name__ == "__main__":
    main()
