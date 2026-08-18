"""Reusable prompt templates for incident-response flows."""
from __future__ import annotations


def register(mcp) -> None:
    @mcp.prompt()
    def triage_incident(service: str, symptom: str) -> str:
        """Prompt template that guides an agent through initial incident triage."""
        return (
            f"You are triaging a potential incident affecting {service}.\n"
            f"Reported symptom: {symptom}\n\n"
            "1. Check recent deployments for this service.\n"
            "2. Check for other open incidents on the same service.\n"
            "3. Search runbooks for this symptom.\n"
            "4. Recommend a next action (rollback, escalate, or monitor)."
        )
