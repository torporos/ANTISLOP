"""MessageLog system for recording and retrieving console and combat messages.

Implements the Message Console requirement:
- Stores message history strings.
- Returns the N most recent messages to display in the bottom console area.
- Pushes older messages up as new messages arrive.
"""

from dataclasses import dataclass


class MessageLog:
    """Stores a history of messages and provides recent entries for console display."""

    def __init__(self, max_messages: int = 200) -> None:
        self.messages: list[str] = []
        self.max_messages = max_messages

    def add(self, message: str) -> None:
        """Add a message to the log, printing to terminal and pushing old messages."""
        self.messages.append(message)
        if len(self.messages) > self.max_messages:
            self.messages.pop(0)
        print(f"[Log] {message}")

    def add_message(self, message: str) -> None:
        """Alias for add()."""
        self.add(message)

    def get_recent(self, count: int = 8) -> list[str]:
        """Return the most recent count messages in chronological order (oldest first)."""
        return self.messages[-count:] if self.messages else []

    def get_latest(self, count: int = 1) -> list[str]:
        """Return the most recent count messages (alias for get_recent)."""
        return self.get_recent(count)

    def clear(self) -> None:
        """Clear all messages from the log."""
        self.messages.clear()

    def __len__(self) -> int:
        return len(self.messages)


# Global MessageLog instance
global_message_log = MessageLog()
