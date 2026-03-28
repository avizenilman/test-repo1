"""
Synthesis module - assembles research results into dossiers and generates outputs.

Responsibilities:
1. Combine all search results into a unified FullDossier
2. Generate human-readable markdown reports
3. Save outputs as both markdown and JSON

The markdown output is designed to be:
- Scannable (summary stats at top)
- Detailed (full tables of contributions)
- Transparent (audit trail and confidence scores)
"""

import json
import os
import re
from datetime import datetime
from typing import Optional

from models import (
    FullDossier,
    PersonProfile,
    Contribution,
    BoardPosition,
    FamilyFoundation,
    AuditQuery,
    AuditSource,
)


def generate_dossier(
    profile: PersonProfile,
    federal: list[Contribution],
    state: list[Contribution],
    local: list[Contribution],
    boards: list[BoardPosition],
    foundation: Optional[FamilyFoundation],
    audit: list[AuditQuery],
    sources: Optional[list[AuditSource]] = None,
) -> FullDossier:
    """
    Assemble full dossier from all research components.

    Sorts contributions by date and deduplicates board positions.
    """
    # Sort contributions by date (most recent first)
    federal_sorted = sorted(federal, key=lambda x: x.date or "", reverse=True)
    state_sorted = sorted(state, key=lambda x: x.date or "", reverse=True)
    local_sorted = sorted(local, key=lambda x: x.date or "", reverse=True)

    # Deduplicate board positions by organization name
    seen_orgs = set()
    unique_boards = []
    for board in boards:
        org_key = board.organization.lower().strip()
        if org_key not in seen_orgs:
            seen_orgs.add(org_key)
            unique_boards.append(board)

    return FullDossier(
        profile=profile,
        contributions_federal=federal_sorted,
        contributions_state=state_sorted,
        contributions_local=local_sorted,
        boards=unique_boards,
        family_foundation=foundation,
        audit_queries=audit,
        audit_sources=sources or [],
        generated_at=datetime.now(),
    )


def dossier_to_markdown(dossier: FullDossier) -> str:
    """
    Convert dossier to human-readable markdown.

    Structure:
    1. Header with name and generation timestamp
    2. Profile summary
    3. LinkedIn bio and experience
    4. Federal contributions (with totals)
    5. State contributions
    6. Local contributions
    7. Board affiliations
    8. Family foundation (if found)
    9. Audit trail summary
    """
    p = dossier.profile
    name = p.names[0].value if p.names else "Unknown"

    # Calculate totals
    federal_total = sum(c.amount for c in dossier.contributions_federal)
    state_total = sum(c.amount for c in dossier.contributions_state)
    local_total = sum(c.amount for c in dossier.contributions_local)
    total_giving = federal_total + state_total + local_total

    # Start building markdown
    md_parts = []

    # Header
    md_parts.append(f"# {name} — Donor Research Dossier")
    md_parts.append(f"**Generated:** {dossier.generated_at.strftime('%Y-%m-%d %H:%M')}")
    md_parts.append("")

    # Executive Summary
    md_parts.append("## Executive Summary")
    md_parts.append(f"- **Total Political Giving:** ${total_giving:,.0f}")
    md_parts.append(f"  - Federal: ${federal_total:,.0f} ({len(dossier.contributions_federal)} contributions)")
    md_parts.append(f"  - State: ${state_total:,.0f} ({len(dossier.contributions_state)} contributions)")
    md_parts.append(f"  - Local: ${local_total:,.0f} ({len(dossier.contributions_local)} contributions)")
    md_parts.append(f"- **Board Positions:** {len(dossier.boards)}")
    if dossier.family_foundation:
        md_parts.append(f"- **Family Foundation:** {dossier.family_foundation.name}")
    md_parts.append("")

    # Profile Summary
    md_parts.append("## Profile Summary")
    md_parts.append(f"- **Name:** {name}")
    md_parts.append(f"- **Current Role:** {p.current_title or 'Unknown'} at {p.current_employer or 'Unknown'}")
    md_parts.append(f"- **Location:** {p.city or 'Unknown'}, {p.state or 'Unknown'}")
    md_parts.append(f"- **LinkedIn:** {p.linkedin.url}")

    if p.spouse:
        spouse_name = p.spouse.names[0].value if p.spouse.names else "Unknown"
        md_parts.append(f"- **Spouse:** {spouse_name}")
        if p.spouse.current_employer:
            md_parts.append(f"  - Role: {p.spouse.current_title or 'N/A'} at {p.spouse.current_employer}")

    md_parts.append("")

    # LinkedIn Bio
    if p.linkedin.about:
        md_parts.append("## LinkedIn Bio")
        md_parts.append(p.linkedin.about)
        md_parts.append("")

    # Employment History
    if p.linkedin.experience:
        md_parts.append("## Employment History")
        for exp in p.linkedin.experience:
            years = f"{exp.start_year or '?'}-{exp.end_year or 'Present'}"
            md_parts.append(f"- **{exp.title or 'Role'}** at {exp.name} ({years})")
        md_parts.append("")

    # Education
    if p.linkedin.education:
        md_parts.append("## Education")
        for edu in p.linkedin.education:
            md_parts.append(f"- {edu}")
        md_parts.append("")

    # Federal Contributions
    md_parts.append("## Federal Contributions (FEC)")
    md_parts.append(f"**Total:** ${federal_total:,.0f}")
    md_parts.append("")

    if dossier.contributions_federal:
        md_parts.append("| Date | Amount | Recipient | Type | Confidence |")
        md_parts.append("|------|--------|-----------|------|------------|")

        # Show top 50 contributions
        for c in dossier.contributions_federal[:50]:
            recipient_display = c.recipient[:45] + "..." if len(c.recipient) > 45 else c.recipient
            confidence_display = f"{c.confidence:.0%}"
            if c.confidence < 0.5:
                confidence_display += " ⚠️"  # Flag low confidence
            md_parts.append(
                f"| {c.date} | ${c.amount:,.0f} | {recipient_display} | {c.recipient_type or 'N/A'} | {confidence_display} |"
            )

        if len(dossier.contributions_federal) > 50:
            md_parts.append(f"\n*Showing 50 of {len(dossier.contributions_federal)} contributions*")
    else:
        md_parts.append("*No federal contributions found*")

    md_parts.append("")

    # State Contributions
    md_parts.append("## State Contributions")
    md_parts.append(f"**Total:** ${state_total:,.0f}")
    md_parts.append("")

    if dossier.contributions_state:
        md_parts.append("| Date | Amount | Recipient | Source | Confidence |")
        md_parts.append("|------|--------|-----------|--------|------------|")

        for c in dossier.contributions_state[:30]:
            recipient_display = c.recipient[:40] + "..." if len(c.recipient) > 40 else c.recipient
            confidence_display = f"{c.confidence:.0%}"
            if c.confidence < 0.5:
                confidence_display += " ⚠️"
            md_parts.append(
                f"| {c.date} | ${c.amount:,.0f} | {recipient_display} | {c.source} | {confidence_display} |"
            )

        if len(dossier.contributions_state) > 30:
            md_parts.append(f"\n*Showing 30 of {len(dossier.contributions_state)} contributions*")
    else:
        md_parts.append("*No state contributions found*")

    md_parts.append("")

    # Local Contributions
    if dossier.contributions_local:
        md_parts.append("## Local Contributions")
        md_parts.append(f"**Total:** ${local_total:,.0f}")
        md_parts.append("")

        md_parts.append("| Date | Amount | Recipient | Jurisdiction | Confidence |")
        md_parts.append("|------|--------|-----------|--------------|------------|")

        for c in dossier.contributions_local[:20]:
            recipient_display = c.recipient[:40] + "..." if len(c.recipient) > 40 else c.recipient
            confidence_display = f"{c.confidence:.0%}"
            if c.confidence < 0.5:
                confidence_display += " ⚠️"
            md_parts.append(
                f"| {c.date} | ${c.amount:,.0f} | {recipient_display} | {c.source} | {confidence_display} |"
            )

        if len(dossier.contributions_local) > 20:
            md_parts.append(f"\n*Showing 20 of {len(dossier.contributions_local)} contributions*")

        md_parts.append("")

    # Board Affiliations
    if dossier.boards:
        md_parts.append("## Board Affiliations")
        md_parts.append("")
        md_parts.append("| Organization | Role | Source | EIN |")
        md_parts.append("|--------------|------|--------|-----|")

        for b in dossier.boards:
            md_parts.append(
                f"| {b.organization} | {b.role or 'N/A'} | {b.source} | {b.ein or 'N/A'} |"
            )

        md_parts.append("")

    # Family Foundation
    if dossier.family_foundation:
        f = dossier.family_foundation
        md_parts.append("## Family Foundation")
        md_parts.append(f"- **Name:** {f.name}")
        md_parts.append(f"- **EIN:** {f.ein}")
        if f.total_assets:
            md_parts.append(f"- **Total Assets:** ${f.total_assets:,.0f} ({f.filing_year})")
        if f.annual_giving:
            md_parts.append(f"- **Annual Giving:** ${f.annual_giving:,.0f}")
        if f.top_grantees:
            md_parts.append("- **Top Grantees:**")
            for grantee in f.top_grantees[:10]:
                md_parts.append(f"  - {grantee}")
        md_parts.append("")

    # Audit Trail
    successful_queries = sum(1 for q in dossier.audit_queries if q.success)
    failed_queries = len(dossier.audit_queries) - successful_queries

    all_contributions = (
        dossier.contributions_federal
        + dossier.contributions_state
        + dossier.contributions_local
    )
    low_confidence = sum(1 for c in all_contributions if c.confidence < 0.5)
    high_confidence = sum(1 for c in all_contributions if c.confidence >= 0.8)

    md_parts.append("## Audit Trail")
    md_parts.append(f"- **Queries Executed:** {len(dossier.audit_queries)} ({successful_queries} successful, {failed_queries} failed)")
    md_parts.append(f"- **High Confidence Matches (≥80%):** {high_confidence}")
    md_parts.append(f"- **Low Confidence Matches (<50%, needs review):** {low_confidence}")
    md_parts.append("- **Sources Consulted:** FEC, CA Secretary of State, NY Board of Elections, ProPublica Nonprofits")
    md_parts.append("")

    # List failed queries for debugging
    failed = [q for q in dossier.audit_queries if not q.success]
    if failed:
        md_parts.append("### Failed Queries")
        for q in failed[:10]:  # Limit to 10
            md_parts.append(f"- `{q.api}:{q.endpoint}` - {q.error}")
        if len(failed) > 10:
            md_parts.append(f"*...and {len(failed) - 10} more*")
        md_parts.append("")

    # Footer
    md_parts.append("---")
    md_parts.append("*This dossier was generated automatically. Low-confidence matches should be manually verified.*")

    return "\n".join(md_parts)


def save_outputs(dossier: FullDossier, output_dir: str) -> tuple[str, str]:
    """
    Save markdown and JSON outputs.

    File naming: {lastname}_{firstname}_{YYYYMMDD}.{ext}

    Returns (markdown_path, json_path) tuple.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Generate filename
    name = dossier.profile.names[0].value if dossier.profile.names else "unknown"
    slug = _make_filename_slug(name)
    timestamp = dossier.generated_at.strftime("%Y%m%d")

    # Save markdown
    md_filename = f"{slug}_{timestamp}.md"
    md_path = os.path.join(output_dir, md_filename)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(dossier_to_markdown(dossier))

    # Save JSON
    json_filename = f"{slug}_{timestamp}.json"
    json_path = os.path.join(output_dir, json_filename)
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(dossier.model_dump_json(indent=2))

    return md_path, json_path


def _make_filename_slug(name: str) -> str:
    """
    Convert name to filesystem-safe slug.

    "John Doe" -> "doe_john"
    "Mary Jane Smith" -> "smith_mary_jane"
    """
    # Lowercase and split
    parts = name.lower().split()

    if len(parts) >= 2:
        # Last name first, then remaining names
        slug = f"{parts[-1]}_{'_'.join(parts[:-1])}"
    else:
        slug = parts[0] if parts else "unknown"

    # Remove non-alphanumeric characters
    slug = re.sub(r"[^a-z0-9_]", "", slug)

    # Collapse multiple underscores
    slug = re.sub(r"_+", "_", slug)

    return slug
