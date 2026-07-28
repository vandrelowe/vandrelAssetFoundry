import math
from dataclasses import dataclass

Vector3 = tuple[float, float, float]


@dataclass(frozen=True)
class FramingSolution:
    distance: float
    forward: Vector3
    right: Vector3
    up: Vector3
    projected_bounds: tuple[float, float, float, float]


def fit_perspective_bounds(
    corners: list[Vector3],
    center: Vector3,
    camera_direction: Vector3,
    angle_x: float,
    angle_y: float,
    frame_limit: float = 0.88,
) -> FramingSolution:
    if not corners:
        raise ValueError("Perspective framing requires at least one geometry point.")
    if not 0 < frame_limit < 1:
        raise ValueError("Frame limit must be between zero and one.")
    forward = _scale(_normalized(camera_direction), -1.0)
    right = _normalized(_cross(forward, (0.0, 0.0, 1.0)))
    up = _normalized(_cross(right, forward))
    offsets = [_subtract(point, center) for point in corners]
    tan_x = math.tan(angle_x / 2)
    tan_y = math.tan(angle_y / 2)
    required = 0.0
    for offset in offsets:
        depth_offset = _dot(offset, forward)
        required = max(
            required,
            abs(_dot(offset, right)) / (frame_limit * tan_x) - depth_offset,
            abs(_dot(offset, up)) / (frame_limit * tan_y) - depth_offset,
            -depth_offset + 1e-6,
        )
    if not math.isfinite(required) or required <= 0:
        raise ValueError("Could not establish a finite positive framing distance.")
    bounds = _projected_bounds(offsets, forward, right, up, required, tan_x, tan_y)
    if any(abs(value) > frame_limit + 1e-6 for value in bounds):
        raise ValueError("Computed camera distance does not contain every geometry-bound corner.")
    return FramingSolution(required, forward, right, up, bounds)


def _projected_bounds(
    offsets: list[Vector3],
    forward: Vector3,
    right: Vector3,
    up: Vector3,
    distance: float,
    tan_x: float,
    tan_y: float,
) -> tuple[float, float, float, float]:
    projected = []
    for offset in offsets:
        depth = distance + _dot(offset, forward)
        projected.append(
            (
                _dot(offset, right) / (depth * tan_x),
                _dot(offset, up) / (depth * tan_y),
            )
        )
    return (
        min(value[0] for value in projected),
        max(value[0] for value in projected),
        min(value[1] for value in projected),
        max(value[1] for value in projected),
    )


def _subtract(left: Vector3, right: Vector3) -> Vector3:
    return tuple(left[index] - right[index] for index in range(3))  # type: ignore[return-value]


def _scale(value: Vector3, factor: float) -> Vector3:
    return tuple(component * factor for component in value)  # type: ignore[return-value]


def _dot(left: Vector3, right: Vector3) -> float:
    return sum(left[index] * right[index] for index in range(3))


def _cross(left: Vector3, right: Vector3) -> Vector3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _normalized(value: Vector3) -> Vector3:
    length = math.sqrt(_dot(value, value))
    if length <= 0:
        raise ValueError("Camera direction must be nonzero.")
    return _scale(value, 1 / length)
