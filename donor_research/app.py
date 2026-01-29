"""
Donor Research Tool - Streamlit Interface

A batch research tool for generating political donation dossiers.
Users paste LinkedIn URLs, click "Run Research," and get comprehensive reports.

Usage:
    1. Create .env file with FEC_API_KEY=your_key
    2. pip install -r requirements.txt
    3. streamlit run app.py
"""

import os
import sys
import streamlit as st
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(
    page_title="Donor Research Tool",
    page_icon="🔍",
    layout="wide",
)

# Custom CSS for better table display
st.markdown("""
<style>
    .stDataEditor {
        font-size: 14px;
    }
    .stMetric {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 5px;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.title("🔍 Donor Research Tool")
st.markdown("""
Research political donations from federal, state, and local sources.
Paste LinkedIn URLs below and click **Run Research** to generate dossiers.
""")

# Sidebar for settings
with st.sidebar:
    st.header("Settings")

    # API key status
    api_key = os.getenv("FEC_API_KEY")
    if api_key:
        st.success("✅ FEC API Key loaded")
    else:
        st.error("❌ FEC API Key not found")
        st.markdown("""
        Add your FEC API key to `.env`:
        ```
        FEC_API_KEY=your_key_here
        ```
        Get a free key at [api.open.fec.gov](https://api.open.fec.gov/developers/)
        """)

    st.divider()

    # Output directory
    output_dir = st.text_input(
        "Output Directory",
        value="outputs",
        help="Directory where dossiers will be saved"
    )

    # Confidence threshold
    confidence_threshold = st.slider(
        "Confidence Threshold",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        step=0.1,
        help="Minimum confidence score to include a contribution"
    )

    st.divider()
    st.markdown("### About")
    st.markdown("""
    This tool searches:
    - **Federal:** FEC (2008-present)
    - **State:** CA & NY databases
    - **Local:** SF, LA, NYC, Oakland
    - **Nonprofits:** ProPublica 990s
    """)


# Initialize session state for the input table
if "donors" not in st.session_state:
    st.session_state.donors = pd.DataFrame({
        "Person LinkedIn": [""],
        "Spouse LinkedIn": [""],
    })

# Main content area
st.subheader("Enter LinkedIn URLs")
st.caption("Add rows using the '+' button below the table. Paste LinkedIn profile URLs for each donor.")

# Editable dataframe
edited_df = st.data_editor(
    st.session_state.donors,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Person LinkedIn": st.column_config.TextColumn(
            "Person LinkedIn URL",
            width="large",
            help="e.g., https://linkedin.com/in/johndoe",
        ),
        "Spouse LinkedIn": st.column_config.TextColumn(
            "Spouse LinkedIn URL (optional)",
            width="large",
            help="Leave empty if no spouse or unknown",
        ),
    },
    hide_index=True,
)

# Update session state
st.session_state.donors = edited_df

# Validation
def validate_linkedin_url(url: str) -> bool:
    """Check if URL looks like a LinkedIn profile URL."""
    if not url or not url.strip():
        return False
    url_lower = url.lower().strip()
    return "linkedin.com/in/" in url_lower or "linkedin.com/pub/" in url_lower


def get_valid_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to rows with valid LinkedIn URLs."""
    valid_mask = df["Person LinkedIn"].apply(
        lambda x: validate_linkedin_url(str(x)) if pd.notna(x) else False
    )
    return df[valid_mask]


# Count valid rows
valid_rows = get_valid_rows(edited_df)
total_rows = len(edited_df[edited_df["Person LinkedIn"].str.strip() != ""])

if total_rows > 0:
    st.info(f"📊 {len(valid_rows)} of {total_rows} rows have valid LinkedIn URLs")

# Run button
col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    run_button = st.button(
        "🔍 Run Research",
        type="primary",
        disabled=not api_key or valid_rows.empty,
    )
with col2:
    clear_button = st.button("🗑️ Clear All")
    if clear_button:
        st.session_state.donors = pd.DataFrame({
            "Person LinkedIn": [""],
            "Spouse LinkedIn": [""],
        })
        st.rerun()

# Run the research pipeline
if run_button:
    if not api_key:
        st.error("❌ Cannot proceed without FEC_API_KEY. Add it to your .env file.")
    elif valid_rows.empty:
        st.warning("⚠️ No valid LinkedIn URLs entered. Please add at least one.")
    else:
        # Import modules here to avoid slow startup
        from enrichment import extract_profile
        from fec_search import search_fec
        from state_search import search_state
        from local_search import search_local
        from nonprofit_search import search_nonprofits
        from synthesis import generate_dossier, save_outputs, dossier_to_markdown

        # Progress tracking
        progress_bar = st.progress(0)
        status_text = st.empty()
        results_container = st.container()

        results = []
        errors = []

        for idx, (_, row) in enumerate(valid_rows.iterrows()):
            person_url = str(row["Person LinkedIn"]).strip()
            spouse_url = str(row["Spouse LinkedIn"]).strip() if pd.notna(row["Spouse LinkedIn"]) else None

            # Update status
            progress = (idx) / len(valid_rows)
            progress_bar.progress(progress)
            status_text.text(f"Processing {idx + 1}/{len(valid_rows)}: {person_url[:50]}...")

            try:
                # Step 1: Extract profiles
                status_text.text(f"[{idx + 1}/{len(valid_rows)}] Extracting LinkedIn profile...")
                person_profile = extract_profile(person_url)

                if spouse_url and validate_linkedin_url(spouse_url):
                    spouse_profile = extract_profile(spouse_url)
                    person_profile.spouse = spouse_profile

                # Step 2: Search FEC
                status_text.text(f"[{idx + 1}/{len(valid_rows)}] Searching FEC database...")
                federal, federal_audit = search_fec(person_profile, api_key)

                # Step 3: Search state databases
                status_text.text(f"[{idx + 1}/{len(valid_rows)}] Searching state databases...")
                state, state_audit = search_state(person_profile)

                # Step 4: Search local databases
                status_text.text(f"[{idx + 1}/{len(valid_rows)}] Searching local databases...")
                local, local_audit = search_local(person_profile)

                # Step 5: Search nonprofits
                status_text.text(f"[{idx + 1}/{len(valid_rows)}] Searching nonprofit databases...")
                boards, foundation, nonprofit_audit = search_nonprofits(person_profile)

                # Combine audit trails
                all_audit = federal_audit + state_audit + local_audit + nonprofit_audit

                # Apply confidence filter
                federal = [c for c in federal if c.confidence >= confidence_threshold]
                state = [c for c in state if c.confidence >= confidence_threshold]
                local = [c for c in local if c.confidence >= confidence_threshold]

                # Step 6: Generate dossier
                status_text.text(f"[{idx + 1}/{len(valid_rows)}] Generating dossier...")
                dossier = generate_dossier(
                    profile=person_profile,
                    federal=federal,
                    state=state,
                    local=local,
                    boards=boards,
                    foundation=foundation,
                    audit=all_audit,
                )

                # Step 7: Save outputs
                md_path, json_path = save_outputs(dossier, output_dir)

                results.append({
                    "name": person_profile.names[0].value if person_profile.names else "Unknown",
                    "md_path": md_path,
                    "json_path": json_path,
                    "dossier": dossier,
                    "url": person_url,
                })

            except Exception as e:
                errors.append({
                    "url": person_url,
                    "error": str(e),
                })
                st.error(f"Error processing {person_url}: {e}")

        # Complete
        progress_bar.progress(1.0)
        status_text.text("✅ Processing complete!")

        # Summary
        st.success(f"✅ Completed {len(results)} dossiers" + (f", {len(errors)} errors" if errors else ""))

        # Display results
        if results:
            st.subheader("Results")

            for r in results:
                dossier = r["dossier"]
                name = r["name"]

                # Calculate stats
                federal_total = sum(c.amount for c in dossier.contributions_federal)
                state_total = sum(c.amount for c in dossier.contributions_state)
                local_total = sum(c.amount for c in dossier.contributions_local)
                total = federal_total + state_total + local_total

                with st.expander(f"📄 {name} — ${total:,.0f} total", expanded=True):
                    # Metrics row
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Federal", f"${federal_total:,.0f}", f"{len(dossier.contributions_federal)} records")
                    with col2:
                        st.metric("State", f"${state_total:,.0f}", f"{len(dossier.contributions_state)} records")
                    with col3:
                        st.metric("Local", f"${local_total:,.0f}", f"{len(dossier.contributions_local)} records")
                    with col4:
                        st.metric("Boards", len(dossier.boards))

                    # Foundation info
                    if dossier.family_foundation:
                        st.info(f"🏛️ **Family Foundation:** {dossier.family_foundation.name} (EIN: {dossier.family_foundation.ein})")

                    # Download buttons
                    col1, col2 = st.columns(2)
                    with col1:
                        with open(r["md_path"], "r", encoding="utf-8") as f:
                            st.download_button(
                                f"📄 Download Markdown",
                                f.read(),
                                file_name=os.path.basename(r["md_path"]),
                                mime="text/markdown",
                            )
                    with col2:
                        with open(r["json_path"], "r", encoding="utf-8") as f:
                            st.download_button(
                                f"📊 Download JSON",
                                f.read(),
                                file_name=os.path.basename(r["json_path"]),
                                mime="application/json",
                            )

                    # Preview markdown
                    with st.expander("Preview Dossier"):
                        st.markdown(dossier_to_markdown(dossier))

        # Show errors
        if errors:
            st.subheader("Errors")
            for err in errors:
                st.error(f"**{err['url']}:** {err['error']}")


# Footer
st.divider()
st.caption("""
**Data Sources:** FEC, CA Secretary of State, NY Board of Elections, SF Ethics Commission, LA Ethics Commission, NYC Campaign Finance Board, ProPublica Nonprofit Explorer

**Note:** Confidence scores indicate match certainty. Low-confidence matches (marked with ⚠️) should be manually verified.
""")
