"""Zone geometry: sampling stays inside the shape, contains() agrees, JSON round-trips."""

from __future__ import annotations

import pytest

from modules.zone_selector import Zone, polygon_self_intersects

N = 2000

RECT = Zone.make_rect(100, 200, 500, 450)
CIRCLE = Zone.make_circle(800, 600, 120)
POLY = Zone.make_polygon([(0, 0), (300, 20), (280, 260), (150, 180), (10, 240)])
TIGHT_RECT = Zone.make_rect(50, 50, 62, 62)
CONCAVE = Zone.make_polygon([(0, 0), (200, 0), (200, 200), (120, 200), (120, 60), (80, 60), (80, 200), (0, 200)])


@pytest.mark.parametrize("zone", [RECT, CIRCLE, POLY, TIGHT_RECT, CONCAVE],
                         ids=["rect", "circle", "polygon", "tight-rect", "concave"])
def test_random_point_stays_inside_and_contains_agrees(zone):
    for _ in range(N):
        x, y = zone.random_point()
        assert isinstance(x, int) and isinstance(y, int)
        assert zone.contains(x, y), (zone.shape, x, y)


@pytest.mark.parametrize("zone", [RECT, CIRCLE, POLY], ids=["rect", "circle", "polygon"])
def test_random_point_is_not_a_single_pixel(zone):
    pts = {zone.random_point() for _ in range(N)}
    # A real distribution over a zone this size should hit many pixels.
    assert len(pts) > 50


def test_random_point_respects_drift_and_still_stays_inside():
    zone = Zone.make_rect(0, 0, 200, 100)
    zone.drift_offset_x = 60.0
    zone.drift_offset_y = -30.0
    zone.sigma_scale = 2.0
    for _ in range(N):
        x, y = zone.random_point()
        assert zone.contains(x, y)


def test_rect_fallback_when_mean_is_pushed_outside_is_inside_and_jittered():
    # A drift far outside the rect makes every Gaussian draw miss, so the
    # fallback path runs every time. It must land inside and must not be
    # the same pixel every call.
    zone = Zone.make_rect(0, 0, 40, 40)
    zone.drift_offset_x = 5000.0
    zone.drift_offset_y = 5000.0
    pts = set()
    for _ in range(300):
        x, y = zone.random_point()
        assert zone.contains(x, y)
        pts.add((x, y))
    assert len(pts) > 1


def test_contains_edges_and_outside():
    assert RECT.contains(100, 200)
    assert RECT.contains(500, 450)
    assert not RECT.contains(99, 200)
    assert not RECT.contains(501, 450)

    cx, cy, r = CIRCLE.circle
    assert CIRCLE.contains(cx, cy)
    assert CIRCLE.contains(cx + r, cy)
    assert not CIRCLE.contains(cx + r + 1, cy)

    assert POLY.contains(150, 100)
    assert not POLY.contains(-1, -1)
    # Inside the notch of the concave shape is outside the polygon.
    assert not CONCAVE.contains(100, 150)
    assert CONCAVE.contains(40, 150)


def test_aabb_and_centroid():
    assert RECT.aabb() == (100, 200, 500, 450)
    assert RECT.centroid() == (300, 325)
    assert CIRCLE.aabb() == (680, 480, 920, 720)
    assert CIRCLE.centroid() == (800, 600)
    x1, y1, x2, y2 = POLY.aabb()
    assert (x1, y1, x2, y2) == (0, 0, 300, 260)
    cx, cy = POLY.centroid()
    assert POLY.contains(cx, cy)
    cx, cy = CONCAVE.centroid()
    assert CONCAVE.contains(cx, cy)


def test_make_rect_normalizes_corner_order():
    z = Zone.make_rect(500, 450, 100, 200)
    assert z.rect == (100, 200, 500, 450)


def test_make_circle_enforces_minimum_radius():
    assert Zone.make_circle(0, 0, 0).circle == (0, 0, 2)


@pytest.mark.parametrize("zone", [RECT, CIRCLE, POLY], ids=["rect", "circle", "polygon"])
def test_to_from_json_roundtrip(zone):
    d = zone.to_json()
    back = Zone.from_json(d)
    assert back is not None
    assert back.shape == zone.shape
    assert back.to_json() == d
    # Sampling state is runtime-only and never serialized.
    assert "drift_offset_x" not in d and "sigma_scale" not in d


def test_from_json_rejects_empty_or_malformed():
    assert Zone.from_json(None) is None
    assert Zone.from_json({}) is None
    assert Zone.from_json({"shape": "rect", "rect": None}) is None
    assert Zone.from_json({"shape": "polygon", "vertices": []}) is None
    assert Zone.from_json({"shape": "hexagon"}) is None


def test_polygon_self_intersection_detection():
    assert not polygon_self_intersects([(0, 0), (10, 0), (10, 10), (0, 10)])
    # Bow-tie: edges cross.
    assert polygon_self_intersects([(0, 0), (10, 10), (10, 0), (0, 10)])
