"""Чистая геометрия без внешних зависимостей: линии, полигоны, гомография.
Все координаты нормализованы (0..1) относительно кадра."""

Point = tuple[float, float]


def side(p1: Point, p2: Point, p: Point) -> int:
    """Знак векторного произведения (p2-p1)×(p-p1): +1 / -1 / 0 (на линии)."""
    cross = (p2[0] - p1[0]) * (p[1] - p1[1]) - (p2[1] - p1[1]) * (p[0] - p1[0])
    return (cross > 0) - (cross < 0)


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Пересекаются ли отрезки ab и cd (собственное пересечение)."""
    return side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0


def crossing_direction(p1: Point, p2: Point, in_side: int, prev: Point, cur: Point) -> str | None:
    """'in' / 'out', если шаг prev->cur пересёк отрезок p1-p2, иначе None."""
    if not segments_intersect(p1, p2, prev, cur):
        return None
    return "in" if side(p1, p2, cur) == in_side else "out"


def point_in_polygon(poly: list[list[float]], p: Point) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > p[1]) != (yj > p[1]) and p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def apply_homography(h: list[list[float]], p: Point) -> Point:
    x, y = p
    w = h[2][0] * x + h[2][1] * y + h[2][2]
    if abs(w) < 1e-12:
        return p
    return (
        (h[0][0] * x + h[0][1] * y + h[0][2]) / w,
        (h[1][0] * x + h[1][1] * y + h[1][2]) / w,
    )
