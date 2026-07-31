# -*- coding: utf-8 -*-
"""NSRpolytopoint.txt -> data/route_nsr.geojson

입력 파일은 공백 구분 텍스트이며 **4번째 열이 경도, 5번째 열이 위도**다.
(1열 순번, 2·3열은 투영좌표 x/y)

경로는 부산 부근에서 출발해 베링해협 - 북극항로 - 북유럽(로테르담 부근)까지
갔다가 되돌아오는 **왕복 경로**다 (첫 점 = 끝 점). 출발점에서 대권거리가
가장 먼 점을 반환점으로 보고 왕로/복로 두 LineString 으로 나눈다.

지도(index.html)는 EPSG:3413 극사영을 웹메르카토르 가상좌표에 매핑해 그리므로,
여기서는 **경위도(EPSG:4326) 그대로** 저장하고 투영 변환은 브라우저의
toFake() 가 담당한다. 다만 점 간격이 넓으면 극사영에서 직선이 실제 항로와
어긋나므로, 위경도 구간을 잘게 나눠(densify) 저장한다.

사용:  python make_route_geojson.py [입력.txt] [출력.geojson]
"""
from __future__ import annotations

import json
import math
import os
import sys

STEP_DEG = 0.4          # densify 간격 (경위도 도)


def read_points(path: str) -> list[tuple[float, float]]:
    pts = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            c = line.split()
            if len(c) < 5:
                continue
            try:
                lon, lat = float(c[3]), float(c[4])
            except ValueError:
                continue
            if -180.001 <= lon <= 180.001 and -90 <= lat <= 90:
                pts.append((lon, lat))
    return pts


def gc_km(a, b) -> float:
    """대권거리 (km)."""
    lo1, la1, lo2, la2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def _wrap(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0


def densify(pts: list[tuple[float, float]], step: float = STEP_DEG):
    """구간을 step(도) 이하로 잘게 나눈다. 날짜변경선은 짧은 쪽으로 보간."""
    out = []
    for i in range(len(pts) - 1):
        lo0, la0 = pts[i]
        lo1, la1 = pts[i + 1]
        d = lo1 - lo0
        if d > 180:
            d -= 360
        elif d < -180:
            d += 360
        n = max(1, int(math.ceil(max(abs(d), abs(la1 - la0)) / step)))
        for k in range(n):
            t = k / n
            out.append((round(_wrap(lo0 + d * t), 6), round(la0 + (la1 - la0) * t, 6)))
    out.append((round(_wrap(pts[-1][0]), 6), round(pts[-1][1], 6)))
    return out


def build(pts: list[tuple[float, float]]) -> dict:
    if len(pts) < 3:
        raise SystemExit('경로 점이 너무 적습니다.')
    closed = gc_km(pts[0], pts[-1]) < 20.0        # 첫 점 == 끝 점 (왕복)
    start = pts[0]
    turn = max(range(len(pts)), key=lambda i: gc_km(start, pts[i]))

    feats = []
    if closed and 3 < turn < len(pts) - 4:
        legs = [('outbound', '왕로 (한국 -> 북유럽)', pts[:turn + 1], '#ff8a3d'),
                ('inbound', '복로 (북유럽 -> 한국)', pts[turn:], '#4dd7ff')]
    else:
        legs = [('route', '항해 경로', pts, '#ff8a3d')]

    total = 0.0
    for key, name, seg, color in legs:
        dens = densify(seg)
        dist = sum(gc_km(seg[i], seg[i + 1]) for i in range(len(seg) - 1))
        total += dist
        feats.append({
            'type': 'Feature',
            'properties': {'leg': key, 'name': name, 'color': color,
                           'points': len(seg), 'length_km': round(dist, 1)},
            'geometry': {'type': 'LineString',
                         'coordinates': [list(p) for p in dens]},
        })

    marks = [('start', '출발 (부산 부근)', pts[0]),
             ('turn', '반환점 (북유럽)', pts[turn])]
    for key, name, p in marks:
        feats.append({
            'type': 'Feature',
            'properties': {'kind': 'marker', 'leg': key, 'name': name},
            'geometry': {'type': 'Point', 'coordinates': [round(p[0], 6), round(p[1], 6)]},
        })

    return {
        'type': 'FeatureCollection',
        'crs_note': 'EPSG:4326 (lon, lat) — 지도에서 EPSG:3413 으로 투영해 표출',
        'properties': {
            'title': '북극항로 항해 경로 (NSR)',
            'source': 'NSRpolytopoint.txt (4열=경도, 5열=위도)',
            'points_raw': len(pts),
            'turn_index': turn,
            'total_km': round(total, 1),
        },
        'features': feats,
    }


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, 'NSRpolytopoint.txt')
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(root, 'data', 'route_nsr.geojson')
    pts = read_points(src)
    if not pts:
        raise SystemExit(f'경로 점을 읽지 못했습니다: {src}')
    gj = build(pts)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(gj, f, ensure_ascii=False, separators=(',', ':'))
    p = gj['properties']
    print(f'[route] {src}\n  점 {p["points_raw"]}개, 반환점 index {p["turn_index"]}, '
          f'총 {p["total_km"]:,.0f} km')
    for ft in gj['features']:
        pr = ft['properties']
        if ft['geometry']['type'] == 'LineString':
            print(f'  - {pr["name"]}: {pr["length_km"]:,.0f} km '
                  f'({pr["points"]}점 -> {len(ft["geometry"]["coordinates"])}점 densify)')
    print(f'  저장: {dst}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
