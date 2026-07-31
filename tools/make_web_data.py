# -*- coding: utf-8 -*-
"""utils 파이프라인 산출물 -> 웹 뷰어용 경량 COG + catalog/descriptions JSON.

무엇을 하는가
--------------
1. `SRC_ROOT`(기본 E:/workspace2026/arctic/test_data/Data_Out) 의 **모델 7종**
   폴더에서 GeoTIFF 를 찾아 변수별 시계열로 묶는다.
2. 각 프레임을 지도와 같은 **EPSG:3413 북극 격자**로 재투영하고, 변수 레지스트리의
   표출범위(vmin/vmax)로 **Byte(1..255) 스케일**해 COG 로 저장한다
   (byte 0 = nodata = 투명). float32 원본 대비 용량이 1/10 이하로 줄고,
   기존 위성자료 항목과 같은 `kind:"palette", enc:"linear"` 경로로 그려진다.
3. 변수별 미리보기 PNG(설명 패널용)를 만든다.
4. `data/catalog.json` 과 `data/descriptions.json` 에 모델 항목을 갱신한다.
   기존 위성자료 항목은 그대로 두고, `m_` 로 시작하는 모델 항목만 교체한다.
5. `data/route_nsr.geojson` (항해 경로) 도 함께 갱신한다.

왜 재투영이 필요한가
--------------------
뷰어(index.html)는 COG 가 **EPSG:3413** 이라고 가정하고 bbox 를 가상좌표로
매핑한다. TOPAZ5·neXtSIM-F·RIOPS·GIOPS·MET-AICE 는 파이프라인이 극사영(PS)
/LAEA/경위도로만 산출하므로 여기서 3413 으로 맞춘다.
(utils 의 process json 에 arctic + EPSG:3413 을 추가해 두면, 다음 실행부터는
파이프라인이 바로 3413 산출물을 만들고 이 스크립트는 재투영을 건너뛴다.)

사용
----
    python make_web_data.py                     # 전체 모델·전체 변수
    python make_web_data.py --models topaz5_1d riops_2d
    python make_web_data.py --vars siconc sithick
    python make_web_data.py --lat-min 60 --dry-run
    python make_web_data.py --src E:/other/Data_Out

필요: gdal(osgeo), numpy, pillow
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
DEFAULT_SRC = r'E:/workspace2026/arctic/test_data/Data_Out'

EPSG3413_PROJ4 = ('+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +k=1 +x_0=0 '
                  '+y_0=0 +datum=WGS84 +units=m +no_defs')


def epsg3413_wkt():
    """EPSG:3413 WKT (osr 사용, 실패 시 proj4 문자열)."""
    try:
        from osgeo import osr
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(3413)
        return srs.ExportToWkt()
    except Exception:                                          # noqa: BLE001
        return EPSG3413_PROJ4

# 위도 하한별 EPSG:3413 반경(m) — 출력 격자 범위 결정용
LAT_RADIUS = {45: 5132000, 50: 4511000, 55: 3909000, 60: 3323000, 66: 2637000}

# ---------------------------------------------------------------- 변수 메타
# (한글명, 단위, vmin, vmax, LUT) — utils 각 모델 *_common.py 의 VARIABLES 기준
_ICE = 'ice'
_FB = 'freeboard'
_TH = 'thermal'
VAR_META = {
    # 해빙
    'siconc':   ('해빙농도', '', 0.0, 1.0, _ICE),
    'iiceconc': ('해빙농도', '', 0.0, 1.0, _ICE),
    'SIC':      ('해빙농도', '%', 0.0, 100.0, _ICE),
    'sithick':  ('해빙두께', 'm', 0.0, 5.0, _FB),
    'iicevol':  ('해빙부피/면적 (평균두께)', 'm', 0.0, 5.0, _FB),
    'sisnthick': ('적설두께', 'm', 0.0, 1.0, _FB),
    'isnowvol': ('적설부피/면적', 'm', 0.0, 1.0, _FB),
    'siage':    ('해빙 연령', '', 0.0, 5.0, _FB),
    'fy':       ('일년빙 면적비', '', 0.0, 1.0, _ICE),
    'siconc_my': ('다년빙 농도', '', 0.0, 1.0, _ICE),
    'siconc_young': ('신생빙 농도', '', 0.0, 1.0, _ICE),
    'si_ridge_ratio': ('빙맥 부피비', '', 0.0, 1.0, _FB),
    'sialb':    ('해빙 알베도', '', 0.0, 1.0, 'gray'),
    'iicesurftemp': ('빙 표면온도', '°C', -40.0, 0.0, _TH),
    'iicepressure': ('빙 내부압력', 'N/m', 0.0, 100000.0, 'gray'),
    'iicestrength': ('빙 강도', 'N/m', 0.0, 100000.0, 'gray'),
    'iicedivergence': ('빙 발산', '1/s', -1e-5, 1e-5, _TH),
    'iiceshear': ('빙 전단', '1/s', 0.0, 2e-5, 'gray'),
    # 해빙 표류
    'vxsi': ('해빙 표류 x', 'm/s', -0.5, 0.5, _TH),
    'vysi': ('해빙 표류 y', 'm/s', -0.5, 0.5, _TH),
    'usi':  ('해빙 표류 동향', 'm/s', -0.5, 0.5, _TH),
    'vsi':  ('해빙 표류 북향', 'm/s', -0.5, 0.5, _TH),
    'itzocrtx': ('해빙 이동 x', 'm/s', -0.5, 0.5, _TH),
    'itmecrty': ('해빙 이동 y', 'm/s', -0.5, 0.5, _TH),
    # 해양
    'zos':      ('해수면고도', 'm', -2.0, 2.0, _TH),
    'sossheig': ('해수면고도 (조석 포함)', 'm', -2.0, 2.0, _TH),
    'thetao':   ('수온', '°C', -2.0, 30.0, _TH),
    'votemper': ('표층 수온 (0.5 m)', '°C', -2.0, 30.0, _TH),
    'so':       ('염분', '1e-3', 25.0, 38.0, _TH),
    'vosaline': ('표층 염분 (0.5 m)', '1e-3', 25.0, 38.0, _TH),
    'vxo':  ('표층 해류 x', 'm/s', -1.0, 1.0, _TH),
    'vyo':  ('표층 해류 y', 'm/s', -1.0, 1.0, _TH),
    'uo':   ('동향 해류', 'm/s', -1.0, 1.0, _TH),
    'vo':   ('북향 해류', 'm/s', -1.0, 1.0, _TH),
    'vozocrtx': ('표층 해류 x (0.5 m)', 'm/s', -1.0, 1.0, _TH),
    'vomecrty': ('표층 해류 y (0.5 m)', 'm/s', -1.0, 1.0, _TH),
    'mlotst': ('혼합층 두께', 'm', 0.0, 500.0, _TH),
    'somixhgt': ('혼합층 깊이 (turbocline)', 'm', 0.0, 500.0, _TH),
    'sokaraml': ('혼합층 깊이 (밀도)', 'm', 0.0, 500.0, _TH),
    'bottomT': ('저층 수온', '°C', -2.0, 10.0, _TH),
    'tob': ('저층 수온', '°C', -2.0, 10.0, _TH),
    'sob': ('저층 염분', '1e-3', 25.0, 38.0, _TH),
    'pbo': ('해저 압력', 'dbar', 0.0, 60000.0, 'gray'),
    'wo':  ('수직 유속', 'm/s', -1e-4, 1e-4, _TH),
}
# TOPAZ5 는 수온/염분 표출범위가 다르다 (극지 전용 제품)
VAR_META_OVERRIDE = {
    ('topaz5_1d', 'thetao'): ('수온', '°C', -2.0, 12.0, _TH),
    ('topaz5_1d', 'so'): ('염분', '1e-3', 25.0, 36.0, _TH),
    ('topaz5_1d', 'siage'): ('해빙 연령', 'day', 0.0, 5.0, _FB),
    ('nextsim_hm', 'siage'): ('해빙 연령', 'year', 0.0, 5.0, _FB),
}

# 항행 유용도: 2 = 직접, 1 = 보조, 0 = 참고
NAV_RANK = {
    'siconc': 2, 'iiceconc': 2, 'SIC': 2, 'sithick': 2, 'iicevol': 2,
    'sisnthick': 2, 'isnowvol': 2, 'siage': 2, 'fy': 2, 'siconc_my': 2,
    'siconc_young': 2, 'si_ridge_ratio': 2, 'vxsi': 2, 'vysi': 2, 'usi': 2,
    'vsi': 2, 'itzocrtx': 2, 'itmecrty': 2, 'iicepressure': 2,
    'iicestrength': 2, 'iicedivergence': 2, 'iiceshear': 2, 'iicesurftemp': 2,
    'zos': 1, 'sossheig': 1, 'thetao': 1, 'votemper': 1, 'vxo': 1, 'vyo': 1,
    'uo': 1, 'vo': 1, 'vozocrtx': 1, 'vomecrty': 1, 'mlotst': 1,
    'somixhgt': 1, 'sokaraml': 1, 'bottomT': 1, 'tob': 1,
}
NAV_TAG = {2: '★ 항행 직접', 1: '◆ 항행 보조', 0: '· 참고'}

# ---------------------------------------------------------------- 모델 정의
D8 = r'(?P<date>\d{8})'
RC = r'(?P<region>full|arctic)_(?P<crs>PS|LAEA|EPSG4326|EPSG3413)'

MODELS = {
    'topaz5_1d': dict(
        no=1, model='TOPAZ5', group='① TOPAZ5 — CMEMS Arctic (10일)',
        org='NERSC / MET Norway (CMEMS ARC MFC)', res_m=6000, axis='date',
        grid='극사영 6.25 km', fc='기준일 + 예보 10일 (일평균)',
        re=re.compile(r'^TOPAZ5_(?P<ds>[A-Za-z0-9-]+)_(?P<var>[A-Za-z0-9]+)_'
                      r'NH_[A-Za-z0-9.-]+_' + D8 + '_' + RC + r'(?P<cog>_cog)?\.tif$'),
    ),
    'nextsim_hm': dict(
        no=2, model='neXtSIM-F', group='② neXtSIM-F — CMEMS Arctic 해빙 (D+9)',
        org='NERSC / MET Norway (CMEMS ARC MFC)', res_m=4000, axis='date',
        grid='극사영 3 km (실효 ~10 km)', fc='기준일 + 예보 9일 (시간평균 -> 일평균)',
        re=re.compile(r'^NEXTSIM_(?P<ds>[A-Za-z0-9-]+)_(?P<var>[A-Za-z0-9_]+?)_'
                      r'NH_[A-Za-z0-9.-]+_' + D8 + '_' + RC + r'(?P<cog>_cog)?\.tif$'),
    ),
    'riops_2d': dict(
        no=3, model='RIOPS', group='③ RIOPS — 캐나다 지역 (84시간)',
        org='ECCC / CCMEP (MSC Datamart)', res_m=5000, axis='run_lead_h',
        grid='극사영 5 km (ps5km60N)', fc='run 00/06/12/18Z, 리드 0~84시간',
        re=re.compile(r'^RIOPS_(?P<var>[A-Za-z0-9]+)_NH_[A-Za-z0-9.-]+_'
                      + D8 + r'T(?P<hh>\d{2})Z_P(?P<lead>\d{3})_' + RC
                      + r'(?P<cog>_cog)?\.tif$'),
    ),
    'met_aice': dict(
        no=4, model='MET-AICE', group='④ MET-AICE — 딥러닝 SIC (D+10)',
        org='MET Norway (THREDDS)', res_m=5000, axis='run_lead_d',
        grid='LAEA 5 km (유럽 북극)', fc='생산일 기준 D+1 ~ D+10',
        re=re.compile(r'^AICE_(?P<var>[A-Za-z0-9]+)_NH_[A-Za-z0-9.-]+_'
                      + D8 + r'T(?P<hh>\d{2})Z_D(?P<lead>\d+)_' + RC
                      + r'(?P<cog>_cog)?\.tif$'),
    ),
    'giops_2d': dict(
        no=5, model='GIOPS', group='⑤ GIOPS — 캐나다 전지구 (240시간)',
        org='ECCC / CCMEP (MSC Datamart)', res_m=5000, axis='run_lead_h',
        grid='극사영 5 km (ps5km60N)', fc='run 00/12Z, 분석 + 리드 0~240시간',
        re=re.compile(r'^GIOPS_(?P<var>[A-Za-z0-9]+)_NH_[A-Za-z0-9.-]+_'
                      + D8 + r'T(?P<hh>\d{2})Z_(?:P(?P<lead>\d{3})|Anal(?P<anal>\d{3}))_'
                      + RC + r'(?P<cog>_cog)?\.tif$'),
    ),
    'foam_gl4': dict(
        no=6, model='FOAM', group='⑥ FOAM — UK Met Office 전지구 (7일)',
        org='UK Met Office (AWS Open Data)', res_m=20000, axis='valid_bulletin',
        grid='정규 경위도 1/4° (GL4)', fc='생산일 세트의 유효일 (-2 ~ +7일)',
        re=re.compile(r'^FOAM_(?P<var>[A-Za-z0-9]+)_(?P<reg4>GL4|GLO|NH)_'
                      r'[A-Za-z0-9.-]+_dm(?P<date>\d{8})_b(?P<bull>\d{8})_'
                      + RC + r'(?P<cog>_cog)?\.tif$'),
    ),
    'glo12_1d': dict(
        no=7, model='GLO12', group='⑦ GLO12 — CMEMS 전지구 (10일)',
        org="Mercator Ocean Int'l (CMEMS GLO MFC)", res_m=9000, axis='date',
        grid='정규 경위도 1/12°', fc='기준일 + 예보 10일 (일평균)',
        re=re.compile(r'^GLO12_(?P<ds>[A-Za-z0-9-]+)_(?P<var>[A-Za-z0-9]+)_'
                      r'GLO_[A-Za-z0-9.-]+_' + D8 + '_' + RC + r'(?P<cog>_cog)?\.tif$'),
    ),
}

# 소스 우선순위: 넓은 영역(full) + 원본 투영 먼저. 3413 이 있으면 최우선(재투영 불필요)
SRC_PREF = [('full', 'EPSG3413'), ('arctic', 'EPSG3413'),
            ('full', 'PS'), ('full', 'LAEA'), ('arctic', 'PS'), ('arctic', 'LAEA'),
            ('full', 'EPSG4326'), ('arctic', 'EPSG4326')]

LUTS = {
    'freeboard': [(8, 29, 88), (34, 94, 168), (65, 182, 196), (199, 233, 180),
                  (254, 204, 92), (227, 26, 28)],
    'thermal': [(20, 20, 120), (60, 120, 216), (240, 240, 240), (245, 150, 60),
                (170, 10, 10)],
    'ice': [(10, 30, 80), (40, 110, 180), (150, 205, 235), (255, 255, 255)],
    'gray': [(0, 0, 0), (255, 255, 255)],
}


def lut_rgb(name: str, t: float):
    a = LUTS.get(name, LUTS['gray'])
    t = 0.0 if t != t else max(0.0, min(1.0, t))
    p = t * (len(a) - 1)
    i = min(len(a) - 2, int(p))
    f = p - i
    return tuple(int(round(a[i][c] * (1 - f) + a[i + 1][c] * f)) for c in range(3))


# ---------------------------------------------------------------- 시간축
def frame_time(cfg: dict, g: dict):
    """(frame_id, ISO 시각, 표시 라벨) — 모델별 시간축을 실제 UTC 시각으로."""
    d = g['date']
    base = datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), tzinfo=timezone.utc)
    axis = cfg['axis']
    if axis == 'date':
        t = base + timedelta(hours=12)              # 일평균 중앙시각
        return d, t, f'{d[4:6]}-{d[6:8]}'
    if axis == 'run_lead_h':
        hh = int(g.get('hh') or 0)
        lead = int(g.get('lead') or g.get('anal') or 0)
        t = base + timedelta(hours=hh + lead)
        fid = f'{d}T{hh:02d}Z_' + ('Anal000' if g.get('anal') is not None
                                   else f'P{lead:03d}')
        return fid, t, f'+{lead}h ({t.strftime("%m-%d %HZ")})'
    if axis == 'run_lead_d':
        hh = int(g.get('hh') or 0)
        lead = int(g.get('lead') or 0)
        t = base + timedelta(hours=hh) + timedelta(days=lead, hours=12)
        return f'{d}T{hh:02d}Z_D{lead}', t, f'D+{lead} ({t.strftime("%m-%d")})'
    if axis == 'valid_bulletin':
        b = g['bull']
        t = base + timedelta(hours=12)
        off = (base - datetime(int(b[:4]), int(b[4:6]), int(b[6:8]),
                               tzinfo=timezone.utc)).days
        sign = f'+{off}' if off >= 0 else str(off)
        return f'dm{d}_b{b}', t, f'{d[4:6]}-{d[6:8]} (b{sign}d)'
    raise ValueError(axis)


# ---------------------------------------------------------------- 스캔
def scan(src_root: str, model_keys, var_filter):
    """모델별 { var: { frame_id: {src, t, label, pref} } } 수집."""
    found = {}
    for mk in model_keys:
        cfg = MODELS[mk]
        folder = os.path.join(src_root, mk)
        if not os.path.isdir(folder):
            print(f'  [skip] 폴더 없음: {folder}')
            continue
        per_var: dict = {}
        for fn in os.listdir(folder):
            if not fn.lower().endswith('.tif'):
                continue
            m = cfg['re'].match(fn)
            if not m:
                continue
            g = m.groupdict()
            var = g['var']
            if var_filter and var not in var_filter:
                continue
            pair = (g['region'], g['crs'])
            if pair not in SRC_PREF:
                continue
            pref = SRC_PREF.index(pair)
            # _cog.tif 를 같은 우선순위에서 먼저 (오버뷰 포함이라 읽기 빠름)
            pref = pref * 2 + (0 if g.get('cog') else 1)
            fid, t, label = frame_time(cfg, g)
            slot = per_var.setdefault(var, {})
            cur = slot.get(fid)
            if cur is None or pref < cur['pref']:
                slot[fid] = {'src': os.path.join(folder, fn), 'pref': pref,
                             't': t, 'label': label,
                             'region': g['region'], 'crs': g['crs']}
        if per_var:
            found[mk] = per_var
    return found


# ---------------------------------------------------------------- 변환
def warp_to_byte(gdal, np, src: str, dst: str, *, bounds, res_m: int,
                 vmin: float, vmax: float, srs_wkt: str, quiet=True):
    """EPSG:3413 격자로 재투영 -> Byte(0=nodata, 1..255=vmin..vmax) COG."""
    warp_opts = gdal.WarpOptions(
        format='MEM', dstSRS=srs_wkt, outputBounds=bounds,
        outputBoundsSRS=srs_wkt, xRes=res_m, yRes=res_m,
        resampleAlg=gdal.GRA_Average, dstNodata=-32767.0,
        outputType=gdal.GDT_Float32, multithread=True,
    )
    if quiet:
        gdal.PushErrorHandler('CPLQuietErrorHandler')
    try:
        mem = gdal.Warp('', src, options=warp_opts)
    finally:
        if quiet:
            gdal.PopErrorHandler()
    if mem is None:
        raise RuntimeError(f'warp 실패: {src}')

    band = mem.GetRasterBand(1)
    arr = band.ReadAsArray().astype('float32')
    nod = band.GetNoDataValue()
    gt, prj = mem.GetGeoTransform(), mem.GetProjection()
    ny, nx = arr.shape
    mem = None

    bad = ~np.isfinite(arr)
    if nod is not None:
        bad |= (arr == nod)
    bad |= (arr < -1e30) | (arr > 1e30)
    span = (vmax - vmin) or 1.0
    scaled = (arr - vmin) / span
    np.clip(scaled, 0.0, 1.0, out=scaled)
    out = (1 + np.rint(scaled * 254)).astype('uint8')
    out[bad] = 0
    valid = int((~bad).sum())

    drv = gdal.GetDriverByName('GTiff')
    tmp = dst + '.tmp.tif'
    ds = drv.Create(tmp, nx, ny, 1, gdal.GDT_Byte,
                    options=['COMPRESS=DEFLATE', 'TILED=YES', 'ZLEVEL=9'])
    ds.SetGeoTransform(gt)
    ds.SetProjection(prj)
    b = ds.GetRasterBand(1)
    b.WriteArray(out)
    b.SetNoDataValue(0)
    b.SetMetadata({'VMIN': str(vmin), 'VMAX': str(vmax)})
    b.FlushCache()
    ds = None

    made = False
    if gdal.GetDriverByName('COG') is not None:
        try:
            gdal.Translate(dst, tmp, format='COG',
                           creationOptions=['COMPRESS=DEFLATE', 'LEVEL=9',
                                            'BLOCKSIZE=512',
                                            'OVERVIEW_RESAMPLING=NEAREST'])
            made = True
        except Exception:
            made = False
    if not made:                      # COG 드라이버 없으면 오버뷰 붙인 GTiff
        ds = gdal.Open(tmp, gdal.GA_Update)
        ds.BuildOverviews('NEAREST', [2, 4, 8, 16])
        ds = None
        shutil.copyfile(tmp, dst)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return out, valid


def write_preview(np, Image, arr_byte, lut: str, path: str, width=420):
    """미리보기 PNG (설명 패널용) — byte 0 은 투명."""
    a = arr_byte
    step = max(1, a.shape[1] // width)
    a = a[::step, ::step]
    table = np.zeros((256, 4), dtype='uint8')
    for i in range(1, 256):
        table[i, :3] = lut_rgb(lut, (i - 1) / 254.0)
        table[i, 3] = 255
    rgba = table[a]
    Image.fromarray(rgba, 'RGBA').save(path, optimize=True)


# ---------------------------------------------------------------- 메인
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='모델 산출물 -> 웹 뷰어 데이터')
    ap.add_argument('--src', default=DEFAULT_SRC, help='원본 Data_Out 경로')
    ap.add_argument('--out', default=os.path.join(WEB, 'Data_Out'),
                    help='웹 Data_Out 경로')
    ap.add_argument('--models', nargs='*', default=list(MODELS),
                    help='처리할 모델 폴더 (기본 전체)')
    ap.add_argument('--vars', nargs='*', default=None, help='변수 제한')
    ap.add_argument('--lat-min', type=int, default=50, choices=sorted(LAT_RADIUS),
                    help='출력 격자 위도 하한 (기본 50)')
    ap.add_argument('--res', type=int, default=0,
                    help='출력 해상도(m) 강제 지정 (기본 모델별 자동)')
    ap.add_argument('--max-frames', type=int, default=0,
                    help='변수당 프레임 상한 (0 = 제한 없음)')
    ap.add_argument('--overwrite', action='store_true', help='기존 파일 재생성')
    ap.add_argument('--dry-run', action='store_true', help='변환 없이 목록만')
    a = ap.parse_args(argv)

    unknown = [m for m in a.models if m not in MODELS]
    if unknown:
        print(f'알 수 없는 모델: {unknown}\n사용 가능: {list(MODELS)}')
        return 2

    print(f'[make_web_data] src={a.src}\n                out={a.out}')
    found = scan(a.src, a.models, set(a.vars) if a.vars else None)
    if not found:
        print('처리할 자료가 없습니다. --src 경로를 확인하세요.')
        return 1

    total_frames = sum(len(f) for v in found.values() for f in v.values())
    print(f'  모델 {len(found)}종, 변수 {sum(len(v) for v in found.values())}개, '
          f'프레임 {total_frames}개')

    if a.dry_run:
        for mk, per_var in found.items():
            print(f'\n[{mk}] {MODELS[mk]["model"]}')
            for var in sorted(per_var):
                fr = per_var[var]
                one = next(iter(fr.values()))
                print(f'   {var:16s} {len(fr):3d} 프레임  '
                      f'source={one["region"]}/{one["crs"]}')
        return 0

    try:
        from osgeo import gdal
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        print(f'필요 패키지 없음: {exc}\n  conda activate <env> 후 실행하세요 '
              '(gdal, numpy, pillow)')
        return 1
    gdal.UseExceptions()

    R = LAT_RADIUS[a.lat_min]
    bounds = (-R, -R, R, R)
    srs_wkt = epsg3413_wkt()
    entries, descs = [], {}
    done = skipped = failed = 0
    bytes_out = 0

    for mk in a.models:
        if mk not in found:
            continue
        cfg = MODELS[mk]
        per_var = found[mk]
        odir = os.path.join(a.out, mk)
        os.makedirs(odir, exist_ok=True)
        res_m = a.res or cfg['res_m']
        print(f'\n[{mk}] {cfg["model"]} — 변수 {len(per_var)}개, '
              f'출력 {res_m} m / lat>={a.lat_min}')

        for var in sorted(per_var, key=lambda v: (-NAV_RANK.get(v, 0), v)):
            frames_in = per_var[var]
            meta = VAR_META_OVERRIDE.get((mk, var)) or VAR_META.get(var)
            if meta is None:
                print(f'   [skip] 표출범위 미등록 변수: {var}')
                continue
            kname, units, vmin, vmax, lut = meta
            order = sorted(frames_in.items(), key=lambda kv: kv[1]['t'])
            if a.max_frames:
                order = order[:a.max_frames]

            out_frames = []
            preview_done = False
            for fid, info in order:
                name = f'{cfg["model"].replace("-", "")}_{var}_{fid}_EPSG3413_cog.tif'
                dst = os.path.join(odir, name)
                rel = f'Data_Out/{mk}/{name}'
                try:
                    if a.overwrite or not os.path.isfile(dst):
                        arr, valid = warp_to_byte(gdal, np, info['src'], dst,
                                                  bounds=bounds, res_m=res_m,
                                                  vmin=vmin, vmax=vmax,
                                                  srs_wkt=srs_wkt)
                        if valid == 0:
                            os.remove(dst)
                            print(f'   [skip] 유효 화소 0: {name}')
                            continue
                        done += 1
                        if not preview_done:
                            write_preview(np, Image, arr, lut,
                                          os.path.join(odir, f'{cfg["model"].replace("-", "")}'
                                                             f'_{var}_preview.png'))
                            preview_done = True
                    else:
                        skipped += 1
                        preview_done = preview_done or os.path.isfile(
                            os.path.join(odir, f'{cfg["model"].replace("-", "")}'
                                               f'_{var}_preview.png'))
                    bytes_out += os.path.getsize(dst)
                    out_frames.append({'id': fid, 'cog': rel,
                                       't': info['t'].strftime('%Y-%m-%dT%H:%M:%SZ'),
                                       'label': info['label']})
                except Exception as exc:                       # noqa: BLE001
                    failed += 1
                    print(f'   [fail] {name}: {exc}')

            if not out_frames:
                continue
            eid = f'm_{mk}__{var}'
            rank = NAV_RANK.get(var, 0)
            entries.append({
                'id': eid, 'group': cfg['group'], 'model': cfg['model'],
                'name': f'{kname} ({var})', 'type': 'series', 'nav': rank,
                'kind': 'palette', 'enc': 'linear',
                'vmin': vmin, 'vmax': vmax, 'lut': lut, 'units': units,
                'desc': eid,
                'png': f'Data_Out/{mk}/{cfg["model"].replace("-", "")}_{var}_preview.png',
                'cog': out_frames[0]['cog'],
                'frames': out_frames,
            })
            t0, t1 = out_frames[0]['t'][:10], out_frames[-1]['t'][:10]
            descs[eid] = {
                'title': f'{cfg["model"]} — {kname} ({var})',
                'fields': [
                    ['모델', f'{cfg["model"]} · {cfg["org"]}'],
                    ['변수', f'{var} — {kname}'],
                    ['단위', units or '무차원'],
                    ['표출범위', f'{vmin} ~ {vmax}{(" " + units) if units else ""}'],
                    ['항행 활용', NAV_TAG[rank]],
                    ['원본 격자', cfg['grid']],
                    ['웹 격자', f'EPSG:3413 {res_m // 1000} km (위도 {a.lat_min}° 이북)'],
                    ['예측 구성', cfg['fc']],
                    ['프레임', f'{len(out_frames)}개 ({t0} ~ {t1})'],
                ],
                'note': ('원본 float32 를 표출범위 기준 Byte(1~255)로 스케일해 저장했다 — '
                         '셀값은 byte 에서 물리량으로 환산해 표시된다. '
                         '지도 아래 재생 막대로 예측 시간대를 넘기며 볼 수 있다.'),
                'caption': f'{cfg["model"]} {kname} — 첫 프레임 미리보기',
            }
            print(f'   {var:16s} {len(out_frames):3d} 프레임  '
                  f'{kname} [{vmin}~{vmax}{units}]')

    # ---------- catalog / descriptions 갱신 (기존 위성자료 항목 보존)
    dpath = os.path.join(WEB, 'data')
    os.makedirs(dpath, exist_ok=True)
    cpath = os.path.join(dpath, 'catalog.json')
    try:
        with open(cpath, encoding='utf-8') as f:
            cat = json.load(f)
    except (OSError, ValueError):
        cat = {'crs': 'EPSG:3413', 'entries': []}
    keep = [e for e in cat.get('entries', []) if not str(e.get('id', '')).startswith('m_')]
    cat['crs'] = 'EPSG:3413'
    cat['entries'] = keep + entries
    with open(cpath, 'w', encoding='utf-8') as f:
        json.dump(cat, f, ensure_ascii=False, indent=1)

    xpath = os.path.join(dpath, 'descriptions.json')
    try:
        with open(xpath, encoding='utf-8') as f:
            dd = json.load(f)
    except (OSError, ValueError):
        dd = {}
    for k in [k for k in dd if str(k).startswith('m_')]:
        dd.pop(k)
    dd.update(descs)
    with open(xpath, 'w', encoding='utf-8') as f:
        json.dump(dd, f, ensure_ascii=False, indent=1)

    # ---------- 항해 경로 GeoJSON
    try:
        sys.path.insert(0, HERE)
        import make_route_geojson as mr
        pts = mr.read_points(os.path.join(WEB, 'NSRpolytopoint.txt'))
        if pts:
            with open(os.path.join(dpath, 'route_nsr.geojson'), 'w',
                      encoding='utf-8') as f:
                json.dump(mr.build(pts), f, ensure_ascii=False,
                          separators=(',', ':'))
            print('\n[route] data/route_nsr.geojson 갱신')
    except Exception as exc:                                   # noqa: BLE001
        print(f'\n[route] 생성 실패(무시): {exc}')

    print(f'\n완료 — 새로 변환 {done}개, 재사용 {skipped}개, 실패 {failed}개')
    print(f'  모델 항목 {len(entries)}개, 웹 COG 총 {bytes_out / 1e6:,.1f} MB')
    print(f'  catalog: {cpath}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
