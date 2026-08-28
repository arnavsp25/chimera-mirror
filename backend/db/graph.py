"""
backend/db/graph.py

Defines and manages the `graph_nodes` / `graph_edges` tables described in
02_ARCHITECTURE.md §4. These didn't exist anywhere in the repo yet (no
router, no model, no schema file for them), so this file creates them.

Two edge_type families share the same table (per the architecture doc):
  - Blast-radius edges:      'targeted' | 'lateral_movement' | 'redirected_to'
  - Decision-provenance edges: 'made' | 'led_to' | 'based_on'

Feature 16 (the chat interface) only READS from these tables — it queries
whatever provenance edges exist for an incident and answers questions
grounded in that data. Populating them with real agent decisions is a
separate concern (PRD feature #12), so this file also ships a small demo
seeder (see scripts/seed_demo_graph.py) so the chat feature is testable
and demoable on its own before that integration happens.

Uses the same db helpers already in backend/db/postgres.py
(execute_query, fetch_all, fetch_one) rather than introducing a new
DB access pattern.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from backend.db.postgres import engine, execute_query, fetch_all

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS graph_nodes (
    id          SERIAL PRIMARY KEY,
    node_type   TEXT NOT NULL,      -- 'ip' | 'host' | 'decoy' | 'agent' | 'decision' | 'intel_source'
    label       TEXT NOT NULL,
    incident_id INTEGER NOT NULL,
    metadata    JSONB DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS graph_edges (
    id          SERIAL PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target_id   INTEGER NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    edge_type   TEXT NOT NULL,      -- 'targeted' | 'lateral_movement' | 'redirected_to' | 'made' | 'led_to' | 'based_on'
    incident_id INTEGER NOT NULL,
    metadata    JSONB DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_incident ON graph_nodes(incident_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_incident ON graph_edges(incident_id);
"""

# Provenance-specific edge types the chat agent cares about most.
PROVENANCE_EDGE_TYPES = ("made", "led_to", "based_on")


async def create_graph_tables() -> None:
    """Creates graph_nodes / graph_edges if they don't already exist.
    Safe to call on every startup — CREATE TABLE IF NOT EXISTS is idempotent."""
    for statement in filter(None, (s.strip() for s in _CREATE_TABLES_SQL.split(";"))):
        await execute_query(statement)


async def insert_node(node_type: str, label: str, incident_id: int, metadata: dict | None = None) -> int:
    """Inserts one node, returns its new id.

    NOTE: uses engine.begin() directly, NOT fetch_all — fetch_all is built
    for read-only SELECT queries and does not commit its transaction
    (confirmed: every insert routed through fetch_all showed ROLLBACK in
    the logs, so nothing was actually persisted, which then broke the
    foreign-key insert in insert_edge right after it). engine.begin()
    auto-commits on success and auto-rolls-back on error, which is what
    an INSERT actually needs.

    Also casts metadata to JSONB explicitly — a raw text() query doesn't
    carry the column-type info needed to auto-serialize a Python dict for
    a JSONB column, so it must be passed as a JSON string + CAST(...).
    """
    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                INSERT INTO graph_nodes (node_type, label, incident_id, metadata)
                VALUES (:node_type, :label, :incident_id, CAST(:metadata AS JSONB))
                RETURNING id
            """),
            {
                "node_type": node_type,
                "label": label,
                "incident_id": incident_id,
                "metadata": json.dumps(metadata or {}),
            },
        )
        return result.scalar_one()


async def insert_edge(
    source_id: int,
    target_id: int,
    edge_type: str,
    incident_id: int,
    metadata: dict | None = None,
) -> int:
    """Inserts one edge, returns its new id. Same engine.begin() +
    JSONB-casting fix as insert_node, for the same reasons."""
    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                INSERT INTO graph_edges (source_id, target_id, edge_type, incident_id, metadata)
                VALUES (:source_id, :target_id, :edge_type, :incident_id, CAST(:metadata AS JSONB))
                RETURNING id
            """),
            {
                "source_id": source_id,
                "target_id": target_id,
                "edge_type": edge_type,
                "incident_id": incident_id,
                "metadata": json.dumps(metadata or {}),
            },
        )
        return result.scalar_one()


async def fetch_graph_for_incident(incident_id: int) -> dict[str, list[dict[str, Any]]]:
    """Returns {nodes: [...], links: [...]} — the exact shape react-force-graph
    expects, per 02_ARCHITECTURE.md §4/§5. Used by both the BlastRadiusGraph
    component and (filtered) by the chat agent below."""
    nodes = await fetch_all(
        "SELECT id, node_type, label, metadata FROM graph_nodes WHERE incident_id = :incident_id",
        {"incident_id": incident_id},
    )
    edges = await fetch_all(
        """
        SELECT id, source_id AS source, target_id AS target, edge_type, metadata
        FROM graph_edges WHERE incident_id = :incident_id
        """,
        {"incident_id": incident_id},
    )
    return {"nodes": nodes, "links": edges}


async def fetch_provenance_for_incident(incident_id: int) -> list[dict[str, Any]]:
    """Returns only the decision-provenance edges ('made'/'led_to'/'based_on')
    for an incident, joined with both endpoint nodes' labels — this is the
    exact slice of data the chat agent grounds its answers in."""
    placeholders = ", ".join(f"'{t}'" for t in PROVENANCE_EDGE_TYPES)
    return await fetch_all(
        f"""
        SELECT
            e.id            AS edge_id,
            e.edge_type,
            e.metadata      AS edge_metadata,
            src.node_type   AS source_type,
            src.label       AS source_label,
            tgt.node_type   AS target_type,
            tgt.label       AS target_label,
            e.created_at
        FROM graph_edges e
        JOIN graph_nodes src ON src.id = e.source_id
        JOIN graph_nodes tgt ON tgt.id = e.target_id
        WHERE e.incident_id = :incident_id
          AND e.edge_type IN ({placeholders})
        ORDER BY e.created_at ASC
        """,
        {"incident_id": incident_id},
    )