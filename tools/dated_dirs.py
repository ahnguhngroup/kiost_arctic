# -*- coding: utf-8 -*-
"""날짜 폴더(~/yyyy/mm/dd) 저장·탐색 공통 헬퍼.

utils 공통 규칙 (2026-08):
  - 데이터 저장·최종 결과 폴더는 <기존 폴더>/yyyy/mm/dd 아래에 둔다.
  - 폴더 날짜는 파일명에서 뽑는다. 우선순위:
      1) TOPAZ5 계열 기준일 태그  <yyyymmdd>b_ 또는 _b<yyyymmdd>
      2) 12자리 관측시각 yyyymmddHHMM (A25, L2 스와스 등)
      3) MODIS/VIIRS 의 A<yyyyddd> (연중일)
      4) 파일명 처음 나오는 유효한 8자리 yyyymmdd
    날짜가 없는 파일(마스크, 정적 산출물)은 기존 폴더에 그대로 둔다.
  - 탐색은 기존 평면 배치와 yyyy/mm/dd 배치를 모두 본다 (하위 호환).

사용:
    from dated_dirs import dated_path, rglob
    out = dated_path(out_dir, fname)          # out_dir/yyyy/mm/dd/fname
    hits = rglob(out_dir, 'TOPAZ5_*_full.tif')  # 평면 + 날짜 폴더 모두
"""

import os
import re
from datetime import datetime, timedelta
from glob import glob

# 기준일 태그 (신형 <bul>b_, 중간형 _b<bul>)
_RE_BULLETIN = re.compile(r'(?:^|_)(\d{8})b(?=_)|_b(\d{8})(?=[_.]|$)')
_RE_D14 = re.compile(r'(?<!\d)(\d{14})(?!\d)')
_RE_D12 = re.compile(r'(?<!\d)(\d{12})(?!\d)')
_RE_AJUL = re.compile(r'(?:^|[._-])A(\d{7})(?=[._-])')
_RE_D8 = re.compile(r'(?<!\d)(\d{8})(?!\d)')


def _valid_d8(s):
    try:
        d = datetime.strptime(s, '%Y%m%d')
    except ValueError:
        return None
    return d if 2000 <= d.year <= 2099 else None


def date_of_name(name):
    """파일명에서 폴더 결정용 날짜(datetime)를 뽑는다. 없으면 None."""
    base = os.path.basename(str(name))
    m = _RE_BULLETIN.search(base)
    if m:
        d = _valid_d8(m.group(1) or m.group(2))
        if d:
            return d
    for rx in (_RE_D14, _RE_D12):
        m = rx.search(base)
        if m:
            d = _valid_d8(m.group(1)[:8])
            if d:
                return d
    m = _RE_AJUL.search(base)
    if m:
        try:
            d = (datetime(int(m.group(1)[:4]), 1, 1)
                 + timedelta(days=int(m.group(1)[4:]) - 1))
            if 2000 <= d.year <= 2099:
                return d
        except ValueError:
            pass
    for m in _RE_D8.finditer(base):
        d = _valid_d8(m.group(1))
        if d:
            return d
    return None


def dated_dir(base, date, create=True):
    """base/yyyy/mm/dd 경로 (date: datetime|'yyyymmdd'). date 없으면 base."""
    if date is None:
        out = str(base)
    else:
        if not hasattr(date, 'strftime'):
            date = _valid_d8(str(date).replace('-', '')[:8])
        out = (os.path.join(str(base), date.strftime('%Y'),
                            date.strftime('%m'), date.strftime('%d'))
               if date else str(base))
    if create:
        os.makedirs(out, exist_ok=True)
    return out


def dated_path(base, filename, date=None, create=True):
    """base/yyyy/mm/dd/filename — 날짜는 date 인자 또는 파일명에서 추출."""
    d = date if date is not None else date_of_name(filename)
    return os.path.join(dated_dir(base, d, create=create),
                        os.path.basename(str(filename)))


def rglob(base, pattern):
    """base 바로 아래(구 평면 배치)와 base/yyyy/mm/dd 아래를 모두 찾는다.

    정렬은 파일명 기준 — 날짜 태그가 앞서는 명명 규칙에서 시간순이 유지된다.
    """
    base = str(base)
    hits = glob(os.path.join(base, pattern))
    hits += glob(os.path.join(base, '[12][09][0-9][0-9]', '[01][0-9]',
                              '[0-3][0-9]', pattern))
    return sorted(set(hits), key=os.path.basename)
