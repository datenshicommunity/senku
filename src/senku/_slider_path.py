"""Converts .osu slider control points into a piecewise-linear path, and
provides position-at-distance lookup along that path.

Implements the standard curve types used by the legacy .osu format:
Bezier (adaptive de Casteljau subdivision), Catmull-Rom, circular arc
("PerfectCurve", through 3 points), and Linear. These are well-known,
public-domain geometric algorithms (de Casteljau's algorithm, Catmull-Rom
splines, circle-through-3-points) -- written from scratch here, not
adapted from any specific codebase. Deliberately excludes the newer
explicit-B-spline-degree feature and the editor-only reverse curve-fitting
functions, neither of which apply to already-exported legacy .osu files.
"""

from __future__ import annotations

import math

import numpy as np

BEZIER_TOLERANCE = 0.25
CIRCULAR_ARC_TOLERANCE = 0.1


def _bezier_is_flat_enough(points: list[tuple[float, float]]) -> bool:
    for i in range(1, len(points) - 1):
        ax = points[i - 1][0] - 2 * points[i][0] + points[i + 1][0]
        ay = points[i - 1][1] - 2 * points[i][1] + points[i + 1][1]
        if ax * ax + ay * ay > BEZIER_TOLERANCE * BEZIER_TOLERANCE * 4:
            return False
    return True


def _bezier_subdivide(points: list[tuple[float, float]]) -> tuple[list, list]:
    # De Casteljau's algorithm is inherently O(n^2) in the number of control
    # points (a triangular midpoint reduction) -- unavoidable and the same in
    # any implementation, reference included. What IS avoidable is doing that
    # O(n^2) work through Python-level tuple allocation/indexing: a troll
    # beatmap with tens of thousands of control points on a single slider
    # segment turns a few-billion-operation task that's instant in a
    # compiled runtime into a multi-minute one in interpreted Python. Same
    # math, vectorised per row with numpy so each "j" loop is one array op
    # instead of n Python-level iterations.
    n = len(points)
    midpoints = np.asarray(points, dtype=np.float64)
    left = np.empty((n, 2), dtype=np.float64)
    right = np.empty((n, 2), dtype=np.float64)

    for i in range(n):
        left[i] = midpoints[0]
        right[n - i - 1] = midpoints[n - i - 1]
        m = n - i - 1
        if m > 0:
            midpoints[:m] = (midpoints[:m] + midpoints[1:m + 1]) * 0.5

    return [(float(p[0]), float(p[1])) for p in left], [(float(p[0]), float(p[1])) for p in right]


def _bezier_approximate(points: list[tuple[float, float]], output: list[tuple[float, float]]) -> None:
    n = len(points)
    left, right = _bezier_subdivide(points)

    combined = left + right[1:]

    output.append(points[0])
    for i in range(1, n - 1):
        index = 2 * i
        px = 0.25 * (combined[index - 1][0] + 2 * combined[index][0] + combined[index + 1][0])
        py = 0.25 * (combined[index - 1][1] + 2 * combined[index][1] + combined[index + 1][1])
        output.append((px, py))


_MAX_BEZIER_CONTROL_POINTS = 300


def _bezier_to_piecewise_linear(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) < 2:
        return list(points)

    if len(points) > _MAX_BEZIER_CONTROL_POINTS:
        # De Casteljau subdivision is O(n^2) per call, and unlike the
        # subdivision-count cap below, that cost is paid on the FIRST call
        # regardless of how few times we recurse -- a troll slider with tens
        # or hundreds of thousands of control points (real example: a single
        # segment with 147,545 points) makes even one subdivide call take
        # tens of seconds. No normal map's slider curve carries anywhere
        # near this many meaningfully-distinct control points, so evenly
        # downsampling (keeping the endpoints) bounds the worst case without
        # affecting any realistic beatmap's output.
        step = (len(points) - 1) / (_MAX_BEZIER_CONTROL_POINTS - 1)
        points = [points[round(i * step)] for i in range(_MAX_BEZIER_CONTROL_POINTS)]

    output: list[tuple[float, float]] = []
    stack = [list(points)]

    # Depth-first adaptive subdivision (iterative, matching the reference's
    # stack-based approach to avoid recursion depth issues on pathological inputs).
    work = [points]
    result_stack = []
    to_process = [points]

    # Safety bound, not a reference-verified constant: de Casteljau subdivision
    # doesn't shrink the control-point count on either half (both halves keep
    # all n points, just describing a smaller curve span), so a pathological
    # slider with tens of thousands of control points that never converges to
    # "flat enough" can recurse effectively forever -- each level is O(n^2)
    # regardless of how vectorised the inner loop is. Bail out to whatever
    # segment we're on rather than hang; this only ever triggers on
    # troll/edge-case content nowhere near normal map complexity.
    _MAX_SUBDIVISIONS = 10_000
    subdivisions = 0

    while to_process:
        current = to_process.pop()
        if subdivisions >= _MAX_SUBDIVISIONS or _bezier_is_flat_enough(current):
            _bezier_approximate(current, output)
            continue
        subdivisions += 1
        left, right = _bezier_subdivide(current)
        to_process.append(right)
        to_process.append(left)

    output.append(points[-1])
    return output


def _catmull_find_point(v1, v2, v3, v4, t: float) -> tuple[float, float]:
    t2 = t * t
    t3 = t * t2
    x = 0.5 * (2 * v2[0] + (-v1[0] + v3[0]) * t + (2 * v1[0] - 5 * v2[0] + 4 * v3[0] - v4[0]) * t2 + (-v1[0] + 3 * v2[0] - 3 * v3[0] + v4[0]) * t3)
    y = 0.5 * (2 * v2[1] + (-v1[1] + v3[1]) * t + (2 * v1[1] - 5 * v2[1] + 4 * v3[1] - v4[1]) * t2 + (-v1[1] + 3 * v2[1] - 3 * v3[1] + v4[1]) * t3)
    return (x, y)


def _catmull_to_piecewise_linear(points: list[tuple[float, float]], detail: int = 50) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    n = len(points)

    for i in range(n - 1):
        v1 = points[i - 1] if i > 0 else points[i]
        v2 = points[i]
        v3 = points[i + 1] if i < n - 1 else (2 * v2[0] - v1[0], 2 * v2[1] - v1[1])
        v4 = points[i + 2] if i < n - 2 else (2 * v3[0] - v2[0], 2 * v3[1] - v2[1])

        for c in range(detail):
            result.append(_catmull_find_point(v1, v2, v3, v4, c / detail))
            result.append(_catmull_find_point(v1, v2, v3, v4, (c + 1) / detail))

    return result


def _circular_arc_properties(p0, p1, p2):
    ax, ay = p0
    bx, by = p1
    cx, cy = p2

    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None

    a_sq = ax * ax + ay * ay
    b_sq = bx * bx + by * by
    c_sq = cx * cx + cy * cy

    centre_x = (a_sq * (by - cy) + b_sq * (cy - ay) + c_sq * (ay - by)) / d
    centre_y = (a_sq * (cx - bx) + b_sq * (ax - cx) + c_sq * (bx - ax)) / d

    radius = math.hypot(ax - centre_x, ay - centre_y)

    theta_start = math.atan2(ay - centre_y, ax - centre_x)
    theta_mid = math.atan2(by - centre_y, bx - centre_x)
    theta_end = math.atan2(cy - centre_y, cx - centre_x)

    # Determine direction (clockwise/counterclockwise) via the midpoint angle.
    while theta_mid < theta_start:
        theta_mid += 2 * math.pi
    while theta_end < theta_start:
        theta_end += 2 * math.pi
    if theta_mid > theta_end:
        direction = -1
        theta_end -= 2 * math.pi
    else:
        direction = 1

    theta_range = abs(theta_end - theta_start)

    return {
        "centre": (centre_x, centre_y),
        "radius": radius,
        "theta_start": theta_start,
        "theta_range": theta_range,
        "direction": direction,
    }


def _circular_arc_to_piecewise_linear(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pr = _circular_arc_properties(points[0], points[1], points[2])
    if pr is None:
        return _bezier_to_piecewise_linear(points)

    radius = pr["radius"]
    if 2 * radius <= CIRCULAR_ARC_TOLERANCE:
        amount_points = 2
    else:
        amount_points = max(2, math.ceil(pr["theta_range"] / (2 * math.acos(1 - CIRCULAR_ARC_TOLERANCE / radius))))

    output = []
    for i in range(amount_points):
        fract = i / (amount_points - 1) if amount_points > 1 else 0
        theta = pr["theta_start"] + pr["direction"] * fract * pr["theta_range"]
        cx, cy = pr["centre"]
        output.append((cx + radius * math.cos(theta), cy + radius * math.sin(theta)))

    return output


def path_to_piecewise_linear(curve_type: str, control_points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """control_points: full point list INCLUDING the head, with red-point
    duplicates already split into separate Bezier segments by the caller
    for curve_type 'B' (each segment independently de-Casteljau'd, then
    concatenated) -- this function handles a single already-split segment."""
    if len(control_points) < 2:
        return list(control_points)

    if curve_type == "L":
        return list(control_points)
    if curve_type == "P" and len(control_points) == 3:
        return _circular_arc_to_piecewise_linear(control_points)
    if curve_type == "C":
        return _catmull_to_piecewise_linear(control_points)
    # "B" (bezier), or "P" with != 3 points (falls back to bezier, matching
    # the reference's behaviour for degenerate/collinear perfect-curve input).
    return _bezier_to_piecewise_linear(control_points)


def split_bezier_segments(control_points: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """Splits a raw control-point list on consecutive duplicate points --
    the legacy .osu format's way of encoding multiple independent Bezier
    segments within one slider."""
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []

    for i, point in enumerate(control_points):
        if current and point == current[-1]:
            if len(current) > 1:
                segments.append(current)
            current = [point]
        else:
            current.append(point)

    if len(current) > 1:
        segments.append(current)

    return segments


def build_path(curve_type: str, control_points: list[tuple[float, float]], expected_length: float) -> list[tuple[float, float]]:
    """Builds the full piecewise-linear path for a slider, handling
    multi-segment Bezier sliders, and clamping/extending to expected_length
    (the .osu file's explicit pixelLength, which is authoritative over
    whatever raw length the control points geometrically produce)."""
    if curve_type == "B":
        segments = split_bezier_segments(control_points)
        combined: list[tuple[float, float]] = []
        for seg in segments:
            piece = _bezier_to_piecewise_linear(seg)
            if combined and piece:
                piece = piece[1:] if combined[-1] == piece[0] else piece
            combined.extend(piece)
        path = combined if combined else list(control_points)
    else:
        path = path_to_piecewise_linear(curve_type, control_points)

    return _clamp_to_length(path, expected_length)


def _cumulative_lengths(path: list[tuple[float, float]]) -> list[float]:
    cumulative = [0.0]
    for i in range(1, len(path)):
        d = math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1])
        cumulative.append(cumulative[-1] + d)
    return cumulative


def _clamp_to_length(path: list[tuple[float, float]], expected_length: float) -> list[tuple[float, float]]:
    if len(path) < 2 or expected_length <= 0:
        return path

    cumulative = _cumulative_lengths(path)
    total = cumulative[-1]
    if total <= 0:
        return path

    if expected_length < total:
        # Trim the path to expected_length.
        for i in range(1, len(cumulative)):
            if cumulative[i] >= expected_length:
                t = (expected_length - cumulative[i - 1]) / (cumulative[i] - cumulative[i - 1]) if cumulative[i] != cumulative[i - 1] else 0
                x = path[i - 1][0] + (path[i][0] - path[i - 1][0]) * t
                y = path[i - 1][1] + (path[i][1] - path[i - 1][1]) * t
                return path[:i] + [(x, y)]
        return path
    elif expected_length > total:
        # Extend in a straight line from the final segment's direction.
        if len(path) >= 2:
            dx = path[-1][0] - path[-2][0]
            dy = path[-1][1] - path[-2][1]
            seg_len = math.hypot(dx, dy)
            if seg_len > 0:
                extra = expected_length - total
                x = path[-1][0] + dx / seg_len * extra
                y = path[-1][1] + dy / seg_len * extra
                return path + [(x, y)]
        return path

    return path


def position_at(path: list[tuple[float, float]], progress: float) -> tuple[float, float]:
    """progress in [0, 1] -- fraction of total path length."""
    if not path:
        return (0.0, 0.0)
    if len(path) == 1:
        return path[0]

    cumulative = _cumulative_lengths(path)
    total = cumulative[-1]
    if total <= 0:
        return path[0]

    target = max(0.0, min(1.0, progress)) * total

    for i in range(1, len(cumulative)):
        if cumulative[i] >= target:
            seg_len = cumulative[i] - cumulative[i - 1]
            t = (target - cumulative[i - 1]) / seg_len if seg_len > 0 else 0
            x = path[i - 1][0] + (path[i][0] - path[i - 1][0]) * t
            y = path[i - 1][1] + (path[i][1] - path[i - 1][1]) * t
            return (x, y)

    return path[-1]
