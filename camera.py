"""Camera system for viewport calculations in 2D scrolling grid maps."""


class Camera:
    """Manages viewport offsets to center the view on a target entity."""

    def __init__(self, viewport_width: int = 85, viewport_height: int = 30) -> None:
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.x = 0
        self.y = 0

    def update(self, target_x: int, target_y: int, map_width: int, map_height: int) -> None:
        """Center camera on (target_x, target_y), clamped to map boundaries."""
        # Ideal camera top-left position to center target on screen
        cam_x = target_x - self.viewport_width // 2
        cam_y = target_y - self.viewport_height // 2

        # Clamp offsets to stay within map boundaries
        max_cam_x = max(0, map_width - self.viewport_width)
        max_cam_y = max(0, map_height - self.viewport_height)

        self.x = max(0, min(cam_x, max_cam_x))
        self.y = max(0, min(cam_y, max_cam_y))

    def to_screen(self, map_x: int, map_y: int) -> tuple[int, int]:
        """Convert world/map coordinates to screen/viewport coordinates."""
        return map_x - self.x, map_y - self.y

    def in_view(self, map_x: int, map_y: int) -> bool:
        """Check whether world/map coordinates fall within the active viewport."""
        return 0 <= (map_x - self.x) < self.viewport_width and 0 <= (map_y - self.y) < self.viewport_height
