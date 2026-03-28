#@title Donor Research Tool - Single File for Colab/Replit
#@markdown **Instructions:**
#@markdown 1. Get free FEC API key at https://api.open.fec.gov/developers/
#@markdown 2. Paste your key below
#@markdown 3. Run all cells

# ============================================================
# CONFIGURATION - Enter your API key here
# ============================================================
FEC_API_KEY = ""  #@param {type:"string"}

# If running in Colab and key is empty, prompt for it
if not FEC_API_KEY:
    try:
        from google.colab import userdata
        FEC_API_KEY = userdata.get('FEC_API_KEY')
    except:
        pass

if not FEC_API_KEY:
    FEC_API_KEY = input("Enter your FEC API key (get free at api.open.fec.gov): ")

# ============================================================
# INSTALL DEPENDENCIES
# ============================================================
import subprocess
subprocess.run(["pip", "install", "-q", "requests", "pydantic"], check=True)

# ============================================================
# IMPORTS
# ============================================================
import re
import time
import requests
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

print("✅ Dependencies loaded")

# ============================================================
# MODELS
# ============================================================
class NameVariant(BaseModel):
    value: str
    type: str
    confidence: float = 1.0

class Employer(BaseModel):
    name: str
    title: Optional[str] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None

class LinkedInProfile(BaseModel):
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
    canonical_id: str
    names: list[NameVariant]
    current_employer: Optional[str] = None
    current_title: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    linkedin: LinkedInProfile
    spouse: Optional["PersonProfile"] = None

class Contribution(BaseModel):
    date: str
    amount: float
    recipient: str
    recipient_type: Optional[str] = None
    source: str
    source_id: Optional[str] = None
    confidence: float
    match_reason: str

class BoardPosition(BaseModel):
    organization: str
    role: Optional[str] = None
    source: str
    ein: Optional[str] = None
    years: Optional[str] = None

print("✅ Models defined")

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def generate_name_variants(full_name: str) -> list[NameVariant]:
    """Generate name variants for FEC matching."""
    variants = []
    parts = full_name.split()

    variants.append(NameVariant(value=full_name, type="current", confidence=1.0))

    if len(parts) >= 2:
        variants.append(NameVariant(value=f"{parts[0]} {parts[-1]}", type="short", confidence=0.95))

    if len(parts) == 3:
        variants.append(NameVariant(value=f"{parts[0]} {parts[1][0]}. {parts[2]}", type="middle_initial", confidence=0.9))
        variants.append(NameVariant(value=f"{parts[0]} {parts[1]}", type="possible_maiden", confidence=0.7))

    variants.append(NameVariant(value=full_name.upper(), type="uppercase", confidence=1.0))

    return variants

def parse_location(location: str) -> tuple[Optional[str], Optional[str]]:
    """Extract city and state from location string."""
    if not location:
        return None, None

    location = re.sub(r",?\s*United States\s*$", "", location, flags=re.IGNORECASE)
    location = re.sub(r",?\s*USA\s*$", "", location, flags=re.IGNORECASE).strip()

    state_map = {
        "california": "CA", "new york": "NY", "texas": "TX", "florida": "FL",
        "illinois": "IL", "pennsylvania": "PA", "ohio": "OH", "georgia": "GA",
        "massachusetts": "MA", "washington": "WA", "colorado": "CO", "arizona": "AZ",
    }

    if "," in location:
        parts = [p.strip() for p in location.split(",")]
        city = parts[0]
        state_part = parts[-1].lower()

        if state_part in state_map:
            return city, state_map[state_part]
        if state_part.upper() in state_map.values():
            return city, state_part.upper()

        return city, None

    return location, None

# ============================================================
# CREATE PROFILE FROM SCREENSHOT DATA
# ============================================================
def create_profile(
    full_name: str,
    linkedin_url: str,
    location: str,
    headline: str = None,
    about: str = None,
    experience: list = None,
    board_affiliations: list = None,
) -> PersonProfile:
    """Create a profile from manually extracted LinkedIn data."""

    employers = []
    current_employer = None
    current_title = None

    for exp in (experience or []):
        employers.append(Employer(**exp))
        if not exp.get("end_year") and not current_employer:
            current_employer = exp.get("name")
            current_title = exp.get("title")

    city, state = parse_location(location)
    name_variants = generate_name_variants(full_name)

    linkedin = LinkedInProfile(
        url=linkedin_url,
        full_name=full_name,
        headline=headline,
        location=location,
        about=about,
        experience=employers,
        board_affiliations=board_affiliations or [],
        fetched_at=datetime.now(),
    )

    name_slug = full_name.lower().replace(" ", "-")
    emp_slug = (current_employer or "unknown").lower().replace(" ", "-")

    return PersonProfile(
        canonical_id=f"{name_slug}-{emp_slug}",
        names=name_variants,
        current_employer=current_employer,
        current_title=current_title,
        city=city,
        state=state,
        linkedin=linkedin,
    )

# ============================================================
# FEC SEARCH
# ============================================================
FEC_BASE = "https://api.open.fec.gov/v1"
CYCLES = [2008, 2010, 2012, 2014, 2016, 2018, 2020, 2022, 2024]

def search_fec(profile: PersonProfile, api_key: str) -> list[Contribution]:
    """Search FEC for federal contributions."""
    contributions = []
    seen_ids = set()

    for name_var in profile.names:
        if name_var.confidence < 0.7:
            continue

        name = name_var.value

        # Build queries with decreasing specificity
        queries = []

        if profile.current_employer and profile.state:
            queries.append({
                "contributor_name": name,
                "contributor_employer": profile.current_employer,
                "contributor_state": profile.state,
            })

        if profile.city and profile.state:
            queries.append({
                "contributor_name": name,
                "contributor_city": profile.city,
                "contributor_state": profile.state,
            })

        if profile.state:
            queries.append({
                "contributor_name": name,
                "contributor_state": profile.state,
            })

        for query in queries:
            for cycle in CYCLES:
                params = {
                    **query,
                    "api_key": api_key,
                    "two_year_transaction_period": cycle,
                    "per_page": 100,
                    "sort": "-contribution_receipt_date",
                }

                try:
                    r = requests.get(f"{FEC_BASE}/schedules/schedule_a/", params=params, timeout=30)
                    if r.status_code == 200:
                        data = r.json()
                        for result in data.get("results", []):
                            tx_id = result.get("transaction_id") or result.get("sub_id")
                            if tx_id in seen_ids:
                                continue
                            seen_ids.add(tx_id)

                            committee = result.get("committee") or {}
                            contributions.append(Contribution(
                                date=result.get("contribution_receipt_date", ""),
                                amount=float(result.get("contribution_receipt_amount", 0)),
                                recipient=committee.get("name", "Unknown"),
                                recipient_type=committee.get("committee_type_full"),
                                source="fec",
                                source_id=str(tx_id),
                                confidence=0.9 if len(query) > 2 else 0.7,
                                match_reason=f"{name_var.type}_name",
                            ))
                    elif r.status_code == 429:
                        print("  Rate limited, waiting...")
                        time.sleep(2)
                except Exception as e:
                    print(f"  Error: {e}")

                time.sleep(0.1)  # Rate limit courtesy

    return sorted(contributions, key=lambda x: x.date, reverse=True)

# ============================================================
# PROPUBLICA NONPROFIT SEARCH
# ============================================================
PROPUBLICA_BASE = "https://projects.propublica.org/nonprofits/api/v2"

def search_nonprofits(profile: PersonProfile) -> list[BoardPosition]:
    """Search ProPublica for family foundations."""
    boards = []

    # Add LinkedIn boards
    for b in profile.linkedin.board_affiliations:
        boards.append(BoardPosition(organization=b, source="linkedin"))

    # Search for family foundation
    last_name = profile.names[0].value.split()[-1]
    searches = [f"{last_name} Family Foundation", f"{last_name} Foundation"]

    for term in searches:
        try:
            r = requests.get(f"{PROPUBLICA_BASE}/search.json", params={"q": term}, timeout=30)
            if r.status_code == 200:
                for org in r.json().get("organizations", [])[:5]:
                    if last_name.lower() in org.get("name", "").lower():
                        boards.append(BoardPosition(
                            organization=org.get("name"),
                            source="990",
                            ein=str(org.get("ein")),
                        ))
        except:
            pass
        time.sleep(0.3)

    return boards

# ============================================================
# EXAMPLE: ALISON GELB PINCUS (from screenshots)
# ============================================================
ALISON_PINCUS = {
    "full_name": "Alison Gelb Pincus",
    "linkedin_url": "https://linkedin.com/in/alisonpincus",
    "headline": "Social Impact Entrepreneur & Investor",
    "location": "San Francisco, California, United States",
    "about": "I'm a people-first business leader, consumer expert, angel investor and board director with +20 years' experience. Best known for co-founding One Kings Lane (acquired by Bed Bath & Beyond 2016).",
    "experience": [
        {"name": "Allies for Allies", "title": "Founder, Executive Director", "start_year": 2023},
        {"name": "Short List Capital", "title": "Partner", "start_year": 2017},
        {"name": "IfOnly", "title": "Board Director", "start_year": 2014, "end_year": 2019},
        {"name": "One Kings Lane", "title": "Co-Founder", "start_year": 2008, "end_year": 2016},
    ],
    "board_affiliations": [
        "Enterprise for Youth - Board Director",
        "remake.world - Leadership Council",
        "Allies for Allies - 501(c)(3)",
    ],
}

# ============================================================
# RUN THE SEARCH
# ============================================================
print("\n" + "="*60)
print("DONOR RESEARCH: Alison Gelb Pincus")
print("="*60)

# Create profile
profile = create_profile(**ALISON_PINCUS)
print(f"\n📋 Profile: {profile.names[0].value}")
print(f"   Location: {profile.city}, {profile.state}")
print(f"   Current: {profile.current_title} at {profile.current_employer}")
print(f"\n   Name variants for search:")
for v in profile.names:
    print(f"   - {v.value} ({v.type})")

# Search FEC
print("\n" + "="*60)
print("🔍 Searching FEC (this may take a minute)...")
print("="*60)

contributions = search_fec(profile, FEC_API_KEY)

print(f"\n✅ Found {len(contributions)} federal contributions")

if contributions:
    total = sum(c.amount for c in contributions)
    print(f"   Total: ${total:,.0f}")

    print("\n   Top contributions:")
    print("   " + "-"*70)
    for c in contributions[:15]:
        print(f"   {c.date} | ${c.amount:>8,.0f} | {c.recipient[:40]}")

    if len(contributions) > 15:
        print(f"   ... and {len(contributions) - 15} more")

# Search nonprofits
print("\n" + "="*60)
print("🏛️ Searching nonprofits...")
print("="*60)

boards = search_nonprofits(profile)
print(f"\n✅ Found {len(boards)} board/nonprofit affiliations")
for b in boards:
    print(f"   - {b.organization} ({b.source})")

# Summary
print("\n" + "="*60)
print("📊 SUMMARY")
print("="*60)
print(f"Federal contributions: ${sum(c.amount for c in contributions):,.0f} ({len(contributions)} records)")
print(f"Board positions: {len(boards)}")
print("\n✅ Done!")

# ============================================================
# TO TEST YOUR OWN PERSON - Uncomment and edit below:
# ============================================================
# my_profile = create_profile(
#     full_name="John Smith",
#     linkedin_url="https://linkedin.com/in/johnsmith",
#     location="New York, NY",
#     experience=[{"name": "Acme Corp", "title": "CEO", "start_year": 2015}],
# )
# my_contributions = search_fec(my_profile, FEC_API_KEY)
# print(f"Found {len(my_contributions)} contributions for John Smith")
