"""
Manual profile entry from LinkedIn screenshots.

When you can't scrape LinkedIn directly, you can:
1. Take screenshots of the profile
2. Extract the data manually or via OCR
3. Feed it into this function to create a PersonProfile

This module provides utilities for creating profiles from manually
extracted data, which then feeds into the rest of the research pipeline.
"""

from datetime import datetime
from typing import Optional

from models import (
    PersonProfile,
    LinkedInProfile,
    NameVariant,
    Employer,
)
from enrichment import _generate_name_variants, _parse_location, _make_canonical_id


def create_profile_from_manual_data(
    full_name: str,
    linkedin_url: str,
    headline: Optional[str] = None,
    location: Optional[str] = None,
    about: Optional[str] = None,
    experience: Optional[list[dict]] = None,
    education: Optional[list[str]] = None,
    board_affiliations: Optional[list[str]] = None,
) -> PersonProfile:
    """
    Create a PersonProfile from manually extracted LinkedIn data.

    Args:
        full_name: Full name as shown on LinkedIn
        linkedin_url: LinkedIn profile URL
        headline: Professional headline
        location: Location string (e.g., "San Francisco, California")
        about: About/bio section text
        experience: List of dicts with keys: name, title, start_year, end_year
        education: List of education strings
        board_affiliations: List of board/volunteer positions

    Returns:
        PersonProfile ready for research pipeline

    Example:
        profile = create_profile_from_manual_data(
            full_name="Alison Gelb Pincus",
            linkedin_url="https://linkedin.com/in/alisonpincus",
            headline="Social Impact Entrepreneur & Investor",
            location="San Francisco, California",
            experience=[
                {"name": "Short List Capital", "title": "Partner", "start_year": 2017},
                {"name": "One Kings Lane", "title": "Co-Founder", "start_year": 2008, "end_year": 2016},
            ],
            board_affiliations=["Enterprise for Youth", "IfOnly"],
        )
    """
    # Parse experience into Employer objects
    employers = []
    current_employer = None
    current_title = None

    if experience:
        for exp in experience:
            employer = Employer(
                name=exp.get("name", "Unknown"),
                title=exp.get("title"),
                start_year=exp.get("start_year"),
                end_year=exp.get("end_year"),
            )
            employers.append(employer)

            # First current role (no end_year) becomes the current employer
            if not exp.get("end_year") and not current_employer:
                current_employer = exp.get("name")
                current_title = exp.get("title")

    # Generate name variants
    name_variants = _generate_name_variants(full_name)

    # Also add maiden name variant if middle name looks like maiden
    # (common pattern: FirstName MaidenName MarriedName)
    parts = full_name.split()
    if len(parts) == 3:
        # Could be "First Maiden Married" - add "First Maiden" as variant
        maiden_variant = f"{parts[0]} {parts[1]}"
        name_variants.append(
            NameVariant(value=maiden_variant, type="possible_maiden", confidence=0.7)
        )

    # Parse location
    city, state = _parse_location(location or "")

    # Build LinkedInProfile
    linkedin_profile = LinkedInProfile(
        url=linkedin_url,
        full_name=full_name,
        headline=headline,
        location=location,
        about=about,
        experience=employers,
        education=education or [],
        board_affiliations=board_affiliations or [],
        raw_text=None,
        fetched_at=datetime.now(),
    )

    # Generate canonical ID
    canonical_id = _make_canonical_id(full_name, current_employer)

    return PersonProfile(
        canonical_id=canonical_id,
        names=name_variants,
        current_employer=current_employer,
        current_title=current_title,
        city=city,
        state=state,
        linkedin=linkedin_profile,
    )


# Example usage with Alison Gelb Pincus data from screenshots
EXAMPLE_PROFILE = {
    "full_name": "Alison Gelb Pincus",
    "linkedin_url": "https://linkedin.com/in/alisonpincus",
    "headline": "Social Impact Entrepreneur & Investor",
    "location": "San Francisco, California, United States",
    "about": """I'm a people-first business leader, consumer expert, angel investor and board director with +20 years' experience building and scaling organizations, creating brand equity, and developing high potential talent across eCommerce/mCommerce, lifestyle/wellness and nonprofit spaces. Business Development is in my bones, but I'm equally passionate about all arenas of company building. I'm also fiercely committed to helping socially and environmentally conscious organizations make the greatest impact they can. I'm in my element when working with bright, creative and diverse teams to deliver groundbreaking solutions.

I'm probably best known for co-founding One Kings Lane which was acquired by Bed, Bath and Beyond in 2016.""",
    "experience": [
        {
            "name": "Allies for Allies",
            "title": "Founder, Executive Director, Board Member",
            "start_year": 2023,
            "end_year": None,
        },
        {
            "name": "Short List Capital",
            "title": "Partner",
            "start_year": 2017,
            "end_year": None,
        },
        {
            "name": "IfOnly",
            "title": "Board Director",
            "start_year": 2014,
            "end_year": 2019,
        },
        {
            "name": "One Kings Lane",
            "title": "Co-Founder",
            "start_year": 2008,
            "end_year": 2016,
        },
        {
            "name": "One Kings Lane",
            "title": "Board Director",
            "start_year": 2009,
            "end_year": 2016,
        },
        {
            "name": "Hachette Filipacchi Media U.S., Inc.",
            "title": "Director of Business Development",
            "start_year": 2005,
            "end_year": 2007,
        },
    ],
    "education": [
        "UCLA Anderson School of Management - MBA, Entrepreneurship",
        "UC Berkeley, Rausser College of Natural Resources - BS, Conservation and Resource Studies",
    ],
    "board_affiliations": [
        "Enterprise for Youth - Board Director (2018-present)",
        "remake.world - Leadership Council (2020-present)",
        "Allies for Allies - 501(c)(3) Board Member",
    ],
}


def get_example_profile() -> PersonProfile:
    """Return the example profile from screenshots for testing."""
    return create_profile_from_manual_data(**EXAMPLE_PROFILE)


if __name__ == "__main__":
    # Demo: create profile and print summary
    profile = get_example_profile()

    print("=" * 60)
    print("PROFILE CREATED FROM SCREENSHOT DATA")
    print("=" * 60)
    print(f"Name: {profile.names[0].value}")
    print(f"Canonical ID: {profile.canonical_id}")
    print(f"Location: {profile.city}, {profile.state}")
    print(f"Current: {profile.current_title} at {profile.current_employer}")
    print()
    print("Name variants for FEC search:")
    for v in profile.names:
        print(f"  - {v.value} ({v.type}, confidence: {v.confidence})")
    print()
    print("Experience:")
    for exp in profile.linkedin.experience:
        years = f"{exp.start_year or '?'}-{exp.end_year or 'Present'}"
        print(f"  - {exp.title} at {exp.name} ({years})")
    print()
    print("Board affiliations:")
    for board in profile.linkedin.board_affiliations:
        print(f"  - {board}")
