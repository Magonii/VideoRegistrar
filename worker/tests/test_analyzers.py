from worker.analyzers import LineCounter, QueueMonitor, TrackSampler
from worker.geometry import apply_homography, crossing_direction, point_in_polygon

# Горизонтальная линия слева направо: «внутрь» — сторона, где знак произведения = in_side.
# Для p1=(0,.5), p2=(1,.5) точка ниже линии на экране (y больше) даёт знак +1.
P1, P2 = (0.0, 0.5), (1.0, 0.5)


def test_crossing_direction_both_ways():
    assert crossing_direction(P1, P2, 1, (0.5, 0.4), (0.5, 0.6)) == "in"
    assert crossing_direction(P1, P2, 1, (0.5, 0.6), (0.5, 0.4)) == "out"
    assert crossing_direction(P1, P2, -1, (0.5, 0.4), (0.5, 0.6)) == "out"


def test_no_crossing_when_step_misses_segment():
    assert crossing_direction(P1, P2, 1, (0.5, 0.4), (0.5, 0.45)) is None
    # шаг пересекает продолжение прямой, но не сам отрезок
    assert crossing_direction((0.0, 0.5), (0.4, 0.5), 1, (0.8, 0.4), (0.8, 0.6)) is None


def test_line_counter_counts_each_track_once():
    line = {"id": 7, "p1": [0, 0.5], "p2": [1, 0.5], "in_side": 1}
    lc = LineCounter([line])
    assert lc.update({1: (0.3, 0.4)}) == []  # первое появление — просто запоминаем
    assert lc.update({1: (0.3, 0.6)}) == [{"line_id": 7, "direction": "in", "count": 1}]
    assert lc.update({1: (0.3, 0.7)}) == []  # дальше линию не пересекает
    assert lc.update({1: (0.3, 0.4)}) == [{"line_id": 7, "direction": "out", "count": 1}]


def test_line_counter_forgets_lost_tracks():
    line = {"id": 1, "p1": [0, 0.5], "p2": [1, 0.5], "in_side": 1}
    lc = LineCounter([line])
    lc.update({1: (0.3, 0.4)})
    lc.update({})  # трек пропал
    # новый трек с тем же id начинается заново и не даёт ложного пересечения
    assert lc.update({1: (0.3, 0.6)}) == []


def test_point_in_polygon():
    square = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]
    assert point_in_polygon(square, (0.5, 0.5))
    assert not point_in_polygon(square, (0.9, 0.5))


def test_queue_requires_min_dwell():
    zone = {"id": 3, "kind": "queue", "min_dwell_sec": 5, "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}
    qm = QueueMonitor([zone], emit_every=0)
    assert qm.update({1: (0.5, 0.5), 2: (0.4, 0.4)}, now=100.0)[0]["people"] == 0  # только пришли
    snap = qm.update({1: (0.5, 0.5), 2: (0.4, 0.4)}, now=107.0)[0]
    assert snap["people"] == 2 and snap["max_wait_sec"] == 7.0
    snap = qm.update({1: (0.5, 0.5)}, now=108.0)[0]  # второй ушёл
    assert snap["people"] == 1


def test_homography_identity_and_scale():
    ident = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    assert apply_homography(ident, (0.3, 0.7)) == (0.3, 0.7)
    scale = [[2, 0, 0], [0, 0.5, 0], [0, 0, 1]]
    assert apply_homography(scale, (0.25, 0.8)) == (0.5, 0.4)


def test_sampler_needs_homography_and_respects_period():
    assert TrackSampler(None).update({1: (0.5, 0.5)}, now=1.0) == []
    s = TrackSampler([[1, 0, 0], [0, 1, 0], [0, 0, 1]], period=0.5)
    assert len(s.update({1: (0.5, 0.5)}, now=1.0)) == 1
    assert s.update({1: (0.5, 0.5)}, now=1.2) == []
    assert len(s.update({1: (0.5, 0.5)}, now=1.6)) == 1
