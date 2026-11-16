"""Global World Clock module for the Sandbox Roguelike RPG.

Tracks in-game time progression across hours, days, and years.
Used for overworld travel, regional resource consumption, and day/night simulation.
"""

from dataclasses import dataclass


@dataclass
class WorldClock:
    """Global simulation clock tracking world time progression."""

    year: int = 1
    day: int = 1
    hour: int = 8  # Start at 08:00 AM (Morning)
    minute: int = 0

    def advance_hours(self, hours: int = 4) -> None:
        """Advance time by given number of hours."""
        self.hour += hours
        while self.hour >= 24:
            self.hour -= 24
            self.day += 1
        while self.day > 365:
            self.day -= 365
            self.year += 1

    def advance_minutes(self, minutes: int = 1) -> None:
        """Advance time by given number of minutes."""
        self.minute += minutes
        while self.minute >= 60:
            self.minute -= 60
            self.advance_hours(1)

    @property
    def time_str(self) -> str:
        """Formatted display string for current date and time."""
        return f"Day {self.day}, {self.hour:02d}:{self.minute:02d}"

    @property
    def total_hours(self) -> int:
        """Total hours elapsed since epoch (Year 1, Day 1, 00:00)."""
        return ((self.year - 1) * 365 + (self.day - 1)) * 24 + self.hour

    def reset(self, year: int = 1, day: int = 1, hour: int = 8, minute: int = 0) -> None:
        """Reset the clock to specified or initial values."""
        self.year = year
        self.day = day
        self.hour = hour
        self.minute = minute


# Global singleton instance
global_world_clock: WorldClock = WorldClock()
