"""sam_gov_client.py — re-export of SamGovClient for the lookup path (m3.md Step 1.4).

The Protocol is frozen in clients.py (Foundation contract). This module re-exports
it so lookup-path code can import from here, matching the m3.md file layout, without
duplicating the definition.
"""
from app.workflow.clients import SamGovClient as SamGovClient  # noqa: F401
