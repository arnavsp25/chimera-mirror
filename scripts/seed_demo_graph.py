"""
scripts/seed_demo_graph.py

Inserts one sample incident's worth of decision-provenance data into
graph_nodes / graph_edges, so ChatAgent (Feature 16) has something real
to answer questions about — without waiting on Feature 12 (which will
eventually have the actual agents write these rows as they run).

This mirrors the golden-thread demo scenario from 02_ARCHITECTURE.md §3:
brute force -> account compromise -> privilege escalation -> risk engine
decision -> automated block action -> Tavily-grounded intel lookup.

Run once, against a real DATABASE_URL:
    python -m scripts.seed_demo_graph

Uses incident_id = 1 by default — change DEMO_INCIDENT_ID below if you
want to seed a different (already-existing) incident row.
"""

import asyncio

from backend.db.graph import create_graph_tables, insert_edge, insert_node

DEMO_INCIDENT_ID = 1


async def seed() -> None:
    await create_graph_tables()

    # --- Nodes -------------------------------------------------------
    attacker_ip = await insert_node("ip", "185.10.20.30", DEMO_INCIDENT_ID)
    target_host = await insert_node("host", "WEB-SERVER-03", DEMO_INCIDENT_ID)
    triage_agent = await insert_node("agent", "TriageAgent", DEMO_INCIDENT_ID)
    intel_agent = await insert_node("agent", "ThreatIntelAgent", DEMO_INCIDENT_ID)
    risk_engine = await insert_node("agent", "RiskEngine", DEMO_INCIDENT_ID)
    decision_critical = await insert_node("decision", "severity=CRITICAL", DEMO_INCIDENT_ID)
    intel_source = await insert_node(
        "intel_source", "Tavily lookup: 185.10.20.30 flagged as known C2 infrastructure", DEMO_INCIDENT_ID
    )
    action_block = await insert_node("decision", "action=block_ip (automated, risk=0.31)", DEMO_INCIDENT_ID)

    # --- Blast-radius edges -------------------------------------------
    await insert_edge(attacker_ip, target_host, "targeted", DEMO_INCIDENT_ID)

    # --- Decision-provenance edges -------------------------------------
    await insert_edge(triage_agent, decision_critical, "made", DEMO_INCIDENT_ID)
    await insert_edge(decision_critical, intel_source, "based_on", DEMO_INCIDENT_ID)
    await insert_edge(intel_agent, intel_source, "made", DEMO_INCIDENT_ID)
    await insert_edge(risk_engine, action_block, "made", DEMO_INCIDENT_ID)
    await insert_edge(decision_critical, action_block, "led_to", DEMO_INCIDENT_ID)

    print(f"[seed_demo_graph] Seeded demo provenance graph for incident_id={DEMO_INCIDENT_ID}")


if __name__ == "__main__":
    asyncio.run(seed())
