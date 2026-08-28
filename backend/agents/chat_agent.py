"""
backend/agents/chat_agent.py

ChatAgent — Feature 16 from 01_PRD.md: "Chat interface where a judge can
literally ask the console 'why did you block this IP?' and get an answer
pulled from the provenance graph."

Given a judge's free-text question and an incident_id, this agent:
  1. Pulls the decision-provenance edges for that incident from
     graph_nodes / graph_edges (via backend/db/graph.py) — the same
     'made' / 'led_to' / 'based_on' edges the architecture doc defines.
  2. Serialises that provenance trail into a compact text block.
  3. Asks the LLM to answer the question using ONLY that data — explicitly
     instructed not to invent anything not present in the graph.

Mirrors backend/agents/triage_agent.py's structure and conventions
(same LLM provider, same _extract_json-style robustness, same
try/except fallback so the demo never hard-crashes if the LLM call fails).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from groq import AsyncGroq

from backend.db.graph import fetch_provenance_for_incident

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------

_GROQ_MODEL = "llama-3.3-70b-versatile"

_SYSTEM_PROMPT = """\
You are CHIMERA Explain — a SOC assistant that answers a judge's or \
analyst's question about ONE specific incident, using ONLY the decision \
trail provided to you below. This trail is the system's actual recorded \
provenance graph: which agent made which decision, and what evidence it \
was based on.

Rules:
- Answer ONLY using the provided decision trail. Do not invent IPs, CVEs,
  agent names, or actions that are not present in the data.
- If the trail does not contain enough information to answer, say so
  plainly instead of guessing.
- Be concise — 2-4 sentences is usually enough for a live demo answer.
- Refer to specific recorded steps when relevant (e.g. "the Risk Engine
  computed a risk score of 0.31, which triggered..." ) rather than vague
  language like "the system decided".

Respond with ONLY valid JSON — no markdown fences, no prose outside the JSON.

Required JSON schema:
{
  "answer": "<your grounded answer to the question>",
  "cited_edge_ids": [<int>, ...],   // ids of the provenance edges you relied on
  "confidence": "grounded" | "partial" | "insufficient_data"
}
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _format_provenance_trail(rows: list[dict[str, Any]]) -> str:
    """Turns the raw provenance edge rows into a compact, LLM-readable
    numbered list, e.g.:
        [edge_id=7] TriageAgent --made--> Decision(severity=CRITICAL)
        [edge_id=8] Decision(severity=CRITICAL) --led_to--> Action(block_ip)
    """
    if not rows:
        return "(no provenance data recorded for this incident yet)"

    lines = []
    for row in rows:
        lines.append(
            f"[edge_id={row['edge_id']}] "
            f"{row['source_type']}:{row['source_label']} "
            f"--{row['edge_type']}--> "
            f"{row['target_type']}:{row['target_label']}"
        )
    return "\n".join(lines)


def _extract_json(text: str) -> dict[str, Any]:
    """Same robustness pattern as triage_agent.py's _extract_json —
    strips markdown fences, falls back to extracting the first {...} block."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response: {text!r}")


def _fallback_answer(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """If the LLM call fails, don't just error out on stage — return the
    raw provenance trail as a plain-language listing instead. Not as
    polished as the LLM answer, but it keeps the demo alive."""
    if not rows:
        return {
            "answer": "No decision trail has been recorded for this incident yet.",
            "cited_edge_ids": [],
            "confidence": "insufficient_data",
        }

    summary = "; ".join(
        f"{row['source_label']} {row['edge_type'].replace('_', ' ')} {row['target_label']}"
        for row in rows
    )
    return {
        "answer": f"Recorded decision trail: {summary}.",
        "cited_edge_ids": [row["edge_id"] for row in rows],
        "confidence": "partial",
    }


async def _call_llm(system: str, user: str) -> str:
    """Same Groq call pattern as triage_agent.py — GROQ_API_KEY is read
    from the environment by the SDK automatically."""
    groq_client = AsyncGroq(api_key=None)
    chat = await groq_client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=512,
        response_format={"type": "json_object"},
    )
    return chat.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Public agent class
# ---------------------------------------------------------------------------

class ChatAgent:
    """
    Answers a free-text question about one incident, grounded in that
    incident's recorded decision-provenance graph.

    Usage::

        agent = ChatAgent()
        result = await agent.answer(incident_id=42, question="Why did you block this IP?")
        # result → {"answer": "...", "cited_edge_ids": [7, 8], "confidence": "grounded"}
    """

    async def answer(self, incident_id: int, question: str) -> dict[str, Any]:
        logger.info("ChatAgent.answer | incident_id=%s | question=%r", incident_id, question)

        rows = await fetch_provenance_for_incident(incident_id)
        trail_text = _format_provenance_trail(rows)

        user_msg = f"Question: {question}\n\nRecorded decision trail:\n{trail_text}"

        try:
            raw_response = await _call_llm(_SYSTEM_PROMPT, user_msg)
            result = _extract_json(raw_response)

            confidence = str(result.get("confidence", "")).lower()
            if confidence not in {"grounded", "partial", "insufficient_data"}:
                confidence = "partial"

            cited = result.get("cited_edge_ids", [])
            if not isinstance(cited, list):
                cited = []

            return {
                "answer": result.get("answer", ""),
                "cited_edge_ids": cited,
                "confidence": confidence,
            }

        except Exception as exc:
            logger.error("ChatAgent LLM call failed: %s — using fallback", exc)
            return _fallback_answer(rows)
