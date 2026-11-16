"""Fact and FactManager module for Dwarf Fortress-style knowledge and dialogue system.

Implements Section 6 of the GDD:
- Facts: discrete data objects representing historical or world events.
- FactManager: global registry of all facts; NPCs store only unique Fact IDs in their Memory.
"""

from dataclasses import dataclass, field


@dataclass
class Fact:
    """Represents a discrete piece of knowledge or a historical/world event.

    Attributes:
        id: Unique identifier for the fact.
        text: Narrative description of the fact.
        subject: Topic, person, group, or location the fact is about.
        location: Optional location name associated with the fact.
        tags: Categorization tags (e.g. 'rumor', 'bandits', 'tavern').
    """

    id: str
    text: str
    subject: str = ""
    location: str = ""
    tags: set[str] = field(default_factory=set)


class FactManager:
    """Central registry of all generated/known Facts in the world.

    NPCs store only unique Fact IDs in their Memory component; FactManager
    resolves the IDs into complete Fact objects.
    """

    def __init__(self) -> None:
        self.facts: dict[str, Fact] = {}

    def register_fact(
        self,
        fact_or_id: Fact | str | None = None,
        text: str = "",
        subject: str = "",
        location: str = "",
        tags: set[str] | None = None,
        fact_id: str | None = None,
    ) -> Fact:
        """Register a new Fact in the global registry."""
        resolved_id = fact_id if fact_id is not None else fact_or_id
        if isinstance(resolved_id, Fact):
            fact = resolved_id
        else:
            if resolved_id is None:
                raise ValueError("Must provide either a Fact instance or a fact ID string")
            fact = Fact(
                id=str(resolved_id),
                text=text,
                subject=subject,
                location=location,
                tags=tags if tags is not None else set(),
            )
        self.facts[fact.id] = fact
        return fact

    def get_fact(self, fact_id: str) -> Fact | None:
        """Retrieve a registered Fact by its unique ID, or None if unknown."""
        return self.facts.get(fact_id)

    def has_fact(self, fact_id: str) -> bool:
        """Return True if a Fact ID exists in the registry."""
        return fact_id in self.facts

    def all_facts(self) -> list[Fact]:
        """Return all registered Facts."""
        return list(self.facts.values())

    def clear(self) -> None:
        """Clear all registered Facts."""
        self.facts.clear()


# Default global FactManager instance
global_fact_manager = FactManager()
