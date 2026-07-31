# Arctic 데이터 뷰어 — MapLibre 극좌표 3단 화면

북극 중심 극사영(NSIDC Polar Stereographic North, **EPSG:3413**) 지도 위에
utils 파이프라인 산출 **COG** 를 그려 보는 데이터 목록 뷰어.

두 종류의 자료를 다룬다.

- **관측 자료** — 단일 시각 COG (AMSR2/AMSR3, ASIP, VIIRS, ICESat-2, Sentinel-3)
- **예측 모델** — 변수별 **시계열 COG**. 지도 아래 재생 막대로 예측 시간대를
  넘기며 애니메이션으로 본다 (TOPAZ5 · neXtSIM-F · RIOPS · MET-AICE · GIOPS ·
  FOAM · GLO12)

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
`web/Data_Out/` 아래에 넣는다.

```bash
run_make_web_data.bat                    # 전체 모델 · 전체 변수
run_make_web_data.bat --dry-run          # 어떤 변수·프레임이 잡히는지만 확인
run_make_web_data.bat --models topaz5_1d riops_2d
run_make_web_data.bat --vars siconc sithick
run_make_web_data.bat --lat-min 60 --overwrite
```

`tools/make_web_data.py` 가 하는 일:

1. `E:\workspace2026\arctic\test_data\Data_Out` 의 모델 7종 폴더에서 GeoTIFF 를
   찾아 **변수별 시계열**로 묶는다 (파일명에서 변수·시각·리드를 파싱).
2. 지도와 같은 **EPSG:3413 북극 격자**로 재투영한다 (기본 위도 50° 이북,
   모델별 4~20 km). 파이프라인이 극사영(PS)·LAEA·경위도로만 산출하는 모델도
   여기서 3413 으로 맞춰진다.
3. 변수 레지스트리의 표출범위로 **Byte(1~255) 스케일** 후 COG 저장
   (byte 0 = nodata = 투명). float32 대비 용량이 1/10 이하로 줄고, 기존
   위성자료와 같은 `kind:"palette", enc:"linear"` 경로로 그려진다.
4. 변수별 미리보기 PNG 를 만든다 (오른쪽 설명 패널용).
5. `data/catalog.json` · `data/descriptions.json` 의 **모델 항목(`m_` 접두어)만**
   교체한다 — 위성자료 항목은 손대지 않는다.
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

- **왼쪽 상단 — 데이터 리스트**: `전체 / 예측 모델 / 관측` 탭과 검색창.
  **관측 자료**와 **예측 모델**이 구분되어 표시되고, 모델은 다시 모델별 그룹
  (① TOPAZ5 … ⑦ GLO12) 아래 **변수별 항목**으로 나뉜다. 변수 앞 색점은 항행
  활용도(주황 ★ 직접 · 파랑 ◆ 보조 · 회색 · 참고), 뒤 `▶N` 배지는 시계열
  프레임 수다. 항목 클릭 → 오른쪽 설명 표시, `＋` 버튼(또는 더블클릭) →
  아래 그리기 목록에 추가.
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

**시계열(모델) 항목**은 여기에 `type: "series"` 와 `frames` 배열이 더 붙는다.

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
├── tools/make_web_data.py      모델 산출물 -> 웹 COG + catalog 생성
├── tools/make_route_geojson.py 항해 경로 GeoJSON 생성
├── run_make_web_data.bat       위 변환 실행 (conda 환경 자동 탐색)
├── NSRpolytopoint.txt    항해 경로 원본 (4열 경도, 5열 위도)
└── Data_Out/             파이프라인 산출 COG·PNG (+ 모델 시계열 COG)
```
