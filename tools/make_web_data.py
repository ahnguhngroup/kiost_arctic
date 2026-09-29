# -*- coding: utf-8 -*-
"""utils 파이프라인 산출물 -> 웹 뷰어용 경량 COG + catalog/descriptions JSON.

무엇을 하는가
--------------
0. **읽을 날짜 폴더 선택(--date)** — 기본 `folder`: Data_Out 의 각 제품 폴더
   (<제품>/yyyy/mm/dd)에 있는 **최종(최신) 날짜 폴더 하나**를 그대로 읽는다
   (모델별 날짜 폴더는 하나뿐이라고 가정; 여러 개면 최신을 쓰고 경고). 특정 기준일로
   맞추려면 today | yesterday | YYYYMMDD | latest 로 지정 — 그러면 아래 규칙대로
   그 날짜 폴더의 자료만 읽는다.
   기준일 폴더 = 예측 기준일(bulletin/run) 폴더. 유효일별 폴더로 저장되는 모델
   (neXtSIM-F·GLO12 등 파일명에 기준일이 없는 일평균 제품)은 기준일 ~ +lead_days
   폴더를 함께 읽어 예측 시계열을 완성한다. 옛 평면 배치 파일도 파일명 날짜로 같은
   기준을 적용한다.
1. `SRC_ROOT`(기본 E:/workspace2026/arctic/test_data/Data_Out) 의 **모델 7종**
   (topaz5_1d · nextsim_hm · riops_2d · met_aice · giops_2d · foam_gl4 · glo12_1d)
   폴더에서 GeoTIFF 를 찾아 변수별 시계열로 묶는다. **관측 자료**는 AMSR 계열
   (AMSR2/AMSR3 L2·L3·A25) + ASIP L3/L4 + Sentinel-3 IST(s3e_ist) 를 기준일 폴더에서
   그대로 복사한다 (SAT_PRODUCTS; VIIRS·ICESat-2 는 --sat-extra 지정 시에만).
2. 각 프레임을 지도와 같은 **EPSG:3413 북극 격자**로 재투영하고, 변수 레지스트리의
   표출범위(vmin/vmax)로 **Byte(1..255) 스케일**해 COG 로 저장한다
   (byte 0 = nodata = 투명). float32 원본 대비 용량이 1/10 이하로 줄고,
   기존 위성자료 항목과 같은 `kind:"palette", enc:"linear"` 경로로 그려진다.
   **출력 경로도 Data_Out 규칙을 따른다**: web/Data_Out/<모델>/yyyy/mm/dd/…
   (원본이 있던 날짜 폴더와 동일).
3. 변수별 미리보기 PNG(설명 패널용)를 만든다.
4. `data/catalog.json` 과 `data/descriptions.json` 에 모델 항목을 갱신한다.
   기존 위성자료 항목은 그대로 두고, `m_` 로 시작하는 모델 항목만 교체한다.
5. `data/route_nsr.geojson` (항해 경로) 도 함께 갱신한다.

용량 관리 (기본 동작)
--------------------
변환을 시작하기 전에 **web/Data_Out 아래를 모두 비운다** — 웹 폴더에는 선택한
기준일의 자료만 남아 용량이 최소가 된다. 비운 뒤 catalog 에서 파일이 사라진
항목(위성자료 포함)은 자동 제거된다(설명 json 은 보존 — 파이프라인이 web_catalog
로 다시 등록하면 그대로 살아난다). `--keep-others` 를 주면 모델 폴더만 비우고
위성자료 폴더는 남긴다. `--no-purge` 는 아무것도 지우지 않는다(이전 방식).
처리할 자료가 하나도 없으면 아무것도 지우지 않고 종료한다.

왜 재투영이 필요한가
--------------------
뷰어(index.html)는 COG 가 **EPSG:3413** 이라고 가정하고 bbox 를 가상좌표로
매핑한다. TOPAZ5·neXtSIM-F·RIOPS·GIOPS·MET-AICE 는 파이프라인이 극사영(PS)
/LAEA/경위도로만 산출하므로 여기서 3413 으로 맞춘다.
(utils 의 process json 에 arctic + EPSG:3413 을 추가해 두면, 다음 실행부터는
파이프라인이 바로 3413 산출물을 만들고 이 스크립트는 재투영을 건너뛴다.)

사용
----
    python make_web_data.py                     # 제품별 최종 날짜 폴더(--date folder), 전체
    python make_web_data.py --date 20260801     # 특정 기준일
    python make_web_data.py --date latest       # 모델 폴더에 있는 가장 최근 기준일
    python make_web_data.py --date yesterday --models topaz5_1d riops_2d
    python make_web_data.py --vars siconc sithick
    python make_web_data.py --lat-min 60 --dry-run
    python make_web_data.py --src E:/other/Data_Out
    python make_web_data.py --keep-others       # 위성자료 웹 폴더는 지우지 않음
    python make_web_data.py --no-purge          # 아무것도 지우지 않음(누적)

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

sys.path.insert(0, HERE)
from dated_dirs import date_of_name  # noqa: E402  (utils 공통 날짜 규칙)

# 기준일 태그 (파일명에 예측 기준일이 들어 있는 경우: <bul>b_ / _b<bul>)
_RE_BUL = re.compile(r'(?:^|_)(\d{8})b(?=_)|_b(\d{8})(?=[_.]|$)')
# 날짜 폴더 yyyy/mm/dd 판별
_RE_Y, _RE_MD = re.compile(r'^\d{4}$'), re.compile(r'^\d{2}$')

# ── 실행 옵션 직접 지정 ------------------------------------------------------
# bat(명령행)와 같은 옵션 문자열을 코드에서도 지정할 수 있다.
#   MAIN_ARGS = None                     -> bat/명령행 옵션을 그대로 사용 (기본)
#   MAIN_ARGS = '--date 20260801 ...'    -> 인자 없이 실행(IDE Run 등)하면 이 옵션 사용
# 명령행 인자가 하나라도 있으면 항상 명령행(bat)이 우선한다.
MAIN_ARGS = None


def _main_argv():
    """명령행 인자 우선, 없으면 MAIN_ARGS(코드 지정 옵션) 사용."""
    import shlex
    if len(sys.argv) > 1:
        return sys.argv[1:]
    if MAIN_ARGS:
        print(f'(MAIN_ARGS 사용: {MAIN_ARGS})')
        return shlex.split(MAIN_ARGS)
    return []

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

# 파일명 규칙 (2026-08-31 이후 신형: <기준일>b_<예측일…>, 구형도 함께 인식)
#   TOPAZ5  TOPAZ5_P1D-m_<var>_NH_6km_<bul>b_<valid>_<RC>
#   NEXTSIM NEXTSIM_hm_<var>_NH_3km_<bul>b_<valid>_<RC>          (구형: _<valid>_)
#   RIOPS   RIOPS_<var>_NH_5km_<bul>b_<valid>T<HH>Z_P<lead>_<RC>  (구형: <run>T<HH>Z_P<lead>)
#   AICE    AICE_<var>_NH_5km_<bul>b_<valid>_D<lead>_<RC>         (구형: <run>T<HH>Z_D<lead>)
#   GIOPS   GIOPS_<var>_NH_5km_<bul>b_<valid>T<HH>Z_(P<lead>|Anal000)_<RC>
#   FOAM    FOAM_<var>_<GL4|GLO|NH>_<res>_<bul>b_dm<valid>[_HHZ]_<RC> (구형: dm<valid>_b<bul>)
#   GLO12   GLO12_P1D-m_<var>_GLO_9km_<bul>b_<valid>_<RC>          (구형: _<valid>_)
# 그룹: date=예측(valid) 날짜, bul=기준일(있으면), hh=예측 시각(run 기준 구형은 run 시각),
#       lead/anal, vhh=신형 예측 시각
BUL = r'(?:(?P<bul>\d{8})b_)?'
MODELS = {
    'topaz5_1d': dict(
        no=1, model='TOPAZ5', group='① TOPAZ5 — CMEMS Arctic (10일)',
        org='NERSC / MET Norway (CMEMS ARC MFC)', res_m=6000, axis='date',
        grid='극사영 6.25 km', fc='기준일 + 예보 10일 (일평균)',
        re=re.compile(r'^TOPAZ5_(?P<ds>[A-Za-z0-9-]+)_(?P<var>[A-Za-z0-9]+)_'
                      r'NH_[A-Za-z0-9.-]+_' + BUL + D8 + r'(?:_b\d{8})?_' + RC + r'(?P<cog>_cog)?\.tif$'),
    ),
    # KIOST 단기 편차보정 (TOPAZ5 -> A25 관측 합성 기반, utils/topaz5_kiost)
    'topaz5_kiost_amsr3_amsr25': dict(
        no=2, model='TP3A3', group='② TP3A3 — KIOST 보정 (AMSR3 A25, 10일)',
        org='KIOST (TOPAZ5 + AMSR3 A25 편차보정)', res_m=6000, axis='date',
        grid='극사영 6.25 km (TOPAZ5 격자)', fc='기준일 + 예보 10일 (일평균, 편차보정)',
        re=re.compile(r'^TP3A3_(?P<ds>[A-Za-z0-9-]+)_(?P<var>[A-Za-z0-9]+)_'
                      r'NH_[A-Za-z0-9.-]+_' + BUL + D8 + '_' + RC + r'(?P<cog>_cog)?\.tif$'),
    ),
    'topaz5_kiost_amsr2_amsr25r': dict(
        no=3, model='TP3R', group='③ TP3R — KIOST 보정 (AMSR2 연구 A25R, 10일)',
        org='KIOST (TOPAZ5 + AMSR2 연구 A25R 편차보정)', res_m=6000, axis='date',
        grid='극사영 6.25 km (TOPAZ5 격자)', fc='기준일 + 예보 10일 (일평균, 편차보정)',
        re=re.compile(r'^TP3R_(?P<ds>[A-Za-z0-9-]+)_(?P<var>[A-Za-z0-9]+)_'
                      r'NH_[A-Za-z0-9.-]+_' + BUL + D8 + '_' + RC + r'(?P<cog>_cog)?\.tif$'),
    ),
    'nextsim_hm': dict(
        no=4, model='neXtSIM-F', group='④ neXtSIM-F — CMEMS Arctic 해빙 (D+9)',
        org='NERSC / MET Norway (CMEMS ARC MFC)', res_m=4000, axis='date',
        grid='극사영 3 km (실효 ~10 km)', fc='기준일 + 예보 9일 (시간평균 -> 일평균)',
        re=re.compile(r'^NEXTSIM_(?P<ds>[A-Za-z0-9-]+)_(?P<var>[A-Za-z0-9_]+?)_'
                      r'NH_[A-Za-z0-9.-]+_' + BUL + D8 + '_' + RC + r'(?P<cog>_cog)?\.tif$'),
    ),
    'riops_2d': dict(
        no=5, model='RIOPS', group='⑤ RIOPS — 캐나다 지역 (84시간)',
        org='ECCC / CCMEP (MSC Datamart)', res_m=5000, axis='run_lead_h',
        grid='극사영 5 km (ps5km60N)', fc='run 00/06/12/18Z, 리드 0~84시간',
        re=re.compile(r'^RIOPS_(?P<var>[A-Za-z0-9]+)_NH_[A-Za-z0-9.-]+_' + BUL
                      + D8 + r'T(?P<hh>\d{2})Z_P(?P<lead>\d{3})_' + RC
                      + r'(?P<cog>_cog)?\.tif$'),
    ),
    # 기본 처리 제외 (2026-09-29, Data_Out_sample 25종 기준) — --models met_aice 로 명시 시 처리
    'met_aice': dict(
        inactive=True,
        no=9, model='MET-AICE', group='⑨ MET-AICE — 딥러닝 SIC (D+10)',
        org='MET Norway (THREDDS)', res_m=5000, axis='run_lead_d',
        grid='LAEA 5 km (유럽 북극)', fc='생산일 기준 D+1 ~ D+10',
        re=re.compile(r'^AICE_(?P<var>[A-Za-z0-9]+)_NH_[A-Za-z0-9.-]+_' + BUL
                      + D8 + r'(?:T(?P<hh>\d{2})Z)?_D(?P<lead>\d+)_' + RC
                      + r'(?P<cog>_cog)?\.tif$'),
    ),
    'giops_2d': dict(
        no=6, model='GIOPS', group='⑥ GIOPS — 캐나다 전지구 (240시간)',
        org='ECCC / CCMEP (MSC Datamart)', res_m=5000, axis='run_lead_h',
        grid='극사영 5 km (ps5km60N)', fc='run 00/12Z, 분석 + 리드 0~240시간',
        re=re.compile(r'^GIOPS_(?P<var>[A-Za-z0-9]+)_NH_[A-Za-z0-9.-]+_' + BUL
                      + D8 + r'T(?P<hh>\d{2})Z_(?:P(?P<lead>\d{3})|Anal(?P<anal>\d{3}))_'
                      + RC + r'(?P<cog>_cog)?\.tif$'),
    ),
    'foam_gl4': dict(
        no=7, model='FOAM', group='⑦ FOAM — UK Met Office 전지구 (7일)',
        org='UK Met Office (AWS Open Data)', res_m=20000, axis='valid_bulletin',
        grid='정규 경위도 1/4° (GL4)', fc='생산일 세트의 유효일 (-2 ~ +7일)',
        re=re.compile(r'^FOAM_(?P<var>[A-Za-z0-9]+)_(?P<reg4>GL4|GLO|NH)_'
                      r'[A-Za-z0-9.-]+_' + BUL + r'(?:dm|hi|oi)(?P<date>\d{8})'
                      r'(?:_(?P<hh>\d{2})Z)?(?:_b(?P<bull>\d{8}))?_'
                      + RC + r'(?P<cog>_cog)?\.tif$'),
    ),
    'glo12_1d': dict(
        no=8, model='GLO12', group='⑧ GLO12 — CMEMS 전지구 (10일)',
        org="Mercator Ocean Int'l (CMEMS GLO MFC)", res_m=9000, axis='date',
        grid='정규 경위도 1/12°', fc='기준일 + 예보 10일 (일평균)',
        re=re.compile(r'^GLO12_(?P<ds>[A-Za-z0-9-]+)_(?P<var>[A-Za-z0-9]+)_'
                      r'GLO_[A-Za-z0-9.-]+_' + BUL + D8 + '_' + RC + r'(?P<cog>_cog)?\.tif$'),
    ),
}
# 기본 처리 모델 = inactive 표시가 없는 것 (--models 로 명시하면 inactive 도 처리)
MODEL_DEFAULT = [k for k, v in MODELS.items() if not v.get('inactive')]

# ---------------------------------------------------------------- 위성(관측) 제품
# 파이프라인이 이미 EPSG:3413 (Byte 또는 float) COG 로 내보낸 관측 자료 — 재투영 없이
# **복사**만 한다. 기준일 폴더(Data_Out/<folder>/yyyy/mm/dd)의 **모든 파일**(스와스면
# 그날 전체 패스)을 각각 하나의 항목으로 등록한다: id = <제품id>__<COG stem>,
# title = 제품 제목, name = COG stem. series=True 제품(A25 합성)은 그날 파일을 프레임으로
# 묶은 시계열 1항목.
#
# 웹에 올리는 자료 범위 (2026-09-29, Data_Out_sample 25종 기준으로 재편):
#   관측 15 — AMSR2 연구 HSI(L2/L3/A25R 합성)·SIM, AMSR3 HSI(L2/L3/A25 합성)·SIM,
#             ASIP L3/L4, Sentinel-1 SAR, Sentinel-2 광학(RGB), Sentinel-3 IST,
#             VIIRS VNP29(NRT 스와스)·VJ129P1D(일별 타일)
#   기상 2  — GFS(0.25°) · WW3(북극 9 km)  [opt sec='wx' -> 뷰어 '기상' 섹션]
# 그 외(표준 SIC/SST/SSW, 연구 ASW/TIT/TSI, A25 SIC 합성 등)는 _SAT_INACTIVE 로
# 내려 두어 기본 처리에서 제외한다 (--sat-extra 로 개별 지정 시에만 처리).
_PCT_ICE = dict(kind='palette', enc='percent', vmin=0, vmax=100, lut='ice', units='%')
_SST = dict(kind='palette', enc='linear', vmin=-2, vmax=35, lut='thermal', units='°C')
_SSW = dict(kind='palette', enc='linear', vmin=0, vmax=30, lut='freeboard', units='m/s')
_ASW = dict(kind='palette', enc='linear', vmin=0, vmax=60, lut='freeboard', units='m/s')
_TIT = dict(kind='palette', enc='linear', vmin=0, vmax=20, lut='thermal', units='cm')
_TSI = dict(kind='palette', enc='classes')
_SIM = dict(kind='palette', enc='linear', vmin=-40, vmax=40, lut='thermal', units='cm/s')
_VNP29 = dict(kind='palette', enc='values', override=True,
              colors={'1': [43, 108, 176], '100': [215, 25, 28]})
_IST = dict(kind='palette', enc='linear', vmin=210, vmax=313, lut='thermal', units='K')
_FB = dict(kind='float', lut='freeboard', stretch=[2, 98], units='m')
# Sentinel-3 SL_2_IST (float GeoTIFF): 해빙비율 0..1, 빙표면온도 K
_S3_SIF = dict(kind='float', lut='ice', vmin=0, vmax=1, units='fraction')
_S3_IST = dict(kind='float', lut='thermal', vmin=240, vmax=280, units='K')
# Sentinel-1 EW GRDM 후방산란 (uint16 DN) — 파일별 2~98% 스트레치 회색조
_S1 = dict(kind='float', lut='gray', stretch=[2, 98], units='DN')
# Sentinel-2 트루컬러 — RGB.tif(EPSG4326 Byte 3밴드)를 3413 으로 재투영·축소 복사
_S2_RGB = dict(kind='rgb')
# GFS 0.25° / WW3 북극 9 km — arctic_EPSG3413 float COG 를 그대로 복사 (시계열)
_GFS_AWW = dict(kind='float', lut='freeboard', vmin=0, vmax=30, units='m/s')
_GFS_APR = dict(kind='float', lut='thermal', vmin=950, vmax=1050, units='hPa')
_GFS_ATM = dict(kind='float', lut='thermal', vmin=-30, vmax=25, units='°C')
_WW3_HS = dict(kind='float', lut='freeboard', vmin=0, vmax=8, units='m')
_WW3_TP = dict(kind='float', lut='thermal', vmin=0, vmax=20, units='s')

# (id, group, title, Data_Out 폴더, 파일 stem 패턴(fnmatch, _cog/.tif 제외), meta, 옵션)
#   옵션: series(그날 파일 -> 시계열 1항목) / model·nav(뷰어 예측 섹션 표시)
#         sec='wx'(뷰어 '기상' 섹션) / maxPx(렌더 상한) / rgb(RGB.tif 재투영 복사)
SAT_PRODUCTS = [
    # ══ 관측 (Data_Out_sample 기준 15종) ══════════════════════════════════
    # ── AMSR2 연구 HSI 라인: L2 스와스 -> L3 10 km -> A25R 합성 ──
    ('amsr2_l2_research_HSI', 'AMSR2 연구 HSI', 'AMSR2 L2 HSI 고해상 해빙 (스와스)',
     'amsr2_l2_research_HSI', 'HSI_L2_AMSR2_NH_swath_*_full_EPSG3413', _PCT_ICE, {}),
    ('amsr2_l3_research_HSI', 'AMSR2 연구 HSI', 'AMSR2 L3 HSI 10 km',
     'amsr2_l3_research_HSI', 'HSI_L3_AMSR2_NH_*_full_EPSG3413', _PCT_ICE, {}),
    ('a25r_amsr2_hsi', 'AMSR2 연구 HSI', 'AMSR2 A25R HSI 합성 (L2 + L3 백필)',
     'amsr2_amsr25r_l2_l3_hsi', 'HSI_A25R_AMSR2_NH_*_full_EPSG3413', _PCT_ICE,
     {'series': True}),
    # ── AMSR2 연구 SIM (해빙 이동, U/V/속력) ──
    ('amsr2_l3_research_SIM_U', 'AMSR2 연구 SIM', 'AMSR2 L3 SIM U성분',
     'amsr2_l3_research_SIM', 'SIM_L3_AMSR2_NH_*_U_full_EPSG3413', _SIM, {}),
    ('amsr2_l3_research_SIM_V', 'AMSR2 연구 SIM', 'AMSR2 L3 SIM V성분',
     'amsr2_l3_research_SIM', 'SIM_L3_AMSR2_NH_*_V_full_EPSG3413', _SIM, {}),
    ('amsr2_l3_research_SIM_SPD', 'AMSR2 연구 SIM', 'AMSR2 L3 SIM 속력',
     'amsr2_l3_research_SIM', 'SIM_L3_AMSR2_NH_*_SPD_full_EPSG3413',
     dict(kind='palette', enc='linear', vmin=0, vmax=40, lut='freeboard',
          units='cm/s'), {}),
    # ── AMSR3 표준 HSI 라인: L2 스와스 -> L3 10 km -> A25 합성 ──
    ('amsr3_l2_HSI', 'AMSR3 HSI', 'AMSR3 L2 HSI 고해상 해빙 (스와스)',
     'amsr3_l2_HSI', 'HSI_L2_AMSR3_NH_swath_*_full_EPSG3413', _PCT_ICE, {}),
    ('amsr3_l3_HSI', 'AMSR3 HSI', 'AMSR3 L3 HSI 10 km',
     'amsr3_l3_HSI', 'HSI_L3_AMSR3_NH_10km_*_full_EPSG3413', _PCT_ICE, {}),
    ('a25_amsr3_hsi', 'AMSR3 HSI', 'AMSR3 A25 HSI 합성 (L2 + L3 백필, 10 km)',
     'amsr3_amsr25_10_l2_l3_hsi', 'HSI_A25_AMSR3_NH_*_full_EPSG3413', _PCT_ICE,
     {'series': True}),
    # ── AMSR3 SIM (해빙 이동) ──
    ('amsr3_l3_SIM_U', 'AMSR3 SIM', 'AMSR3 L3 SIM U성분',
     'amsr3_l3_SIM', 'SIM_L3_AMSR3_NH_*_U_full_EPSG3413', _SIM, {}),
    ('amsr3_l3_SIM_V', 'AMSR3 SIM', 'AMSR3 L3 SIM V성분',
     'amsr3_l3_SIM', 'SIM_L3_AMSR3_NH_*_V_full_EPSG3413', _SIM, {}),
    ('amsr3_l3_SIM_SPD', 'AMSR3 SIM', 'AMSR3 L3 SIM 속력',
     'amsr3_l3_SIM', 'SIM_L3_AMSR3_NH_*_SPD_full_EPSG3413',
     dict(kind='palette', enc='linear', vmin=0, vmax=40, lut='freeboard',
          units='cm/s'), {}),
    # ── ASIP (DMI) ──
    ('asip_l3', 'ASIP', 'ASIP L3 해빙농도 0.5 km', 'asip_l3',
     'SIC_L3_ASIP_NH_500m_*_full_EPSG34??', _PCT_ICE, {'maxPx': 1400}),
    ('asip_l4', 'ASIP', 'ASIP L4 해빙농도 1 km', 'asip_l4',
     'SIC_L4_ASIP_NH_1km_*_full_EPSG34??', _PCT_ICE, {'maxPx': 1400}),
    # ── Sentinel-1 EW GRDM SAR 후방산란 (uint16 DN, 200 m) ──
    ('s1_hh', 'Sentinel-1 SAR', 'S1 SAR 후방산란 HH (스와스)', 's1',
     'S1?_EW_GRD?_*_hh_EPSG3413', _S1, {'maxPx': 1400}),
    ('s1_hv', 'Sentinel-1 SAR', 'S1 SAR 후방산란 HV (스와스)', 's1',
     'S1?_EW_GRD?_*_hv_EPSG3413', _S1, {'maxPx': 1400}),
    # ── Sentinel-2 트루컬러 (RGB.tif EPSG4326 -> 3413 재투영·축소 복사) ──
    ('s2_rgb', 'Sentinel-2 광학', 'S2 트루컬러 RGB (타일)', 's2',
     'S2?_MSIL2A_*_RGB', _S2_RGB, {'rgb': True, 'maxPx': 1400}),
    # ── Sentinel-3 SLSTR IST (EUMETSAT, s3_eumetsat 유틸 -> Data_Out/s3e_ist) ──
    ('s3e_ist_sif', 'Sentinel-3 IST', 'S3 SLSTR 해빙비율 (스와스)', 's3e_ist',
     'S3?_SL_2_IST____*_sea_ice_fraction_EPSG3413', _S3_SIF, {'maxPx': 1400}),
    ('s3e_ist_ist', 'Sentinel-3 IST', 'S3 SLSTR 빙표면온도 (스와스)', 's3e_ist',
     'S3?_SL_2_IST____*_surface_temperature_EPSG3413', _S3_IST, {'maxPx': 1400}),
    # ── VIIRS 해빙 분포 ──
    ('viirs_29', 'VIIRS', 'VNP29 해빙 분포 (NRT 스와스)', 'viirs_29_vnp_nrt',
     'SIC_A*_EPSG3413', _VNP29, {}),
    ('viirs_29p_vj1', 'VIIRS', 'VJ129P1D 일별 해빙 (타일)',
     'viirs_29pe_vj129p1d', 'VJ129P1D.A*_sic_EPSG3413', _VNP29, {}),
    # ══ 기상 (GFS·WW3, 뷰어 '기상' 섹션) ═════════════════════════════════
    ('gfs_aww', 'GFS 기상 (0.25도)', 'GFS 10 m 풍속', 'gfs',
     'GFS_aww_*_arctic_EPSG3413', _GFS_AWW, {'series': True, 'sec': 'wx'}),
    ('gfs_apr', 'GFS 기상 (0.25도)', 'GFS 해면기압', 'gfs',
     'GFS_apr_*_arctic_EPSG3413', _GFS_APR, {'series': True, 'sec': 'wx'}),
    ('gfs_atm', 'GFS 기상 (0.25도)', 'GFS 2 m 기온', 'gfs',
     'GFS_atm_*_arctic_EPSG3413', _GFS_ATM, {'series': True, 'sec': 'wx'}),
    ('ww3_swh', 'WW3 파랑 (9 km)', 'WW3 1차 너울 파고', 'ww3',
     'WW3_swh_*_arctic_EPSG3413', _WW3_HS, {'series': True, 'sec': 'wx'}),
    ('ww3_twh', 'WW3 파랑 (9 km)', 'WW3 전체 유의파고', 'ww3',
     'WW3_twh_*_arctic_EPSG3413', _WW3_HS, {'series': True, 'sec': 'wx'}),
    ('ww3_twp', 'WW3 파랑 (9 km)', 'WW3 전체 파주기', 'ww3',
     'WW3_twp_*_arctic_EPSG3413', _WW3_TP, {'series': True, 'sec': 'wx'}),
]
# 기본 처리 대상에서 제외한 제품 (--sat-extra <id> 로 개별 지정 시에만 처리)
#   2026-09-29 재편: 표준 SIC/SST/SSW·연구 ASW/TIT/TSI·A25 SIC 합성 계열을
#   Data_Out_sample 25종 기준에 따라 이곳으로 내림. VIIRS 나머지·ICESat-2 는 종전대로.
_SAT_INACTIVE = [
    # ── AMSR2 L2 (표준) ──
    ('amsr2_l2_SIC', 'AMSR2 L2 (표준)', 'AMSR2 L2 SIC 해빙농도', 'amsr2_l2_SIC',
     'SIC_L2_AMSR2_NH_swath_*_full_EPSG3413', _PCT_ICE, {}),
    ('amsr2_l2_SST', 'AMSR2 L2 (표준)', 'AMSR2 L2 SST 해수면온도', 'amsr2_l2_SST',
     'SST_L2_AMSR2_NH_swath_*_full_EPSG3413', _SST, {}),
    ('amsr2_l2_SSW', 'AMSR2 L2 (표준)', 'AMSR2 L2 SSW 해상풍', 'amsr2_l2_SSW',
     'SSW_L2_AMSR2_NH_swath_*_full_EPSG3413', _SSW, {}),
    ('amsr2_l2_research_ASW', 'AMSR2 L2 (연구)', 'AMSR2 L2 ASW 전천후 해상풍',
     'amsr2_l2_research_ASW', 'ASW_L2_AMSR2_NH_swath_*_full_EPSG3413', _ASW, {}),
    ('amsr2_l2_research_TIT', 'AMSR2 L2 (연구)', 'AMSR2 L2 TIT 박빙 두께',
     'amsr2_l2_research_TIT', 'TIT_L2_AMSR2_NH_swath_*_full_EPSG3413', _TIT, {}),
    ('amsr2_l2_research_TSI', 'AMSR2 L2 (연구)', 'AMSR2 L2 TSI 박빙 탐지',
     'amsr2_l2_research_TSI', 'TSI_L2_AMSR2_NH_swath_*_full_EPSG3413', _TSI, {}),
    # ── AMSR2 L3 (표준) ──
    ('amsr2_l3_10_SIC', 'AMSR2 L3 (표준)', 'AMSR2 L3 SIC 10 km', 'amsr2_l3_10_SIC',
     'SIC_L3_AMSR2_NH_10km_*_full_EPSG3413', _PCT_ICE, {}),
    ('amsr2_l3_25_SIC', 'AMSR2 L3 (표준)', 'AMSR2 L3 SIC 25 km', 'amsr2_l3_25_SIC',
     'SIC_L3_AMSR2_NH_25km_*_full_EPSG3413', _PCT_ICE, {}),
    ('amsr2_l3_10_SST', 'AMSR2 L3 (표준)', 'AMSR2 L3 SST 0.1도', 'amsr2_l3_10_SST',
     'SST_L3_AMSR2_*_full_EPSG3413', _SST, {}),
    ('amsr2_l3_25_SST', 'AMSR2 L3 (표준)', 'AMSR2 L3 SST 0.25도', 'amsr2_l3_25_SST',
     'SST_L3_AMSR2_*_full_EPSG3413', _SST, {}),
    ('amsr2_l3_10_SSW', 'AMSR2 L3 (표준)', 'AMSR2 L3 SSW 0.1도', 'amsr2_l3_10_SSW',
     'SSW_L3_AMSR2_*_full_EPSG3413', _SSW, {}),
    ('amsr2_l3_25_SSW', 'AMSR2 L3 (표준)', 'AMSR2 L3 SSW 0.25도', 'amsr2_l3_25_SSW',
     'SSW_L3_AMSR2_*_full_EPSG3413', _SSW, {}),
    ('amsr2_l3_research_ASW', 'AMSR2 L3 (연구)', 'AMSR2 L3 ASW 0.1도',
     'amsr2_l3_research_ASW', 'ASW_L3_AMSR2_*_full_EPSG3413', _ASW, {}),
    ('amsr2_l3_research_TIT', 'AMSR2 L3 (연구)', 'AMSR2 L3 TIT 박빙 두께',
     'amsr2_l3_research_TIT', 'TIT_L3_AMSR2_NH_*_full_EPSG3413', _TIT, {}),
    ('amsr2_l3_research_TSI', 'AMSR2 L3 (연구)', 'AMSR2 L3 TSI 박빙 탐지',
     'amsr2_l3_research_TSI', 'TSI_L3_AMSR2_NH_10km_*_full_EPSG3413', _TSI, {}),
    # ── AMSR3 L2 / L3 (표준 SIC 등) ──
    ('amsr3_l2_SIC', 'AMSR3 L2', 'AMSR3 L2 SIC 해빙농도', 'amsr3_l2_SIC',
     'SIC_L2_AMSR3_NH_swath_*_full_EPSG3413', _PCT_ICE, {}),
    ('amsr3_l2_SST', 'AMSR3 L2', 'AMSR3 L2 SST 해수면온도', 'amsr3_l2_SST',
     'SST_L2_AMSR3_NH_swath_*_full_EPSG3413', _SST, {}),
    ('amsr3_l2_SSW', 'AMSR3 L2', 'AMSR3 L2 SSW 해상풍', 'amsr3_l2_SSW',
     'SSW_L2_AMSR3_NH_swath_*_full_EPSG3413', _SSW, {}),
    ('amsr3_l2_ASW', 'AMSR3 L2', 'AMSR3 L2 ASW 전천후 해상풍', 'amsr3_l2_ASW',
     'ASW_L2_AMSR3_NH_swath_*_full_EPSG3413', _ASW, {}),
    ('amsr3_l3_SIC', 'AMSR3 L3', 'AMSR3 L3 SIC 10 km', 'amsr3_l3_SIC',
     'SIC_L3_AMSR3_NH_10km_*_full_EPSG3413', _PCT_ICE, {}),
    ('amsr3_l3_SST', 'AMSR3 L3', 'AMSR3 L3 SST 10 km', 'amsr3_l3_SST',
     'SST_L3_AMSR3_*_full_EPSG3413', _SST, {}),
    ('amsr3_l3_SSW', 'AMSR3 L3', 'AMSR3 L3 SSW 10 km', 'amsr3_l3_SSW',
     'SSW_L3_AMSR3_*_full_EPSG3413', _SSW, {}),
    ('amsr3_l3_ASW', 'AMSR3 L3', 'AMSR3 L3 ASW 10 km', 'amsr3_l3_ASW',
     'ASW_L3_AMSR3_*_full_EPSG3413', _ASW, {}),
    # ── A25 SIC 합성 시계열 (표준 SIC 라인 — 기본 제외) ──
    ('a25_amsr2_sic', 'AMSR2 A25 (L2+L3 합성)', 'AMSR2 A25 SIC 합성 (L2 + L3 백필)',
     'amsr2_amsr25_l2_l3_sic', 'SIC_A25_AMSR2_NH_*_full_EPSG3413', _PCT_ICE,
     {'series': True}),
    ('a25_amsr3_sic', 'AMSR3 A25 (L2+L3 합성)', 'AMSR3 A25 SIC 합성 (L2 + L3 백필)',
     'amsr3_amsr25_l2_l3_sic', 'SIC_A25_AMSR3_NH_*_full_EPSG3413', _PCT_ICE,
     {'series': True}),
    ('a25l2_amsr2_sic', 'AMSR2 A25L2 (L2 전용 합성)',
     'AMSR2 A25L2 SIC 시간별 L2 합성 (L3 백필 없음)',
     'amsr2_amsr25_l2_sic', 'SIC_A25L2_AMSR2_NH_*_full_EPSG3413', _PCT_ICE,
     {'series': True}),
    ('a25l2_amsr3_sic', 'AMSR3 A25L2 (L2 전용 합성)',
     'AMSR3 A25L2 SIC 시간별 L2 합성 (L3 백필 없음)',
     'amsr3_amsr25_l2_sic', 'SIC_A25L2_AMSR3_NH_*_full_EPSG3413', _PCT_ICE,
     {'series': True}),
    # ── VIIRS 나머지 / ICESat-2 (종전 그대로) ──
    ('viirs_29_j1', 'VIIRS', 'VJ129 해빙 분포 (스와스)', 'viirs_29_vj1_nrt',
     'SIC_A*_EPSG3413', _VNP29, {}),
    ('viirs_29_j2', 'VIIRS', 'VJ229 해빙 분포 (스와스)', 'viirs_29_vj2_nrt',
     'SIC_A*_EPSG3413', _VNP29, {}),
    ('viirs_29_arc', 'VIIRS', 'VNP29 해빙 분포 (스와스, archive)',
     'viirs_29_vnp_archive', 'SIC_A*_EPSG3413', _VNP29, {}),
    ('viirs_29_j1_arc', 'VIIRS', 'VJ129 해빙 분포 (스와스, archive)',
     'viirs_29_vj1_archive', 'SIC_A*_EPSG3413', _VNP29, {}),
    ('viirs_29_j2_arc', 'VIIRS', 'VJ229 해빙 분포 (스와스, archive)',
     'viirs_29_vj2_archive', 'SIC_A*_EPSG3413', _VNP29, {}),
    ('viirs_29p', 'VIIRS', 'VNP29P1D 일별 해빙 (타일)', 'viirs_29pe_vnp29p1d',
     'VNP29P1D.A*_sic_EPSG3413', _VNP29, {}),
    ('viirs_29p_vj2', 'VIIRS', 'VJ229P1D 일별 해빙 (타일)',
     'viirs_29pe_vj229p1d', 'VJ229P1D.A*_sic_EPSG3413', _VNP29, {}),
    ('viirs_30', 'VIIRS', 'VNP30 빙표면온도 (스와스)', 'viirs_30',
     'IST_A*_EPSG3413', _IST, {}),
    ('viirs_30p', 'VIIRS', 'VNP30P1D 일별 IST (타일)', 'viirs_30pe_vnp30p1d',
     'VNP30P1D.A*_ist_EPSG3413', _IST, {}),
    ('icesat2_atl20', 'ICESat-2', 'ATL20 월평균 Freeboard', 'icesat2_atl20',
     'ATL20-01_*_monthly_mean_fb', _FB, {}),
]
# 과거 catalog 에만 남아 있을 수 있는 은퇴 제품 id (catalog 정리 대상에 포함)
_SAT_RETIRED_IDS = ['amsr3_l3_SIM']
SAT_IDS = [p[0] for p in SAT_PRODUCTS]
SAT_EXTRA_IDS = [p[0] for p in _SAT_INACTIVE]

_RE_T14 = re.compile(r'(?<!\d)(\d{14})(?!\d)')
_RE_T12 = re.compile(r'(?<!\d)(\d{12})(?!\d)')
_RE_T8T6 = re.compile(r'(?<!\d)(\d{8})T(\d{6})(?!\d)')        # Sentinel 20260830T083305
_RE_T8H2 = re.compile(r'(?<!\d)(\d{8})T(\d{2})Z')             # GFS/WW3 유효시각 20260909T06Z
_RE_AJ = re.compile(r'(?:^|[._-])A(\d{7})(?:[._-](\d{4}))?')


def file_time(stem: str):
    """파일명 -> UTC 시각 (14/12자리, yyyymmddTHHMMSS, A연중일+HHMM, 8자리 -> 12Z)."""
    m = _RE_T14.search(stem) or _RE_T12.search(stem)
    if m:
        s = m.group(1)[:12]
        try:
            return datetime.strptime(s, '%Y%m%d%H%M')
        except ValueError:
            pass
    m = _RE_T8T6.search(stem)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2)[:4], '%Y%m%d%H%M')
        except ValueError:
            pass
    m = _RE_T8H2.search(stem)                 # GFS/WW3: 유효일THHZ (P리드는 이미 반영)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2) + '00', '%Y%m%d%H%M')
        except ValueError:
            pass
    m = _RE_AJ.search(stem)
    if m:
        try:
            t = datetime(int(m.group(1)[:4]), 1, 1) + timedelta(days=int(m.group(1)[4:]) - 1)
            if m.group(2):
                t += timedelta(hours=int(m.group(2)[:2]), minutes=int(m.group(2)[2:]))
            return t
        except ValueError:
            pass
    d = date_of_name(stem)
    return d + timedelta(hours=12) if d else None


def scan_satellite(src_root: str, ref, sat_filter=None, products=None):
    """위성 파일 -> { pid: [ {stem, src, png, ddir, t} ... ] }.

    ref 가 FOLDER 면 제품 폴더의 **최종(최신) 날짜 폴더** 파일 전부(스와스는 그날 전체),
    그 외에는 기준일 ref 폴더(또는 파일명 날짜 == ref)의 파일."""
    import fnmatch
    out = {}
    folder_mode = ref == FOLDER

    def _stem_of(fn):
        low = fn.lower()
        if not low.endswith('.tif'):
            return None
        return fn[:-8] if low.endswith('_cog.tif') else fn[:-4]

    for pid, _grp, _title, folder, pat, _meta, _opt in (products or SAT_PRODUCTS):
        if sat_filter and pid not in sat_filter:
            continue
        fdir = os.path.join(src_root, folder)
        if not os.path.isdir(fdir):
            continue
        files = _list_model_files(fdir)
        pref_day = None
        if folder_mode:
            pref_day, n_dirs = newest_folder_date(
                files, lambda fn: (_stem_of(fn) is not None
                                   and fnmatch.fnmatch(_stem_of(fn), pat)))
            if n_dirs > 1:
                print(f'  [warn] {pid}: 날짜 폴더 {n_dirs}개 — 최신 {pref_day:%Y/%m/%d} 만 사용')
        best = {}                                    # stem -> (pref, path, fd)
        for fn, path, fd in files:
            low = fn.lower()
            if not low.endswith('.tif'):
                continue
            is_cog = low.endswith('_cog.tif')
            stem = fn[:-8] if is_cog else fn[:-4]
            if not fnmatch.fnmatch(stem, pat):
                continue
            if folder_mode:
                if pref_day is not None and fd != pref_day:
                    continue
            else:
                day = fd or date_of_name(stem)
                if day is None or day.date() != ref.date():
                    continue
            pref = 0 if is_cog else 1
            cur = best.get(stem)
            if cur is None or pref < cur[0]:
                best[stem] = (pref, path, fd)
        items = []
        for stem, (_pref, path, _fd) in sorted(best.items()):
            png = os.path.join(os.path.dirname(path), stem + '.png')
            items.append({'stem': stem, 'src': path,
                          'png': png if os.path.isfile(png) else None,
                          'ddir': src_date_dir(path), 't': file_time(stem)})
        if items:
            out[pid] = items
    return out


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
    """(frame_id, ISO 시각, 표시 라벨) — 모델별 시간축을 실제 UTC 시각으로.

    신형 이름(<기준일>b_…)은 date/hh 가 이미 **예측(valid) 시각**이고,
    구형 이름은 date/hh 가 run 시각이라 lead 를 더한다. frame_id 는 두 형식이
    같은 프레임이면 같아지도록 예측 시각 + 리드로 만든다."""
    d = g['date']
    base = datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), tzinfo=timezone.utc)
    axis = cfg['axis']
    new_form = bool(g.get('bul'))
    if axis == 'date':
        t = base + timedelta(hours=12)              # 일평균 중앙시각
        return d, t, f'{d[4:6]}-{d[6:8]}'
    if axis == 'run_lead_h':
        hh = int(g.get('hh') or 0)
        lead = int(g.get('lead') or g.get('anal') or 0)
        t = base + timedelta(hours=hh) if new_form else base + timedelta(hours=hh + lead)
        ltag = 'Anal000' if g.get('anal') is not None else f'P{lead:03d}'
        fid = f'{t:%Y%m%dT%H}Z_{ltag}'
        return fid, t, f'+{lead}h ({t.strftime("%m-%d %HZ")})'
    if axis == 'run_lead_d':
        hh = int(g.get('hh') or 0)
        lead = int(g.get('lead') or 0)
        t = (base + timedelta(hours=12) if new_form
             else base + timedelta(hours=hh) + timedelta(days=lead, hours=12))
        return f'{t:%Y%m%d}_D{lead}', t, f'D+{lead} ({t.strftime("%m-%d")})'
    if axis == 'valid_bulletin':
        b = g.get('bul') or g.get('bull') or d
        hh = int(g.get('hh') or 12)
        t = base + timedelta(hours=hh)
        off = (base - datetime(int(b[:4]), int(b[4:6]), int(b[6:8]),
                               tzinfo=timezone.utc)).days
        sign = f'+{off}' if off >= 0 else str(off)
        return f'dm{d}_b{b}', t, f'{d[4:6]}-{d[6:8]} (b{sign}d)'
    raise ValueError(axis)


# ---------------------------------------------------------------- 날짜 규칙
FOLDER = 'folder'          # --date folder: 제품별 최종(최신) 날짜 폴더를 그대로 사용


def parse_date_arg(s: str):
    """--date 해석: folder(FOLDER 반환) | today | yesterday | YYYYMMDD | latest(None 반환)."""
    s = (s or FOLDER).strip().lower()
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                             microsecond=0, tzinfo=None)
    if s in (FOLDER, 'auto'):
        return FOLDER
    if s == 'today':
        return now
    if s == 'yesterday':
        return now - timedelta(days=1)
    if s == 'latest':
        return None
    d = datetime.strptime(s.replace('-', '')[:8], '%Y%m%d')
    return d


def _bulletin_of(fn: str):
    """파일명에 예측 기준일 태그가 있으면 datetime, 없으면 None."""
    m = _RE_BUL.search(fn)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) or m.group(2), '%Y%m%d')
    except ValueError:
        return None


def src_date_dir(src: str):
    """원본 파일의 Data_Out 날짜 폴더 'yyyy/mm/dd' (없으면 파일명 날짜, 그도 없으면 '')."""
    parts = os.path.normpath(src).split(os.sep)
    if (len(parts) >= 4 and _RE_Y.match(parts[-4]) and _RE_MD.match(parts[-3])
            and _RE_MD.match(parts[-2])):
        return '/'.join(parts[-4:-1])
    d = date_of_name(os.path.basename(src))
    return d.strftime('%Y/%m/%d') if d else ''


def _list_model_files(folder: str):
    """(파일명, 경로, 폴더날짜|None) — 평면 배치 + yyyy/mm/dd 날짜 폴더."""
    out = []
    for f in os.listdir(folder):
        p = os.path.join(folder, f)
        if os.path.isfile(p):
            out.append((f, p, None))
    from glob import glob as _g
    for p in _g(os.path.join(folder, '[12][09][0-9][0-9]', '[01][0-9]',
                             '[0-3][0-9]', '*')):
        if not os.path.isfile(p):
            continue
        parts = os.path.normpath(p).split(os.sep)
        try:
            fd = datetime.strptime(''.join(parts[-4:-1]), '%Y%m%d')
        except ValueError:
            continue
        out.append((os.path.basename(p), p, fd))
    return out


def newest_folder_date(files, accept=None):
    """_list_model_files 결과에서 (필터 accept 를 통과한) 파일들의 날짜 폴더 중 최신.

    날짜 폴더가 없으면(옛 평면 배치) None. 여러 개면 (최신, 개수) 로 경고용 개수도 반환."""
    fds = set()
    for fn, _p, fd in files:
        if fd is None:
            continue
        if accept is not None and not accept(fn):
            continue
        fds.add(fd)
    if not fds:
        return None, 0
    return max(fds), len(fds)


def _ddir_date(ddir: str, fallback):
    """'yyyy/mm/dd' -> 'YYYY-MM-DD' (없으면 fallback datetime 사용)."""
    if ddir and len(ddir) == 10:
        return f'{ddir[:4]}-{ddir[5:7]}-{ddir[8:10]}'
    return fallback.strftime('%Y-%m-%d') if fallback else ''


def ref_date_of(cfg: dict, fn: str, folder_date):
    """파일의 기준일(예측 run/bulletin) 과 유효일 판정 -> (bulletin|None, day)."""
    b = _bulletin_of(fn)
    day = folder_date or date_of_name(fn)
    return b, day


def frame_selected(cfg: dict, fn: str, folder_date, ref, lead_days: int):
    """기준일 ref 에 속하는 프레임인가.

    - 파일명에 기준일 태그가 있으면 태그 == ref
    - 그 외: 폴더(또는 파일명) 날짜 == ref.
      유효일별 폴더 모델(axis 'date', 기준일 태그 없음)은 ref < 날짜 <= ref+lead_days 도 포함
    """
    b, day = ref_date_of(cfg, fn, folder_date)
    if b is not None:
        return b.date() == ref.date()
    if day is None:
        return False
    if day.date() == ref.date():
        return True
    if cfg['axis'] == 'date':
        return ref.date() < day.date() <= (ref + timedelta(days=lead_days)).date()
    return False


def latest_ref_date(src_root: str, model_keys):
    """--date latest: 기준일 태그/run 폴더를 가진 모델들 중 가장 최근 기준일.

    (유효일별 폴더만 있는 모델은 기준일을 알 수 없어 후보에서 제외;
     그런 모델만 있으면 가장 최근 날짜 - lead 로 추정하지 않고 그 날짜를 쓴다)"""
    cand, fallback = [], []
    for mk in model_keys:
        cfg = MODELS[mk]
        folder = os.path.join(src_root, mk)
        if not os.path.isdir(folder):
            continue
        for fn, _p, fd in _list_model_files(folder):
            if not fn.lower().endswith('.tif') or not cfg['re'].match(fn):
                continue
            b = _bulletin_of(fn)
            if b is not None:
                cand.append(b)
            elif cfg['axis'] != 'date':          # run 기반 (riops/giops/aice)
                d = fd or date_of_name(fn)
                if d:
                    cand.append(d)
            else:
                d = fd or date_of_name(fn)
                if d:
                    fallback.append(d)
    if cand:
        return max(cand)
    return max(fallback) if fallback else None


# ---------------------------------------------------------------- 스캔
def scan(src_root: str, model_keys, var_filter, ref, lead_days: int):
    """모델별 { var: { frame_id: {src, t, label, pref, ddir} } } 수집.

    ref 가 FOLDER 면 **모델 폴더의 최종(최신) 날짜 폴더** 하나를 통째로 쓴다
    (날짜 폴더는 모델별로 하나뿐이라고 가정; 여러 개면 최신을 쓰고 경고).
    날짜 폴더가 없는 옛 평면 배치는 파일 전부를 대상으로 한다.
    그 외에는 기준일 ref 규칙(frame_selected)."""
    found = {}
    folder_mode = ref == FOLDER
    for mk in model_keys:
        cfg = MODELS[mk]
        folder = os.path.join(src_root, mk)
        if not os.path.isdir(folder):
            print(f'  [skip] 폴더 없음: {folder}')
            continue
        per_var: dict = {}
        n_seen = 0
        files = _list_model_files(folder)
        mref, n_dirs = (None, 0)
        if folder_mode:
            mref, n_dirs = newest_folder_date(
                files, lambda fn: fn.lower().endswith('.tif') and cfg['re'].match(fn))
            if n_dirs > 1:
                print(f'  [warn] {mk}: 날짜 폴더 {n_dirs}개 — 최신 {mref:%Y/%m/%d} 만 사용')
        for fn, _path, fd in files:
            if not fn.lower().endswith('.tif'):
                continue
            m = cfg['re'].match(fn)
            if not m:
                continue
            n_seen += 1
            if folder_mode:
                if mref is not None and fd != mref:
                    continue
            elif not frame_selected(cfg, fn, fd, ref, lead_days):
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
                slot[fid] = {'src': _path, 'pref': pref,
                             't': t, 'label': label,
                             'region': g['region'], 'crs': g['crs'],
                             'ddir': src_date_dir(_path)}
        if per_var:
            found[mk] = per_var
        elif n_seen and not folder_mode:
            print(f'  [skip] {mk}: 기준일 {ref:%Y-%m-%d} 자료 없음 '
                  f'(다른 날짜 파일 {n_seen}개)')
    return found


# ---------------------------------------------------------------- 정리(용량)
def purge_web_data(out_root: str, model_keys, mode: str):
    """web/Data_Out 비우기. mode: 'all' | 'models' | 'none'. 반환: 지운 바이트."""
    if mode == 'none' or not os.path.isdir(out_root):
        return 0
    targets = ([os.path.join(out_root, d) for d in os.listdir(out_root)]
               if mode == 'all' else
               [os.path.join(out_root, mk) for mk in model_keys])
    freed = 0
    for t in targets:
        if not os.path.exists(t):
            continue
        if os.path.isdir(t):
            for dp, _dn, fns in os.walk(t):
                for f in fns:
                    try:
                        freed += os.path.getsize(os.path.join(dp, f))
                    except OSError:
                        pass
            shutil.rmtree(t, ignore_errors=True)
        else:
            try:
                freed += os.path.getsize(t)
                os.remove(t)
            except OSError:
                pass
    return freed


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


def rgb_to_web_cog(gdal, src: str, dst: str, max_px=2048):
    """RGB GeoTIFF(예: S2 트루컬러, EPSG4326 Byte 3밴드) -> EPSG:3413 축소 COG.

    원본(10 m급, 수백 MB)을 그대로 복사하지 않고 max_px 이하로 줄여 재투영한다.
    검정(0,0,0)은 nodata 로 투명 처리된다 (뷰어 rgb 렌더러와 동일 규칙)."""
    ds = gdal.Open(src, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError('열 수 없음: ' + src)
    w, h = ds.RasterXSize, ds.RasterYSize
    sc = max(w, h) / float(max_px)
    if sc > 1:
        ds = gdal.Translate('', ds, format='MEM',
                            width=int(round(w / sc)), height=int(round(h / sc)),
                            resampleAlg='average')
    warped = gdal.Warp('', ds, format='MEM', dstSRS=EPSG3413_PROJ4,
                       srcNodata=0, dstNodata=0,
                       resampleAlg=gdal.GRA_Bilinear)
    if warped is None:
        raise RuntimeError('재투영 실패: ' + src)
    drv = 'COG' if gdal.GetDriverByName('COG') else 'GTiff'
    co = (['COMPRESS=DEFLATE'] if drv == 'COG'
          else ['COMPRESS=DEFLATE', 'TILED=YES'])
    out = gdal.Translate(dst, warped, format=drv, creationOptions=co)
    if out is None:
        raise RuntimeError('저장 실패: ' + dst)
    out = None
    return dst


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
    ap.add_argument('--models', nargs='*', default=MODEL_DEFAULT,
                    help=f'처리할 모델 폴더 (기본 {len(MODEL_DEFAULT)}종; '
                         f'기본 제외: {[k for k in MODELS if k not in MODEL_DEFAULT]})')
    ap.add_argument('--vars', nargs='*', default=None, help='변수 제한')
    ap.add_argument('--lat-min', type=int, default=50, choices=sorted(LAT_RADIUS),
                    help='출력 격자 위도 하한 (기본 50)')
    ap.add_argument('--res', type=int, default=0,
                    help='출력 해상도(m) 강제 지정 (기본 모델별 자동)')
    ap.add_argument('--max-frames', type=int, default=0,
                    help='변수당 프레임 상한 (0 = 제한 없음)')
    ap.add_argument('--date', default=FOLDER,
                    help='folder(기본: 제품별 최종 날짜 폴더를 그대로 사용, 모델별 날짜 폴더는 '
                         '하나라고 가정) | today | yesterday | YYYYMMDD | latest — '
                         'Data_Out/<모델>/yyyy/mm/dd 날짜 폴더 기준')
    ap.add_argument('--lead-days', type=int, default=10,
                    help='유효일별 폴더 모델(neXtSIM-F·GLO12 등)에서 기준일 이후 '
                         '함께 읽을 예측 일수 (기본 10)')
    ap.add_argument('--no-sat', action='store_true',
                    help='위성(관측) 자료는 처리하지 않음 (모델만)')
    ap.add_argument('--sat', nargs='*', default=None,
                    help=f'처리할 위성 제품 id 제한 (기본 전체: {", ".join(SAT_IDS[:4])} …)')
    ap.add_argument('--sat-extra', nargs='*', default=None,
                    help=f'기본 제외 제품을 추가로 처리: {", ".join(SAT_EXTRA_IDS)}')
    ap.add_argument('--keep-others', action='store_true',
                    help='web/Data_Out 비울 때 모델 폴더만 비우고 위성자료 폴더는 보존')
    ap.add_argument('--no-purge', action='store_true',
                    help='web/Data_Out 을 비우지 않음 (누적, 이전 방식)')
    ap.add_argument('--overwrite', action='store_true',
                    help='기존 파일 재생성 (--no-purge 와 함께 쓸 때 의미 있음)')
    ap.add_argument('--dry-run', action='store_true', help='변환·삭제 없이 목록만')
    a = ap.parse_args(argv if argv is not None else _main_argv())

    unknown = [m for m in a.models if m not in MODELS]
    if unknown:
        print(f'알 수 없는 모델: {unknown}\n사용 가능: {list(MODELS)}')
        return 2

    try:
        ref = parse_date_arg(a.date)
    except ValueError:
        print(f'--date 형식 오류: {a.date} (folder|today|yesterday|YYYYMMDD|latest)')
        return 2
    if ref is None:
        ref = latest_ref_date(a.src, a.models)
        if ref is None:
            print('처리할 자료가 없습니다 (--date latest: 날짜 폴더/파일을 찾지 못함).')
            return 1
        print(f'[make_web_data] --date latest -> 기준일 {ref:%Y-%m-%d}')

    folder_mode = ref == FOLDER
    print(f'[make_web_data] src={a.src}\n                out={a.out}\n' +
          ('                기준일 = 제품별 최종 날짜 폴더 (--date folder)'
           if folder_mode else
           f'                기준일={ref:%Y-%m-%d} (유효일 폴더 모델은 +{a.lead_days}일까지)'))
    found = scan(a.src, a.models, set(a.vars) if a.vars else None,
                 ref, a.lead_days)
    extra = set(a.sat_extra or [])
    bad_extra = sorted(extra - set(SAT_EXTRA_IDS))
    if bad_extra:
        print(f'알 수 없는 --sat-extra: {bad_extra}\n사용 가능: {SAT_EXTRA_IDS}')
        return 2
    sat_products = SAT_PRODUCTS + [p for p in _SAT_INACTIVE if p[0] in extra]
    sat_found = {} if a.no_sat else scan_satellite(
        a.src, ref, set(a.sat) if a.sat else None, products=sat_products)
    if not found and not sat_found:
        if folder_mode:
            print('처리할 자료가 없습니다 (모델·위성 폴더에 파일 없음) — 웹 폴더는 건드리지 '
                  '않았습니다.')
        else:
            print(f'기준일 {ref:%Y-%m-%d} 에 처리할 자료가 없습니다 — 웹 폴더는 건드리지 '
                  '않았습니다. (--date 를 확인하거나 --date folder 사용)')
        return 1
    if folder_mode:
        # 대표 기준일 = 사용된 날짜 폴더 중 최신 (catalog.ref_date, 요약 출력용)
        days = set()
        for v in found.values():
            for frames in v.values():
                days.update(f['ddir'] for f in frames.values() if f.get('ddir'))
        for items in sat_found.values():
            days.update(i['ddir'] for i in items if i.get('ddir'))
        ref = (datetime.strptime(max(days), '%Y/%m/%d') if days
               else datetime.now(timezone.utc).replace(tzinfo=None))
        used = sorted(days)
        print(f'  사용한 날짜 폴더: {", ".join(used) if used else "(평면 배치)"}')

    total_frames = sum(len(f) for v in found.values() for f in v.values())
    n_sat_files = sum(len(v) for v in sat_found.values())
    print(f'  모델 {len(found)}종, 변수 {sum(len(v) for v in found.values())}개, '
          f'프레임 {total_frames}개 · 위성 제품 {len(sat_found)}종, 파일 {n_sat_files}개')

    if a.dry_run:
        for mk, per_var in found.items():
            print(f'\n[{mk}] {MODELS[mk]["model"]}')
            for var in sorted(per_var):
                fr = per_var[var]
                one = next(iter(fr.values()))
                ddirs = sorted({i['ddir'] for i in fr.values()})
                print(f'   {var:16s} {len(fr):3d} 프레임  '
                      f'source={one["region"]}/{one["crs"]}  '
                      f'-> Data_Out/{mk}/{ddirs[0] if ddirs else ""}'
                      f'{" …" if len(ddirs) > 1 else ""}')
        if sat_found:
            print('\n[위성/관측] 기준일 폴더의 파일 (스와스는 그날 전체)')
            for pid, _g, title, folder, _pat, _m, opt in sat_products:
                items = sat_found.get(pid)
                if not items:
                    continue
                kind = '시계열 1항목' if opt.get('series') else f'{len(items)}항목'
                ddirs = sorted({i['ddir'] for i in items})
                print(f'   {pid:26s} {len(items):3d} 파일 -> {kind}  '
                      f'Data_Out/{folder}/{ddirs[0] if ddirs else ""}')
                for i in items[:3]:
                    print(f'        {i["stem"]}')
                if len(items) > 3:
                    print(f'        … 외 {len(items) - 3}개')
        mode = 'none' if a.no_purge else ('models' if a.keep_others else 'all')
        print(f'\n(dry-run) 실제 실행 시 web/Data_Out 정리 모드: {mode}')
        return 0

    # ---------- 웹 데이터 폴더 비우기 (용량 최소화)
    purge_mode = 'none' if a.no_purge else ('models' if a.keep_others else 'all')
    # keep-others: 모델 폴더 + 이번에 다시 만드는 위성 제품 폴더만 비운다
    purge_keys = list(a.models) + sorted({
        folder for pid, _g, _t, folder, _p, _m, _o in sat_products if pid in sat_found})
    freed = purge_web_data(a.out, purge_keys, purge_mode)
    if purge_mode != 'none':
        print(f'  web 폴더 정리({purge_mode}): {freed / 1e6:,.1f} MB 삭제 — {a.out}')

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
        res_m = a.res or cfg['res_m']
        mname = cfg['model'].replace('-', '')
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
            first_ddir = ''
            preview_rel = None
            for fid, info in order:
                name = f'{mname}_{var}_{fid}_EPSG3413_cog.tif'
                # 출력 경로 = Data_Out 규칙 그대로 (원본과 같은 yyyy/mm/dd 폴더)
                ddir = info['ddir']
                odir = os.path.join(a.out, mk, *ddir.split('/')) if ddir \
                    else os.path.join(a.out, mk)
                os.makedirs(odir, exist_ok=True)
                dst = os.path.join(odir, name)
                rel = f'Data_Out/{mk}/{ddir + "/" if ddir else ""}{name}'
                pv_path = os.path.join(odir, f'{mname}_{var}_preview.png')
                pv_rel = f'Data_Out/{mk}/{ddir + "/" if ddir else ""}{mname}_{var}_preview.png'
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
                        if preview_rel is None:
                            write_preview(np, Image, arr, lut, pv_path)
                            preview_rel = pv_rel
                    else:
                        skipped += 1
                        if preview_rel is None and os.path.isfile(pv_path):
                            preview_rel = pv_rel
                    bytes_out += os.path.getsize(dst)
                    if not first_ddir:
                        first_ddir = info.get('ddir', '')
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
                'title': f'{kname} ({var})',            # 데이터 제목
                'name': f'{mname}_{var}',               # 데이터 이름 (COG 파일 계열)
                'type': 'series', 'nav': rank,
                'kind': 'palette', 'enc': 'linear',
                'vmin': vmin, 'vmax': vmax, 'lut': lut, 'units': units,
                'desc': eid,
                'ref_date': _ddir_date(first_ddir, ref),
                'png': preview_rel or '',
                'cog': out_frames[0]['cog'],
                'frames': out_frames,
            })
            t0, t1 = out_frames[0]['t'][:10], out_frames[-1]['t'][:10]
            descs[eid] = {
                'title': f'{cfg["model"]} — {kname} ({var})',
                'fields': [
                    ['모델', f'{cfg["model"]} · {cfg["org"]}'],
                    ['기준일', _ddir_date(first_ddir, ref)],
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

    # ---------- 위성(관측) 자료: 기준일 폴더의 파일을 그대로 복사 (Data_Out 경로 규칙)
    sat_entries, sat_descs = [], {}
    sat_bytes = 0
    for pid, grp, title, folder, pat, meta, opt in sat_products:
        items = sat_found.get(pid)
        if not items:
            continue
        frames, first_png = [], None
        for it in items:
            ddir = it['ddir']
            odir = os.path.join(a.out, folder, *ddir.split('/')) if ddir \
                else os.path.join(a.out, folder)
            os.makedirs(odir, exist_ok=True)
            if opt.get('rgb'):
                # RGB 원본(대용량)은 복사 대신 3413 축소 COG 생성 (rgb_to_web_cog)
                base = it['stem'] + '_EPSG3413_cog.tif'
            else:
                base = os.path.basename(it['src'])
            dst = os.path.join(odir, base)
            try:
                if a.overwrite or not os.path.isfile(dst):
                    if opt.get('rgb'):
                        rgb_to_web_cog(gdal, it['src'], dst,
                                       max_px=opt.get('warp_px', 2048))
                    else:
                        shutil.copy2(it['src'], dst)
                sat_bytes += os.path.getsize(dst)
                rel = f'Data_Out/{folder}/{ddir + "/" if ddir else ""}{base}'
                png_rel = ''
                if it['png'] and not opt.get('rgb'):
                    pdst = os.path.join(odir, os.path.basename(it['png']))
                    if a.overwrite or not os.path.isfile(pdst):
                        shutil.copy2(it['png'], pdst)
                    png_rel = f'Data_Out/{folder}/{ddir + "/" if ddir else ""}' \
                              f'{os.path.basename(it["png"])}'
                    first_png = first_png or png_rel
                t = it['t']
                frames.append({'id': it['stem'], 'cog': rel, 'png': png_rel,
                               't': t.strftime('%Y-%m-%dT%H:%M:%SZ') if t else '',
                               'label': (t.strftime('%m-%d %H:%MZ') if t else it['stem'])})
            except Exception as exc:                           # noqa: BLE001
                failed += 1
                print(f'   [fail] {base}: {exc}')
        if not frames:
            continue
        common = {'group': grp, 'title': title, 'desc': pid, **meta,
                  **{k: v for k, v in opt.items() if k not in ('series', 'rgb',
                                                               'warp_px')}}
        # 설명 패널 기본 항목 (파이프라인 web_catalog 가 이미 써 둔 설명은 보존)
        enc_txt = {'palette': f"{meta.get('enc', '')} byte",
                   'float': 'float (파일별/고정 스트레치)',
                   'rgb': '트루컬러 RGB'}.get(meta.get('kind'), meta.get('kind', ''))
        sat_descs[pid] = {
            'title': title,
            'fields': [
                ['그룹', grp],
                ['Data_Out 폴더', folder],
                ['파일 패턴', pat],
                ['표현', enc_txt + (f" · {meta.get('vmin')}~{meta.get('vmax')}"
                                    f"{(' ' + meta['units']) if meta.get('units') else ''}"
                                    if meta.get('vmin') is not None else '')],
                ['구성', ('하루 시계열 1항목' if opt.get('series')
                          else '파일별 항목 (스와스/타일 전량)')],
            ],
            'note': '기준일 폴더의 산출물을 웹 폴더로 복사해 표시한다.'
                    + (' (RGB 원본은 3413 축소 COG 로 변환)' if opt.get('rgb') else ''),
        }
        if opt.get('series'):
            frames.sort(key=lambda f: f['t'])
            sat_entries.append({
                'id': pid, **common, 'type': 'series',
                'name': pat.replace('*', '…'),
                'png': first_png or '', 'cog': frames[0]['cog'],
                'ref_date': _ddir_date(items[0].get('ddir', ''), ref),
                'frames': [{k: v for k, v in f.items() if k != 'png'} for f in frames],
            })
            print(f'   [{pid}] {len(frames)} 파일 -> 시계열 1항목 ({frames[0]["label"]} ~ '
                  f'{frames[-1]["label"]})')
        else:
            for f in frames:
                sat_entries.append({
                    'id': f'{pid}__{f["id"]}', **common,
                    'name': f['id'], 'png': f['png'] or first_png or '',
                    'cog': f['cog'], 't': f['t'],
                    'ref_date': _ddir_date(items[0].get('ddir', ''), ref),
                })
            print(f'   [{pid}] {len(frames)} 파일 -> {len(frames)}항목')
    if sat_entries:
        print(f'  위성 자료 복사 {sat_bytes / 1e6:,.1f} MB')

    # ---------- catalog / descriptions 갱신 (기존 위성자료 항목 보존)
    dpath = os.path.join(WEB, 'data')
    os.makedirs(dpath, exist_ok=True)
    cpath = os.path.join(dpath, 'catalog.json')
    try:
        with open(cpath, encoding='utf-8') as f:
            cat = json.load(f)
    except (OSError, ValueError):
        cat = {'crs': 'EPSG:3413', 'entries': []}
    def _ours(eid):
        eid = str(eid or '')
        if eid.startswith('m_'):
            return True
        return any(eid == pid or eid.startswith(pid + '__')
                   for pid in SAT_IDS + SAT_EXTRA_IDS + _SAT_RETIRED_IDS)
    keep = [e for e in cat.get('entries', []) if not _ours(e.get('id'))]
    # 웹 폴더를 비운 뒤 파일이 사라진 항목(위성자료 등)은 목록에서 제거
    #  — 설명(descriptions)은 보존하므로 파이프라인이 web_catalog 로 다시 등록하면 복원됨
    pruned = []
    if purge_mode != 'none':
        kept2 = []
        for e in keep:
            cog = e.get('cog') or ''
            if cog and not os.path.isfile(os.path.join(WEB, cog)):
                pruned.append(e.get('id'))
            else:
                kept2.append(e)
        keep = kept2
        if pruned:
            print(f'  catalog: 파일이 없는 항목 {len(pruned)}개 제거 '
                  f'({", ".join(str(p) for p in pruned[:6])}'
                  f'{" …" if len(pruned) > 6 else ""})')
    cat['crs'] = 'EPSG:3413'
    cat['ref_date'] = ref.strftime('%Y-%m-%d')
    # 순서: 위성 단일 항목 -> 위성 시계열(A25) -> 모델 시계열  (뷰어 섹션 구분 기준)
    sat_single = [e for e in sat_entries if e.get('type') != 'series']
    sat_series = [e for e in sat_entries if e.get('type') == 'series']
    cat['entries'] = keep + sat_single + sat_series + entries
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
    for k, v in sat_descs.items():           # 파이프라인이 써 둔 설명은 우선
        dd.setdefault(k, v)
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
    print(f'  모델 항목 {len(entries)}개 (웹 COG {bytes_out / 1e6:,.1f} MB), '
          f'위성 항목 {len(sat_entries)}개 ({sat_bytes / 1e6:,.1f} MB)')
    print(f'  catalog: {cpath}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
