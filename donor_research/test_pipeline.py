#!/usr/bin/env python3
"""
Test script for the donor research pipeline.

Run this locally to test with real API calls:
    python test_pipeline.py

Requires:
    - FEC_API_KEY in .env file (get free key at api.open.fec.gov)
    - pip install requests pydantic python-dotenv
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Import our modules
from manual_entry import get_example_profile, create_profile_from_manual_data
from fec_search import search_fec
from state_search import search_state
from local_search import search_local
from nonprofit_search import search_nonprofits
from synthesis import generate_dossier, dossier_to_markdown, save_outputs


def test_with_alison_pincus():
    """Test the full pipeline with Alison Gelb Pincus data from screenshots."""

    print("=" * 70)
    print("DONOR RESEARCH PIPELINE TEST")
    print("=" * 70)

    # Check API key
    api_key = os.getenv("FEC_API_KEY")
    if not api_key:
        print("\n⚠️  No FEC_API_KEY found in .env")
        print("   Get a free key at: https://api.open.fec.gov/developers/")
        print("   Add to .env: FEC_API_KEY=your_key_here")
        print("\n   Continuing with limited testing...\n")
        api_key = "DEMO_KEY"  # Limited rate
    else:
        print(f"\n✅ FEC API Key loaded: {api_key[:8]}...")

    # Step 1: Create profile from screenshot data
    print("\n" + "=" * 70)
    print("STEP 1: Create profile from screenshot data")
    print("=" * 70)

    profile = get_example_profile()
    print(f"Name: {profile.names[0].value}")
    print(f"Location: {profile.city}, {profile.state}")
    print(f"Current: {profile.current_title} at {profile.current_employer}")
    print(f"\nName variants for search:")
    for v in profile.names:
        print(f"  - {v.value} ({v.type}, conf={v.confidence})")

    # Step 2: Search FEC
    print("\n" + "=" * 70)
    print("STEP 2: Search FEC for federal contributions")
    print("=" * 70)

    federal, federal_audit = search_fec(profile, api_key)
    print(f"Found {len(federal)} federal contributions")

    successful = sum(1 for q in federal_audit if q.success)
    print(f"Queries: {len(federal_audit)} ({successful} successful)")

    if federal:
        total = sum(c.amount for c in federal)
        print(f"Total: ${total:,.0f}")
        print("\nTop 10 contributions:")
        for c in federal[:10]:
            print(f"  {c.date} | ${c.amount:>8,.0f} | {c.recipient[:40]} | conf={c.confidence}")

    # Step 3: Search nonprofits (includes Open990 officer search)
    print("\n" + "=" * 70)
    print("STEP 3: Search nonprofits (990 officer lookup)")
    print("=" * 70)

    boards, foundation, nonprofit_audit = search_nonprofits(profile)
    print(f"Found {len(boards)} board positions")

    for b in boards:
        print(f"  - {b.organization} ({b.source}, EIN: {b.ein or 'N/A'})")

    if foundation:
        print(f"\nFamily Foundation: {foundation.name}")
        print(f"  EIN: {foundation.ein}")
        if foundation.total_assets:
            print(f"  Assets: ${foundation.total_assets:,.0f}")

    # Step 4: Search state databases
    print("\n" + "=" * 70)
    print("STEP 4: Search state databases (CA, NY)")
    print("=" * 70)

    state, state_audit = search_state(profile)
    print(f"Found {len(state)} state contributions")

    # Step 5: Search local databases
    print("\n" + "=" * 70)
    print("STEP 5: Search local databases")
    print("=" * 70)

    local, local_audit = search_local(profile)
    print(f"Found {len(local)} local contributions")

    # Step 6: Generate dossier
    print("\n" + "=" * 70)
    print("STEP 6: Generate dossier")
    print("=" * 70)

    all_audit = federal_audit + state_audit + local_audit + nonprofit_audit

    dossier = generate_dossier(
        profile=profile,
        federal=federal,
        state=state,
        local=local,
        boards=boards,
        foundation=foundation,
        audit=all_audit,
    )

    # Save outputs
    md_path, json_path = save_outputs(dossier, "outputs")
    print(f"Saved markdown: {md_path}")
    print(f"Saved JSON: {json_path}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    federal_total = sum(c.amount for c in dossier.contributions_federal)
    state_total = sum(c.amount for c in dossier.contributions_state)
    local_total = sum(c.amount for c in dossier.contributions_local)

    print(f"Federal contributions: ${federal_total:,.0f} ({len(dossier.contributions_federal)} records)")
    print(f"State contributions:   ${state_total:,.0f} ({len(dossier.contributions_state)} records)")
    print(f"Local contributions:   ${local_total:,.0f} ({len(dossier.contributions_local)} records)")
    print(f"Board positions:       {len(dossier.boards)}")
    print(f"Queries executed:      {len(dossier.audit_queries)}")

    print("\n✅ Test complete! Check outputs/ directory for results.")

    return dossier


def test_custom_profile(
    full_name: str,
    linkedin_url: str,
    location: str,
    current_employer: str = None,
    current_title: str = None,
):
    """Test with a custom profile."""

    print(f"\nTesting with: {full_name}")

    profile = create_profile_from_manual_data(
        full_name=full_name,
        linkedin_url=linkedin_url,
        location=location,
        experience=[
            {"name": current_employer, "title": current_title}
        ] if current_employer else None,
    )

    api_key = os.getenv("FEC_API_KEY", "DEMO_KEY")

    # Quick FEC search
    federal, _ = search_fec(profile, api_key)
    print(f"Found {len(federal)} federal contributions")

    if federal:
        total = sum(c.amount for c in federal)
        print(f"Total: ${total:,.0f}")
        for c in federal[:5]:
            print(f"  {c.date} | ${c.amount:,.0f} | {c.recipient[:40]}")

    return federal


if __name__ == "__main__":
    # Run test with Alison Pincus data
    dossier = test_with_alison_pincus()

    # Optionally test with another name:
    # test_custom_profile(
    #     full_name="John Smith",
    #     linkedin_url="https://linkedin.com/in/johnsmith",
    #     location="San Francisco, CA",
    #     current_employer="Acme Corp",
    #     current_title="CEO",
    # )
