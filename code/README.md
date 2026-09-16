# 우리동네 정비진단 — 재현 패키지 (PoC v0.3)

주민이 정비사업 필수요건을 조례 기준으로 직접 확인하는 공공 서비스 모델의 판정 엔진·검증 코드.
전 데이터 무상 개방 API만 사용. 개인 의존성 없이 아래 순서로 누구나 재현할 수 있다.

## 준비
```bash
pip install pyshp pyproj shapely scikit-learn pypdf pymupdf pillow
cp .env.example .env      # VWORLD_KEY=브이월드 오픈API 키 (www.vworld.kr 발급), BLDG_KEY=공공데이터포털 건축HUB 키(선택)
```
법령 API는 국가법령정보센터 OC 키(무료)를 `rules_from_law.py` 상단에 지정.

## 구성
| 파일 | 역할 |
|---|---|
| `jindan.py` | 판정 엔진 — WFS 수집(타일 분할), 조례 기준표(`RULESETS`: 서울·경기), 노후 연한·과소필지·면적 판정, 상·하한·4상태 |
| `rules_from_law.py` | 법령 API에서 조례 XML·별표 첨부(hwp)를 받아 기준표 자동 생성, 수동 기준표와 대조 |
| `collect_cache.py` | 검증 구역 13곳(기지정 10 + 미지정 3)의 건물·필지 원자료 캐시 |
| `impute_model.py` | 대장 미연계 건물의 노후 여부 공간 학습 추정(구역 홀드아웃 평가) |
| `robustness.py` | 경계 강건성 등급(±20·40m 변형) + 서울·경기 기준표 교차 판정 |
| `road_access.py` | 주택접도율 근사(도로 지목 필지 공유 경계 ≥4m) |
| `types.py` | 사업유형별 기준표 8종(재개발·주거환경개선·역세권·재건축·가로주택·소규모재건축·자율주택·소규모재개발) 판정 + 가로구역 자동 생성 → `data/type_matrix.json` |
| `join_ledger.py` | 건축물대장 표제부(건축HUB API) 조인으로 미연계 건물 사용승인일 보완 — `.env`에 `BLDG_KEY` 필요, 조인 전후 노후도 비교 → `data/join_result.json` |
| `road_width.py` | 도로 폴리곤 침식으로 폭 4m/6m 반영 접도율 하한 + 폭 미반영 상한 → `data/road_width_result.json` |
| `density.py` | 표제부 전수 조회로 호수밀도 조례 특례(§2 5호) 근사 → `data/density_result.json` (BLDG_KEY, 필지 수만큼 호출) |
| `timing.py` | 기준연도를 올려가며 60% 도달 연도 산출(진단서 3장) → `data/timing_result.json` |
| `gg_cases.py` | 경기 실지 이용자 경계 판정(경기·서울 기준표 병기) → `data/gg_cases.json` |
| `report.py` | 진단서 PDF 자동 생성(경계 출처·판정 범위·기준표 버전·유형별 가능성 표) |
| `build_submission_v3.py` | 참가신청서 PDF 생성 |

## 재현 순서
```bash
python rules_from_law.py        # 기준표 자동 생성 → 서울·경기 수동표와 52케이스 대조
python collect_cache.py         # 13개 구역 캐시(API 약 300회, 수 분)
python impute_model.py          # 결측 보완 모델: 홀드아웃 정확도·AUC, 판정 폭 축소
python robustness.py            # 강건성 등급·교차 판정
python road_access.py           # 접도율 근사
python types.py                 # 유형별 판정 매트릭스(캐시 기반) + 가로구역 자동 생성
python join_ledger.py 상계동     # 표제부 조인(BLDG_KEY 필요) → data/join_result.json
python road_width.py            # 접도율 폭 반영
python timing.py                # 충족 예상 시점
python density.py 상도14        # 호수밀도 특례 근사(BLDG_KEY)
python gg_cases.py              # 경기 실지 판정
python report.py <results.json> # 진단서 PDF
```
회귀 기준(2026-09-15 실행값): 기준표 대조 불일치 0건 / 상계동 154-3일대 1,055동·노후도 71.1~85.5%(2025 기준) /
결측 모델 홀드아웃 AUC 중앙값 0.96·평균 0.93(정확도는 클래스 불균형으로 참고치) / 강건성 등급 강건 6·보통 5·취약 2 / 표제부 조인(2026-09-16): 상계동 커버리지 83.1→96.0%, 보수값~연계값 71.1~85.5→78.1~81.3, 대장 없음 42동.

## 인수 시 유의
- 판정 규칙은 코드가 아닌 `RULESETS` 기준표에 있으며, 조례 개정 시 `rules_from_law.py`로 재생성 후 시·도 감수·버전 기록
- 대장 미연계 건물의 추정은 '추정'으로만 표기하고 확정은 건축물대장 표제부 조인으로
- 진단서의 판정 범위 고지(불량건축물 가~다목·접도율·호수밀도·재건축진단·주민동의·기본계획 미반영)는 삭제하지 않는다
