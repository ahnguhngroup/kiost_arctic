# -*- coding: utf-8 -*-
"""선박 AIS 항적 CSV/GPKG 여러 개 -> 웹 지도용 GeoJSON 한 파일.

입력: data/PANSTAR*.csv (열: Longitude, Latitude, Ship speed(kn), Ship course,
      Ship heading, Turning rate, Navigation status, Last update(CST), Last update(UTC))
      data/PANSTAR*.gpkg (GeoPackage — utc/cst/lon/lat/speed_kn/course_deg/
      heading_deg/turn_rate/nav_status 필드를 가진 track_points 레이어;
      sqlite3 로 직접 읽으므로 GDAL 불필요. 2026-09-29 추가)
      CSV 와 GPKG 가 함께 있으면 병합 후 UTC 시각 기준 중복 제거.
출력: <web>/PANSTAR_ACRO_track.geojson
  - Feature "track"  : LineString — 전체 항적(모든 기록, UTC 시각순, 중복 제거)
  - Feature "hourly" : Point ×N — **1시간 간격** 대표점(각 UTC 시각의 정시에 가장 가까운
                       기록). properties: utc, cst, lon, lat, sog_kn, cog, heading,
                       status, seg_kn(직전 대표점과의 구간 평균속력), idx
  - Feature "last"   : Point — 마지막 기록(예상 위치 계산 기준점)
  - FeatureCollection.properties: ship, t_start, t_end, n_records, n_hourly,
        total_km, sog_last_kn, avg_kn_24h(최근 24h 이동 구간 평균), avg_kn_underway(전체
        항해중 구간 평균) — 뷰어의 예상 도달 시각 계산에 사용

사용:  python tools/make_ship_track.py            # web/data/PANSTAR*.csv 전부
       python tools/make_ship_track.py --glob "data/PANSTAR_ACRO*.csv" --out PANSTAR_ACRO_track.geojson
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)

MAIN_ARGS = None            # 예: '--hours 1 --out PANSTAR_ACRO_track.geojson'


def _main_argv():
    import shlex
    if len(sys.argv) > 1:
        return sys.argv[1:]
    if MAIN_ARGS:
        print(f'(MAIN_ARGS 사용: {MAIN_ARGS})')
        return shlex.split(MAIN_ARGS)
    return []


def haversine_km(lo1, la1, lo2, la2):
    R = 6371.0088
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _read_csv(path):
    """cp949/utf-8 자동 판별, 열 이름은 접두어로 찾는다."""
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp949', 'latin-1'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return []
    hdr = [h.strip() for h in rows[0]]

    def col(prefix, exclude=None):
        for i, h in enumerate(hdr):
            hl = h.lower()
            if hl.startswith(prefix.lower()) and (exclude is None or exclude.lower() not in hl):
                return i
        return None
    i_lon = col('Longitude', exclude='deg-minute')
    i_lat = col('Latitude', exclude='deg-minute')
    i_sog = col('Ship speed')
    i_cog = col('Ship course')
    i_hdg = col('Ship heading')
    i_rot = col('Ship Turning')
    i_sta = col('Navigation status')
    i_utc = next((i for i, h in enumerate(hdr) if h.startswith('Last update') and 'UTC' in h), None)
    i_cst = next((i for i, h in enumerate(hdr) if h.startswith('Last update') and 'CST' in h), None)
    if None in (i_lon, i_lat, i_utc):
        raise SystemExit(f'열 구조를 알 수 없음: {path}\n  헤더: {hdr}')
    out = []
    for r in rows[1:]:
        if len(r) <= max(i_lon, i_lat, i_utc):
            continue
        try:
            lon, lat = float(r[i_lon]), float(r[i_lat])
            t = datetime.strptime(r[i_utc].strip(), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            continue

        def num(i):
            try:
                return float(r[i]) if i is not None and r[i].strip() != '' else None
            except ValueError:
                return None
        out.append({
            'lon': lon, 'lat': lat, 't': t,
            'cst': r[i_cst].strip() if i_cst is not None else '',
            'sog': num(i_sog), 'cog': num(i_cog), 'hdg': num(i_hdg), 'rot': num(i_rot),
            'status': r[i_sta].strip() if i_sta is not None else '',
            'src': os.path.basename(path),
        })
    return out


def _parse_utc(s):
    """'2026-08-21 06:59:53' | '2026/08/21 06:59:53+00' 등 -> datetime (UTC naive)."""
    s = (s or '').strip()
    for suf in ('+00:00', '+00', 'Z'):
        if s.endswith(suf):
            s = s[:-len(suf)].strip()
    if '.' in s[10:]:                       # 소수점 초 ('...:53.000') 제거
        s = s[:s.rindex('.')]
    s = s.replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y%m%d%H%M%S'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _read_gpkg(path):
    """GeoPackage track_points 레이어 -> 기록 리스트.

    lon/lat/utc 가 **속성 필드**로 들어 있는 레이어를 찾아 sqlite3 로 직접
    읽는다 (지오메트리 파싱·GDAL 불필요)."""
    import sqlite3
    cn = sqlite3.connect(path)
    try:
        try:
            tabs = [r[0] for r in cn.execute(
                "SELECT table_name FROM gpkg_contents WHERE data_type='features'")]
        except sqlite3.Error:
            tabs = [r[0] for r in cn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
        tab = None
        for t in tabs:
            cols = {r[1].lower() for r in cn.execute(f'PRAGMA table_info("{t}")')}
            if {'utc', 'lon', 'lat'} <= cols:
                tab = t
                break
        if tab is None:
            print(f'  [warn] {os.path.basename(path)}: utc/lon/lat 필드를 가진 '
                  f'레이어가 없어 건너뜀 (레이어: {tabs})')
            return []
        cols = {r[1].lower(): r[1] for r in cn.execute(f'PRAGMA table_info("{tab}")')}

        def c(name):
            return cols.get(name)
        sel = [c('utc'), c('cst'), c('lon'), c('lat'), c('speed_kn'),
               c('course_deg'), c('heading_deg'), c('turn_rate'), c('nav_status')]
        q = ', '.join(f'"{s}"' if s else 'NULL' for s in sel)
        out = []
        for row in cn.execute(f'SELECT {q} FROM "{tab}"'):
            utc, cst, lon, lat, sog, cog, hdg, rot, sta = row
            t = _parse_utc(utc if isinstance(utc, str) else str(utc))
            try:
                lon, lat = float(lon), float(lat)
            except (TypeError, ValueError):
                continue
            if t is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
                continue

            def num(v):
                try:
                    return float(v) if v is not None and str(v).strip() != '' else None
                except (TypeError, ValueError):
                    return None
            out.append({
                'lon': lon, 'lat': lat, 't': t,
                'cst': (cst or '').strip() if isinstance(cst, str) else '',
                'sog': num(sog), 'cog': num(cog), 'hdg': num(hdg), 'rot': num(rot),
                'status': (sta or '').strip() if isinstance(sta, str) else '',
                'src': os.path.basename(path),
            })
        return out
    finally:
        cn.close()


def build(recs, hours=1.0, ship='PANSTAR ACRO'):
    recs.sort(key=lambda r: r['t'])
    # 같은 UTC 시각 중복 제거 (파일 간 겹침)
    dedup, seen = [], set()
    for r in recs:
        k = r['t'].strftime('%Y%m%d%H%M%S')
        if k in seen:
            continue
        seen.add(k)
        dedup.append(r)
    recs = dedup
    if not recs:
        raise SystemExit('유효한 기록이 없습니다')

    # ── 1시간 대표점: 정시(또는 hours 간격 격자)에 가장 가까운 기록
    step = timedelta(hours=hours)
    t0 = recs[0]['t'].replace(minute=0, second=0, microsecond=0)
    grid = t0
    hourly = []
    j = 0
    while grid <= recs[-1]['t'] + step:
        # grid 에 가장 가까운 기록 (±step/2 이내)
        while j + 1 < len(recs) and abs(recs[j + 1]['t'] - grid) <= abs(recs[j]['t'] - grid):
            j += 1
        if abs(recs[j]['t'] - grid) <= step / 2:
            if not hourly or hourly[-1] is not recs[j]:
                hourly.append(recs[j])
        grid += step

    # ── 구간 평균속력 (대표점 사이)
    feats = []
    prev = None
    for i, r in enumerate(hourly):
        seg_kn = None
        if prev is not None:
            dt_h = (r['t'] - prev['t']).total_seconds() / 3600
            if dt_h > 0:
                seg_kn = haversine_km(prev['lon'], prev['lat'], r['lon'], r['lat']) / 1.852 / dt_h
        feats.append({
            'type': 'Feature',
            'properties': {
                'kind': 'hourly', 'idx': i,
                'utc': r['t'].strftime('%Y-%m-%d %H:%M:%S'),
                'cst': r['cst'], 'lon': round(r['lon'], 6), 'lat': round(r['lat'], 6),
                'sog_kn': r['sog'], 'cog': r['cog'], 'heading': r['hdg'],
                'status': r['status'],
                'seg_kn': round(seg_kn, 2) if seg_kn is not None else None,
            },
            'geometry': {'type': 'Point', 'coordinates': [r['lon'], r['lat']]},
        })
        prev = r

    # ── 전체 항적 선 + 거리
    total_km = 0.0
    for a, b in zip(recs, recs[1:]):
        total_km += haversine_km(a['lon'], a['lat'], b['lon'], b['lat'])
    line = {
        'type': 'Feature',
        'properties': {'kind': 'track', 'ship': ship,
                       't_start': recs[0]['t'].strftime('%Y-%m-%d %H:%M:%S'),
                       't_end': recs[-1]['t'].strftime('%Y-%m-%d %H:%M:%S'),
                       'n_records': len(recs), 'total_km': round(total_km, 1)},
        'geometry': {'type': 'LineString',
                     'coordinates': [[round(r['lon'], 6), round(r['lat'], 6)] for r in recs]},
    }

    # ── 속력 통계 (예상 위치 계산용)
    last = recs[-1]
    def avg_kn(since):
        d = 0.0; h = 0.0
        for a, b in zip(recs, recs[1:]):
            if b['t'] < since:
                continue
            dt = (b['t'] - a['t']).total_seconds() / 3600
            if dt <= 0 or dt > 3:            # 큰 결측 구간 제외
                continue
            km = haversine_km(a['lon'], a['lat'], b['lon'], b['lat'])
            if km / 1.852 / dt < 1.0:        # 정박/표류 구간 제외
                continue
            d += km; h += dt
        return round(d / 1.852 / h, 2) if h > 0 else None
    avg24 = avg_kn(last['t'] - timedelta(hours=24))
    avg_all = avg_kn(recs[0]['t'])

    last_feat = {
        'type': 'Feature',
        'properties': {'kind': 'last', 'utc': last['t'].strftime('%Y-%m-%d %H:%M:%S'),
                       'cst': last['cst'], 'sog_kn': last['sog'], 'cog': last['cog'],
                       'heading': last['hdg'], 'status': last['status']},
        'geometry': {'type': 'Point', 'coordinates': [last['lon'], last['lat']]},
    }
    fc = {
        'type': 'FeatureCollection',
        'properties': {
            'ship': ship, 'hours': hours,
            't_start': line['properties']['t_start'], 't_end': line['properties']['t_end'],
            'n_records': len(recs), 'n_hourly': len(feats), 'total_km': round(total_km, 1),
            'sog_last_kn': last['sog'], 'avg_kn_24h': avg24, 'avg_kn_underway': avg_all,
            'sources': sorted({r['src'] for r in recs}),
            'generated': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        },
        'features': [line, last_feat] + feats,
    }
    return fc


def main(argv=None):
    ap = argparse.ArgumentParser(description='선박 항적 CSV -> GeoJSON')
    ap.add_argument('--glob', default=os.path.join(WEB, 'data', 'PANSTAR*.csv'),
                    help='입력 CSV 글롭 (기본 web/data/PANSTAR*.csv)')
    ap.add_argument('--gpkg-glob', default=os.path.join(WEB, 'data', 'PANSTAR*.gpkg'),
                    help='입력 GeoPackage 글롭 (기본 web/data/PANSTAR*.gpkg; '
                         "'' 이면 gpkg 는 읽지 않음)")
    ap.add_argument('--out', default=os.path.join(WEB, 'PANSTAR_ACRO_track.geojson'),
                    help='출력 GeoJSON (기본 web/PANSTAR_ACRO_track.geojson)')
    ap.add_argument('--hours', type=float, default=1.0, help='대표점 간격(시간, 기본 1)')
    ap.add_argument('--ship', default='PANSTAR ACRO')
    a = ap.parse_args(argv if argv is not None else _main_argv())

    files = sorted(glob.glob(a.glob))
    gfiles = sorted(glob.glob(a.gpkg_glob)) if a.gpkg_glob else []
    if not files and not gfiles:
        print(f'입력 없음: {a.glob} / {a.gpkg_glob}')
        return 1
    recs = []
    for f in files:
        rs = _read_csv(f)
        print(f'  {os.path.basename(f)}: {len(rs)}건')
        recs += rs
    for f in gfiles:
        rs = _read_gpkg(f)
        print(f'  {os.path.basename(f)}: {len(rs)}건 (gpkg)')
        recs += rs
    fc = build(recs, hours=a.hours, ship=a.ship)
    with open(a.out, 'w', encoding='utf-8') as fp:
        json.dump(fc, fp, ensure_ascii=False, separators=(',', ':'))
    p = fc['properties']
    print(f"저장: {a.out}\n  기록 {p['n_records']}건 (중복 제거) · {p['t_start']} ~ {p['t_end']} UTC"
          f"\n  {a.hours:g}시간 대표점 {p['n_hourly']}개 · 항적 {p['total_km']:,} km"
          f"\n  마지막 SOG {p['sog_last_kn']} kn · 최근24h 평균 {p['avg_kn_24h']} kn · "
          f"항해중 평균 {p['avg_kn_underway']} kn")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
