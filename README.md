# Arctic 데이터 뷰어 — MapLibre 극좌표 3단 화면

북극 중심 극사영(NSIDC Polar Stereographic North, **EPSG:3413**) 지도 위에
utils 파이프라인 산출 **COG** 를 그려 보는 데이터 목록 뷰어.

세 종류의 자료를 다룬다 (2026-09-29, Data_Out_sample 25종 기준으로 재편).

- **관측 자료** (15) — 단일 시각 COG. AMSR2 연구 HSI(L2/L3/A25R 합성)·SIM,
  AMSR3 HSI(L2/L3/A25 합성)·SIM, ASIP L3/L4, Sentinel-1 SAR(HH/HV),
  Sentinel-2 트루컬러(RGB), Sentinel-3 IST, VIIRS(VNP29 NRT·VJ129P1D)
- **예측 모델** (8) — 변수별 **시계열 COG**. 지도 아래 재생 막대로 예측 시간대를
  넘기며 애니메이션으로 본다 (TOPAZ5 · **TP3A3/TP3R(KIOST 편차보정)** ·
  neXtSIM-F · RIOPS · GIOPS · FOAM · GLO12; MET-AICE 는 기본 제외 —
  `--models met_aice` 로 명시 시 처리)
- **기상** (2) — GFS(0.25°: 풍속·해면기압·기온)와 WW3(북극 9 km: 파고·파주기)
  arctic_EPSG3413 float COG 시계열. 왼쪽 목록의 **기상** 섹션/탭에 표시

여기에 **북극항로(NSR) 항해 경로**가 지도 투영에 맞춰 겹쳐 그려진다.

## 실행

`run_web.bat` 더블클릭 → 브라우저가 `http://localhost:8000` 으로 열린다.
포트를 바꾸려면 `run_web.bat 8080` 처럼 인자로 준다.

- COG/JSON 을 `fetch` 로 읽기 때문에 **file:// 로 직접 열면 동작하지 않는다.**
- `run_web.bat` 은 `range_server.py`(HTTP Range 지원 서버) 를 띄운다.
  Range 지원 덕분에 큰 COG 도 필요한 부분(오버뷰)만 읽어 로딩이 빠르다.
  (Range 미지원 서버에서도 전체 파일 다운로드 폴백으로 동작은 한다.)

### Python 실행 환경

`run_web.bat` 은 utils 파이프라인과 같은 conda 환경(`ahnguhn` @
`C:\ProgramData\Anaconda3`)을 먼저 활성화한 뒤, 실제로 실행되는 Python 을
`python` → `py -3` → 알려진 설치 경로 순으로 찾는다. 설치 위치가 다르면
배치 파일 상단의 `CONDA_ENV` / `CONDA_ROOT` 를 고치면 된다.
(`range_server.py` 는 표준 라이브러리만 쓰므로 GDAL 이 없는 Python 이어도 된다.)

Windows 에서 `Python was not found ... Microsoft Store` 메시지가 나오면
`python` 이 실제 파이썬이 아니라 **스토어 별칭 스텁**으로 잡힌 것이다 —
설정 > 앱 > 고급 앱 설정 > 앱 실행 별칭에서 `python.exe` / `python3.exe` 를 끈다.

### 배치 파일 인코딩 주의

`run_web.bat` 은 **ASCII 전용**으로 유지한다. 한글 주석·메시지를 넣어 UTF-8 로
저장하면 CP949 콘솔에서 cmd 가 바이트를 잘못 끊어 주석 줄까지 명령으로 실행하고,
`'린'은(는) 내부 또는 외부 명령...` 같은 오류가 줄줄이 뜬다.
화면에 한글이 필요하면 배치가 아니라 Python(`range_server.py`) 에서 출력한다.

## 모델 예측 데이터 준비 (최초 1회 / 파이프라인 재실행 후)

모델 산출물은 용량이 크고(전 변수 8 GB) 투영도 제각각이라, 웹용으로 **변환해서**
`web/Data_Out/` 아래에 넣는다. **제품별로 날짜 폴더 하나(최종 폴더)만** 변환하고,
변환 전에 웹 폴더를 비워 용량을 최소로 유지한다.

```bash
run_make_web_data.bat                    # 각 제품의 최종(최신) 날짜 폴더, 전체 모델·변수
run_make_web_data.bat --dry-run          # 목록만 (삭제·변환 없음)
run_make_web_data.bat --date 20260801    # 특정 기준일 폴더로 고정
run_make_web_data.bat --date latest      # 기준일 태그/run 폴더 기준 가장 최근 기준일
run_make_web_data.bat --models topaz5_1d riops_2d
run_make_web_data.bat --vars siconc sithick
run_make_web_data.bat --keep-others      # 위성자료 웹 폴더는 남기고 모델 폴더만 교체
run_make_web_data.bat --no-purge         # 아무것도 지우지 않고 누적 (이전 방식)
```

**기본 동작 `--date folder`** (2026-08-31): 모델·위성 제품 폴더마다
`Data_Out/<제품>/yyyy/mm/dd` 의 **최종(최신) 날짜 폴더 하나**를 통째로 가져온다 —
운영 규칙상 제품별 날짜 폴더는 하나만 두므로, 글로벌 기준일을 따로 정하지 않아도
된다. 날짜 폴더가 여럿이면 최신 것만 쓰고 `[warn]` 을 찍는다(옛 평면 배치는 파일
전부). 제품마다 날짜가 달라도 각자 자기 폴더를 쓰며, catalog 항목의 `ref_date` 는
그 제품이 쓴 폴더 날짜, `catalog.ref_date` 는 그중 최신이다.
`--date today|yesterday|YYYYMMDD|latest` 를 주면 이전처럼 **하나의 기준일**로
고정해 아래 규칙대로 그 날짜 폴더만 읽는다.

**날짜 폴더 규칙** (utils 공통, `tools/dated_dirs.py`): 원본은
`Data_Out/<모델>/yyyy/mm/dd/` 에서 읽고, 웹 산출물도 **같은 경로 규칙**으로
`web/Data_Out/<모델>/yyyy/mm/dd/…_cog.tif` 에 저장한다 (원본이 있던 날짜 폴더와
동일). catalog 의 `cog`/`png` 경로에도 날짜 폴더가 들어간다.
`--date` 는 **예측 기준일(bulletin/run) 폴더**를 뜻한다 — TOPAZ5(기준일 태그
`…b_`)·RIOPS·GIOPS·MET-AICE(run 시각)·FOAM(`_b` 태그)은 그 폴더 하나에 전체
리드가 들어 있고, 파일명에 기준일이 없는 일평균 제품(neXtSIM-F·GLO12)은
유효일별 폴더에 흩어져 있으므로 기준일 ~ `--lead-days`(기본 10)일 폴더를 함께
읽어 시계열을 완성한다. 아직 날짜 폴더로 옮기지 않은 옛 평면 배치 파일도
파일명 날짜로 같은 기준을 적용한다.

**용량 관리**: 처리할 자료가 확인되면 `web/Data_Out` 아래를 **모두 비운 뒤**
변환한다. 그 결과 파일이 사라진 catalog 항목(위성자료 포함)은 목록에서 자동
제거된다 — 설명(descriptions.json)은 보존되므로 amsr25 등 파이프라인이
`web_catalog` 로 다시 등록하면 그대로 복원된다. 기준일에 자료가 하나도 없으면
아무것도 지우지 않고 종료한다.

**위성(관측) 자료도 함께 준비한다** — `SAT_PRODUCTS` 레지스트리의 폴더에서
**기준일 폴더의 파일을 모두** 찾아 web/Data_Out 의 같은 날짜 폴더로 **복사**한다
(이미 EPSG:3413 COG 라 재투영 없음 — 예외: Sentinel-2 는 아래 참고).
웹에 올리는 자료 범위 (2026-09-29, **Data_Out_sample 25종** 기준으로 재편):

| 계열 | Data_Out 폴더 | 비고 |
|---|---|---|
| AMSR2 연구 HSI | `amsr2_l2_research_HSI`, `amsr2_l3_research_HSI` | L2 스와스 + L3 10 km |
| AMSR2 A25R HSI 합성 | `amsr2_amsr25r_l2_l3_hsi` | 그날 파일 → 시계열 1항목 |
| AMSR2 연구 SIM | `amsr2_l3_research_SIM` | U/V/속력 3제품 |
| AMSR3 HSI | `amsr3_l2_HSI`, `amsr3_l3_HSI` | L2 스와스 + L3 10 km |
| AMSR3 A25 HSI 합성 | `amsr3_amsr25_10_l2_l3_hsi` | 10 km 완성판 → 시계열 1항목 |
| AMSR3 SIM | `amsr3_l3_SIM` | U/V/속력 3제품 |
| ASIP | `asip_l3`, `asip_l4` | DMI 해빙농도 0.5/1 km |
| Sentinel-1 SAR | `s1` | HH/HV 후방산란 (uint16, 파일별 2~98% 스트레치 회색조) |
| Sentinel-2 광학 | `s2` | `*_RGB.tif`(EPSG4326) 를 **3413 축소 COG**(기본 2048px)로 변환 복사 — 원본 stack COG(수백 MB)는 복사하지 않음 |
| Sentinel-3 IST | `s3e_ist` | 스와스별 float COG 2종: 해빙비율(`s3e_ist_sif`, 0~1) · 빙표면온도(`s3e_ist_ist`, K) |
| VIIRS | `viirs_29_vnp_nrt`, `viirs_29pe_vj129p1d` | VNP29 NRT 스와스 · VJ129P1D 일별 타일 |
| **기상** GFS | `gfs` | `aww`(풍속)·`apr`(해면기압)·`atm`(기온) — 시계열, 뷰어 '기상' 섹션(`sec:'wx'`) |
| **기상** WW3 | `ww3` | `swh`(1차 너울고)·`twh`(전체 유의파고)·`twp`(주기) — 시계열, 〃 |

그 외 표준 SIC/SST/SSW·연구 ASW/TIT/TSI·A25(L2/L2+L3) SIC 합성·VIIRS 나머지·
ICESat-2 는 `_SAT_INACTIVE` 로 내려 두어 기본 처리에서 제외되며,
`--sat-extra amsr2_l2_SIC …` 로 지정할 때만 처리한다.
스와스 제품은 그날의 패스 하나하나가 catalog 항목이 되고
(id `<제품>__<파일 stem>`, `title` = 제품 제목, `name` = 파일 stem), A25 합성처럼
`series` 로 표시한 제품은 그날 파일을 프레임으로 묶은 시계열 1항목이 된다.
`--no-sat`(모델만), `--sat amsr2_l2_SIC asip_l3`(제품 제한). 다른 위성 제품을
추가하려면 `SAT_PRODUCTS` 에 (id, 그룹, 제목, 폴더, 파일 stem 패턴, 색 인코딩) 한
줄을 넣으면 된다.

`tools/make_web_data.py` 가 하는 일:

1. `E:\workspace2026\arctic\test_data\Data_Out` 의 모델 8종 폴더(TOPAZ5 ·
   TP3A3/TP3R · neXtSIM-F · RIOPS · GIOPS · FOAM · GLO12)에서 **기준일
   폴더의** GeoTIFF 를 찾아 **변수별 시계열**로 묶는다 (파일명에서 변수·시각·리드를 파싱).
2. 지도와 같은 **EPSG:3413 북극 격자**로 재투영한다 (기본 위도 50° 이북,
   모델별 4~20 km). 파이프라인이 극사영(PS)·LAEA·경위도로만 산출하는 모델도
   여기서 3413 으로 맞춰진다.
3. 변수 레지스트리의 표출범위로 **Byte(1~255) 스케일** 후 COG 저장
   (byte 0 = nodata = 투명). float32 대비 용량이 1/10 이하로 줄고, 기존
   위성자료와 같은 `kind:"palette", enc:"linear"` 경로로 그려진다.
4. 변수별 미리보기 PNG 를 만든다 (오른쪽 설명 패널용).
5. `data/catalog.json` · `data/descriptions.json` 의 **모델 항목(`m_` 접두어)과
   레지스트리 위성 제품 항목**을 교체한다 — 그 외 손으로 넣은 항목은 손대지 않는다
   (단, 웹 폴더를 비운 뒤 파일이 없는 항목은 제거).
6. `data/route_nsr.geojson` (항해 경로) 을 갱신한다.

> **utils 파이프라인 설정**: topaz5_1d/1h · nextsim_hm · riops_2d · giops_2d ·
> aice 의 process json 에 `arctic` 리전과 `EPSG:3413` 을 추가해 두었다. 다음
> 파이프라인 실행부터는 3413 산출물이 바로 생성되고, 이 스크립트는 재투영을
> 건너뛰고 그대로 사용한다.

시각 축은 모델마다 다르지만(일평균 날짜 / P리드 시간 / D리드 일 / 유효일),
스크립트가 각 프레임의 **실제 UTC 시각**을 계산해 catalog 에 넣기 때문에
뷰어에서 서로 다른 모델을 **같은 시간축에 놓고 비교**할 수 있다.

## 화면 구성

```
┌──────────────┬──────────────────────┬──────────────┐
│ 데이터 리스트 │                      │ 데이터 설명   │
│  (그룹별)     │      지도 (3413)     │  표 + 비고    │
├──────────────┤                      │  대표 PNG     │
│ 그리기 목록   │                      │              │
│ [그리기]      │                      │              │
│ [모두 지우기] │                      │              │
└──────────────┴──────────────────────┴──────────────┘
```

- **왼쪽 상단 — 데이터 리스트**: `전체 / 관측 / 예측 모델 / 기상` 탭과 검색창.
  **관측 자료 → 예측 모델 → 기상** 세 섹션 순으로 표시되고(2026-09-29 재편:
  기상 = catalog `sec:"wx"` — GFS·WW3), 각 그룹 아래는
  **데이터 제목 → 데이터 이름** 2단 구조다.
  - 데이터 제목(`title`, 굵게) = 제품/변수 단위 (예: "AMSR2 L2 SIC 해빙농도",
    "해빙농도 (siconc)"). **클릭하면 하위 데이터 목록이 접히거나 펼쳐지고**(▼/▶
    캐럿) 오른쪽 설명도 뜬다. 처음에는 파일이 하나뿐인 제품은 펼쳐진 채, 스와스처럼
    여러 개인 제품은 접힌 채 시작한다. 파일이 여러 개면 개수 배지와 `＋전체` 버튼이
    붙는다 (스와스 하루치를 한 번에 추가). 그룹 줄(예: "AMSR2 L2 (표준)")을 클릭하면
    그룹 전체가 접히고, 검색창 위 `펼침 / 접기` 버튼은 모든 제품을 한 번에
    펼치거나 접는다. 검색 중에는 결과가 보이도록 항상 펼쳐진다.
  - 데이터 이름 = **COG 파일 이름**(확장자·`_cog` 제외, 고정폭 글꼴). 스와스
    제품은 기준일의 패스마다 한 줄씩 나오고, 각 줄의 `＋`(또는 더블클릭)로 그리기
    목록에 추가한다. **시계열(애니메이션)** 항목은 이름 뒤에
    `[2026-08-10 00:15Z ~ 08-10 23:45Z · 14프레임]` 처럼 **시간 범위**가 붙고
    `▶N` 배지가 표시된다. 모델 변수 앞 색점은 항행 활용도(주황 ★ 직접 · 파랑 ◆
    보조 · 회색 · 참고).
  - 그리기 목록·범례·상태줄에는 `제목 · 이름` 으로 표시된다.
- **왼쪽 하단 — 그리기 목록**: 중복 추가 안 됨, 드래그&드롭으로 순서 변경,
  `×` 로 개별 제거(지도에서도 제거), `👁/🚫` 로 레이어별 **보이기/보이지 않기** 토글.
  **그리기** = 목록 순서대로 지도에 COG 를 그림(뒤가 위).
  **모두 지우기** = 지도 레이어와 목록을 모두 비움.
- **가운데 — 지도**: EPSG:3413 극사영(가상좌표 매핑), 육지/위경도망/국가명,
  파이프라인 다운로드 **권역 5개**(ARC/BRS/ENS/YLS/EAS) 경계·라벨 표시,
  우하단에 마우스 실좌표 표시. 권역선은 항상 래스터 위에 유지된다.
  그려진 COG 를 **클릭하면 셀값 팝업**이 뜬다 — 클릭 지점의 위/경도와
  보이는 레이어별 값(위 레이어부터)을 물리량으로 변환해 표시
  (percent → %, linear → vmin..vmax 물리값+단위, classes → 클래스 번호,
  VNP29 → 해빙/개수면, float → 실측값). 전부 nodata 인 지점은 팝업 없음.
- **오른쪽 — 데이터 설명**: 선택한 데이터의 설명 표(원격탐사해빙자료 PPT 기반),
  비고, 대표 PNG(클릭 시 원본).
- **지도 아래 — 재생 막대(시계열 전용)**: 그리기 목록에 예측 모델 항목이
  들어가면 자동으로 나타난다.
  `⏮ 처음` · `◀ 이전` · `▶ 재생/⏸ 일시정지` · `⏹ 중지` · `▶ 다음` 버튼,
  **시간 스크롤 막대**, 현재 시각(UTC)과 프레임 번호, 재생 속도(0.5~4배).
  키보드 `Space`(재생/정지), `←` `→`(프레임 이동)도 쓸 수 있다.
  막대 아래에는 레이어별로 지금 표시 중인 프레임 라벨이 표시되며, 공통 시간축과
  12시간 넘게 차이 나는 레이어는 주황색으로 표시된다.
  그리기 직후 배경에서 전 프레임을 미리 렌더링하므로(진행 막대) 재생이 끊기지 않는다.
- **지도 좌상단 — 표시 토글**: `항해 경로(NSR)`, `권역` 켜기/끄기.
- **오른쪽 하단 — 범례**: 지도에 그려진 COG 의 색상 범례(위 레이어부터).
  연속형은 그라디언트 바 + 최소/중간/최대 눈금(물리값·단위),
  TSI 는 클래스 칩, VNP29 는 해빙/개수면 칩으로 표시.
  실제 그리기에 쓰인 색(내장 팔레트 또는 catalog 색)과 항상 일치하며,
  숨긴 레이어는 흐리게 표시된다.

## 데이터 연결 (JSON)

| 파일 | 내용 |
|---|---|
| `data/catalog.json` | 그릴 데이터 목록. 항목별 `id, group, name, cog, png, kind(...)` |
| `data/descriptions.json` | id별 설명(`title, fields, note, caption`) — 설명 자료만 별도 관리 |
| `data/route_nsr.geojson` | 항해 경로 (경위도). `NSRpolytopoint.txt` 에서 생성 |

항목의 표시 이름은 `title`(데이터 제목) + `name`(데이터 이름, 보통 COG 파일 stem)
2단으로 구성된다. `title` 이 없는 옛 항목은 `name` 을 제목으로, COG 파일명을 이름으로 쓴다.
**시계열(모델·A25) 항목**은 여기에 `type: "series"` 와 `frames` 배열이 더 붙는다.

```json
{
  "id": "m_topaz5_1d__siconc",
  "group": "① TOPAZ5 — CMEMS Arctic (10일)",
  "model": "TOPAZ5", "name": "해빙농도 (siconc)",
  "type": "series", "nav": 2,
  "kind": "palette", "enc": "linear",
  "vmin": 0.0, "vmax": 1.0, "lut": "ice", "units": "",
  "png": "Data_Out/topaz5_1d/TOPAZ5_siconc_preview.png",
  "cog": "Data_Out/topaz5_1d/TOPAZ5_siconc_20260728_EPSG3413_cog.tif",
  "frames": [
    {"id": "20260728", "t": "2026-07-28T12:00:00Z", "label": "07-28",
     "cog": "Data_Out/topaz5_1d/TOPAZ5_siconc_20260728_EPSG3413_cog.tif"}
  ]
}
```

- `t` = 프레임의 **실제 UTC 시각** — 모델 간 공통 시간축을 만드는 기준.
- `label` = 재생 막대에 표시할 짧은 라벨 (`+12h`, `D+3`, `07-28` 등).
- `nav` = 항행 활용도 (2 직접 · 1 보조 · 0 참고).
- 시계열 항목도 `cog`(첫 프레임) 를 갖는다 — 시계열을 모르는 코드 경로와의 호환용.

- `cog` / `png` 경로는 `web/` 기준 상대경로 (`Data_Out/...`).
- `kind: "palette"` — byte COG. 파일에 내장된 GDAL ColorTable 이 있으면 그대로,
  없으면 `enc`/`vmin`/`vmax`/`lut` 로 파이프라인과 동일한 색상 테이블을
  클라이언트에서 생성해 적용 (0 = nodata 투명).
  `enc: "percent"`(byte 1..100 = 0..100 %), `"linear"`(byte 1..255 = vmin..vmax),
  `"classes"`(byte = 클래스값+1, TSI 클래스 색상),
  `"values"`(값별 지정 색 — VNP29 이진: 해빙 100=빨강, 개수면 1=파랑).
  `override: true` 면 COG 내장 팔레트보다 catalog 색을 우선 적용.
- `kind: "float"` — Float32 COG. `lut`(freeboard/thermal/ice/gray) 와
  `stretch`([2,98] 백분위) 로 색을 입힘. nodata(-9999 등) 투명.
- `maxPx` — 큰 자료의 오버뷰 선택 상한(기본 1100).

데이터를 추가하려면 catalog.json 에 항목을 넣고, 같은 id 로
descriptions.json 에 설명을 넣으면 된다.

## 항해 경로 (NSR)

`NSRpolytopoint.txt` 는 공백 구분 텍스트이고 **4번째 열이 경도, 5번째 열이 위도**다
(1열 순번, 2·3열은 투영좌표). `tools/make_route_geojson.py` 가 이를 읽어
`data/route_nsr.geojson` 을 만든다.

- 첫 점과 끝 점이 같은 **왕복 경로**라서, 출발점에서 대권거리가 가장 먼 점을
  반환점으로 보고 **왕로(주황) / 복로(하늘색)** 두 LineString 으로 나눈다
  (부산 부근 ↔ 북유럽, 편도 약 14,400 km).
- 극사영에서 직선 보간이 실제 항로와 어긋나지 않도록 0.4° 간격으로 densify 한다.
  경도 ±180 구간은 짧은 쪽으로 보간하므로 날짜변경선 부근도 끊기지 않는다.
- 좌표는 **경위도 그대로** 저장하고, 투영 변환은 브라우저(`toFake()`)가 지도의
  EPSG:3413 가상좌표 매핑과 똑같은 식으로 처리한다 — 육지·위경도망·권역선과
  정확히 같은 기준이다.

단독 실행: `python tools\make_route_geojson.py`

## 선박 항적 (PANSTAR ACRO) + 예상 위치 도구

`data/PANSTAR*.csv`(AIS 기록: 경위도, SOG, 침로, 선수, 상태, CST/UTC 시각)와
`data/PANSTAR*.gpkg`(GeoPackage `track_points` 레이어 — utc/cst/lon/lat/
speed_kn/course_deg/heading_deg/turn_rate/nav_status 필드; 2026-09-29 추가,
sqlite3 로 직접 읽어 GDAL 불필요)를 `tools/make_ship_track.py` 가 하나로 묶어
**`PANSTAR_ACRO_track.geojson`**(web 루트)을 만든다 — 지도용으로 GeoJSON 이
적합(경위도 그대로 두고 투영은 브라우저 `toFake()`). CSV·GPKG 가 겹치는 기간은
UTC 시각으로 중복 제거된다.

```
python tools\make_ship_track.py                 # data/PANSTAR*.csv + *.gpkg 전부 -> PANSTAR_ACRO_track.geojson
python tools\make_ship_track.py --hours 2       # 대표점 간격 변경
python tools\make_ship_track.py --gpkg-glob ""  # gpkg 제외 (CSV 만)
```

- 파일 간 겹치는 구간은 UTC 시각으로 중복 제거하고 시각순으로 잇는다.
- `track`(LineString, 전체 기록) + **1시간 대표점**(각 정시에 가장 가까운 기록; 속성
  `utc, cst, lon, lat, sog_kn, cog, heading, status, seg_kn`=직전 대표점과의 구간 평균속력)
  + `last`(마지막 위치). 컬렉션 속성에 `sog_last_kn`, `avg_kn_24h`(최근 24h 이동 구간
  평균), `avg_kn_underway`(항해중 전체 평균, 1 kn 미만 정박·표류 구간과 3h 넘는 결측 제외).
- **지도**: 노란 선 + 노란 점(1시간), 빨간 점 = 마지막 위치. 점에 **마우스를 올리면**
  시각(UTC/KST/CST)·위치·SOG·구간 평균속력·침로/선수·항해 상태 팝업. 좌상단
  `선박 항적 (PANSTAR ACRO)` 체크로 켜고 끈다.
- **📍 예상위치 찍기**(좌상단 버튼, Esc 로 종료): 켠 상태에서 지도를 클릭하면 분홍 점이
  찍히고 마지막 위치 → 그 지점의 **대권거리(km/nmi)와 방위**, 그리고 **기존 속력 3가지**
  (마지막 SOG / 최근 24h 평균 / 항해중 평균)로 계산한 **소요 시간과 예상 도달 시각
  (UTC·KST)** 팝업이 뜬다. 마지막 위치에서 지점까지 분홍 점선(대권)도 그려진다.
  현재 침로와 90° 넘게 어긋난(뒤쪽) 지점이면 경고를 덧붙인다. 찍은 점은 다시 클릭하면
  팝업이 다시 열리고, 팝업의 `✕ 이 점 삭제` 또는 `찍은 점 지우기` 로 제거한다.
  예상위치 모드에서는 COG 셀값 팝업이 잠시 꺼진다.
- CSV 가 추가되면 스크립트를 다시 돌려 geojson 만 갱신하면 된다 (뷰어 수정 불필요).

## 파일

```
web/
├── index.html            뷰어 본체 (투영·COG 렌더 코드 포함)
├── run_web.bat           로컬 서버 실행
├── range_server.py       HTTP Range 지원 정적 서버
├── lib/maplibre-gl.js    MapLibre GL JS 4.7.1
├── lib/maplibre-gl.css
├── lib/geotiff.js        geotiff.js (브라우저 COG 리더)
├── data/catalog.json     데이터 경로 카탈로그
├── data/descriptions.json 데이터 설명
├── data/land_data.js     Natural Earth 육지 (JS 내장)
├── data/route_nsr.geojson  항해 경로 (NSRpolytopoint.txt 에서 생성)
├── tools/make_web_data.py      모델 산출물(기준일 폴더) -> 웹 COG + catalog 생성
├── tools/dated_dirs.py         utils 공통 날짜 폴더(yyyy/mm/dd) 규칙 헬퍼
├── tools/make_route_geojson.py 항해 경로 GeoJSON 생성
├── tools/make_ship_track.py    선박 AIS CSV -> PANSTAR_ACRO_track.geojson
├── PANSTAR_ACRO_track.geojson  선박 항적 (1시간 대표점 + 전체 선 + 마지막 위치)
├── run_make_web_data.bat       위 변환 실행 (conda 환경 자동 탐색)
├── NSRpolytopoint.txt    항해 경로 원본 (4열 경도, 5열 위도)
└── Data_Out/<제품>/yyyy/mm/dd/   파이프라인 산출 COG·PNG (+ 모델 시계열 COG) — 날짜 폴더 규칙
```
