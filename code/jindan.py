# -*- coding: utf-8 -*-
"""우리동네 정비진단 — 판정 엔진 (PoC v0.2)

정비구역(또는 임의 지점 반경) 안의 건물·필지를 브이월드 개방 API로 수집하여
서울시 도시정비조례 기준 노후도·과소필지 등을 자동 판정한다.

사용 예:
  경계 기반 : judge_zone(rings)                # rings: WGS84 폴리곤 링 목록
  주소 기반 : judge_address("노원구 상계동 154-3", radius_m=250)   # 예비 진단
근거 법령: 도시 및 주거환경정비법 §2③·§16, 시행령 §2·별표1,
          서울특별시 도시 및 주거환경정비 조례 §2·§4·§6·별표1 (시행 2026-05-18)
"""
import json
import math
import urllib.parse
import urllib.request

import os

def load_key():
    """브이월드 API 키: 환경변수 VWORLD_KEY → 코드 폴더의 .env 순으로 탐색. 소스에는 키를 두지 않는다."""
    k = os.environ.get("VWORLD_KEY")
    if k:
        return k.strip()
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env):
        for line in open(env, encoding="utf-8"):
            if line.startswith("VWORLD_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("VWORLD_KEY 가 없습니다. 환경변수로 설정하거나 코드/.env 파일을 만드세요(.env.example 참고).")

KEY = load_key()
BASE_YEAR = 2026
RC_CODES = ("21", "22", "23", "24", "25", "29")  # 콘크리트 계열 (21 철근콘크리트, 22 프리캐스트 …)
STEEL_CODES = ("31", "32", "33", "39")           # 강구조 (31 일반철골, 32 경량철골 …)
COVERAGE_MIN = 0.5                                # 판정가능 비율이 이 미만이면 판정 보류
ROAD_SUFFIX = ("도", "천", "구", "제", "유")    # 지목 말미: 도로·하천·구거·제방·유지


# ── 공통 유틸 ────────────────────────────────────────────────
def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=120).read()


def geocode(address):
    q = {"service": "address", "request": "getcoord", "version": "2.0",
         "crs": "epsg:4326", "address": address, "refine": "true",
         "type": "parcel", "key": KEY}
    d = json.loads(_get("https://api.vworld.kr/req/address?" + urllib.parse.urlencode(q)))
    p = d["response"]["result"]["point"]
    return float(p["x"]), float(p["y"])


def wfs_collect(typename, bbox, grid=3):
    """bbox=(x0,y0,x1,y1)를 grid×grid 타일로 나눠 수집(MAXFEATURES=1000 제한 대응)."""
    x0, y0, x1, y1 = bbox
    seen, out, saturated = set(), [], 0
    for i in range(grid):
        for j in range(grid):
            ty0 = y0 + (y1 - y0) * i / grid
            ty1 = y0 + (y1 - y0) * (i + 1) / grid
            tx0 = x0 + (x1 - x0) * j / grid
            tx1 = x0 + (x1 - x0) * (j + 1) / grid
            q = {"SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
                 "TYPENAME": typename, "BBOX": f"{ty0},{tx0},{ty1},{tx1},EPSG:4326",
                 "SRSNAME": "EPSG:4326", "MAXFEATURES": "1000",
                 "OUTPUT": "application/json", "KEY": KEY, "DOMAIN": "localhost"}
            fs = json.loads(_get("https://api.vworld.kr/req/wfs?" + urllib.parse.urlencode(q))).get("features", [])
            if len(fs) >= 1000:
                saturated += 1
            for f in fs:
                if f["id"] not in seen:
                    seen.add(f["id"])
                    out.append(f)
    if saturated:
        # 포화 타일이 있으면 더 잘게 재수집
        return wfs_collect(typename, bbox, grid + 2)
    return out


def centroid(geom):
    ring = geom["coordinates"][0][0] if geom["type"] == "MultiPolygon" else geom["coordinates"][0]
    return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))


try:
    from pyproj import Transformer
    _TO_5186 = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)  # Korea 2000 / 중부원점
except Exception:  # pyproj 미설치 시 등장방형 근사로 폴백
    _TO_5186 = None


def ring_area_m2(ring):
    """폴리곤 링 면적(㎡). EPSG:5186 투영 후 신발끈 공식(실면적)."""
    if _TO_5186 is not None:
        xs, ys = _TO_5186.transform([p[0] for p in ring], [p[1] for p in ring])
        pts = list(zip(xs, ys))
    else:
        lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
        mx, my = 111320 * math.cos(lat0), 110540
        pts = [(p[0] * mx, p[1] * my) for p in ring]
    return abs(sum(pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
                   for i in range(len(pts) - 1))) / 2


def point_in_rings(x, y, rings):
    def pip(ring):
        inside = False
        for i in range(len(ring) - 1):
            x1, y1 = ring[i]
            x2, y2 = ring[i + 1]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
        return inside
    if not pip(rings[0]):
        return False
    return not any(pip(r) for r in rings[1:])   # 구멍 제외


# ── 판정 로직 (서울 조례 제4조·별표1) ──────────────────────────
# ── 조례별 기준표 (판정 로직은 공통, 표만 교체) ────────────────
def _apt_limit_table(rows_5up, rows_4dn):
    """별표1을 (준공연도 상한, 연한) 목록으로 표현. 예: [(1981,20),(1982,22),...,(9999,30)]"""
    def f(year, five_up):
        for ymax, lim in (rows_5up if five_up else rows_4dn):
            if year <= ymax:
                return lim
        return 30
    return f

RULESETS = {
    "서울": {  # 서울특별시 도시 및 주거환경정비 조례(시행 2026-05-18) §2·§4·별표1·§6
        "law": "서울특별시 도시 및 주거환경정비 조례 제4조·별표1·제6조",
        "apt_limit": _apt_limit_table(
            [(1981, 20), (1982, 22), (1983, 24), (1984, 26), (1985, 28), (9999, 30)],
            [(1981, 20), (1982, 21), (1983, 22), (1984, 23), (1985, 24), (1986, 25), (1987, 26), (1988, 27), (1989, 28), (1990, 29), (9999, 30)]),
        "apt_other": 20, "nonhouse_rc": 30, "default": 20,
        "old_ratio_min": 0.60, "area_min_m2": 10000, "small_parcel_m2": 90, "small_parcel_min": 0.40,
    },
    "경기": {  # 경기도 도시 및 주거환경정비 조례(시행 2026-06-29) §2·§3·별표1(개정 2023.4.11)·§6
        "law": "경기도 도시 및 주거환경정비 조례 제3조·별표1·제6조",
        "apt_limit": _apt_limit_table(
            [(1983, 20), (1984, 22), (1985, 24), (1986, 26), (1987, 28), (9999, 30)],
            [(1983, 20), (1984, 21), (1985, 22), (1986, 23), (1987, 24), (1988, 25), (1989, 26), (1990, 27), (1991, 28), (1992, 29), (9999, 30)]),
        "apt_other": 20, "nonhouse_rc": 30, "default": 20,
        "old_ratio_min": 0.50, "area_min_m2": 10000, "small_parcel_m2": 90, "small_parcel_min": 0.30,
    },
}
RULES = RULESETS["서울"]


def aging_limit(year, strct_cd, usability, grnd_flr, rules=None):
    """건물 1동의 노후 기준 연한(년). 구조: RC 계열·강구조 여부, 용도: 공동주택/단독주택, 층수: 5층 이상 여부."""
    r = rules or RULES
    code = str(strct_cd or "")
    rc = code in RC_CODES or code in STEEL_CODES      # 조례: RC 계열 "및 강구조"; 조적조(11·12·19)·목구조 등은 비RC
    use = str(usability or "")
    apt = use.startswith("02")
    house = use.startswith("01")                       # 단독주택은 30년 적용 제외
    if apt and rc:
        return r["apt_limit"](year, (grnd_flr or 0) >= 5)
    if apt:
        return r["apt_other"]
    if rc and not house:
        return r["nonhouse_rc"]
    return r["default"]                                # 조적조 단독·무허가(사용승인일 있는 경우) 등


def judge_building(props, base_year=None, rules=None):
    """True=노후, False=양호, None=판정불가(사용승인일 없음). base_year: 판정 기준연도(기본 BASE_YEAR)."""
    base_year = base_year or BASE_YEAR
    day = (props.get("useapr_day") or "").strip()
    if not day[:4].isdigit():
        return None
    year = int(day[:4])
    lim = aging_limit(year, props.get("strct_cd"), props.get("usability"), props.get("grnd_flr"), rules)
    return (base_year - year) >= lim


# ── 구역 진단 ────────────────────────────────────────────────
def judge_zone(rings, name="(무명 구역)", area_m2=None, base_year=None, rules=None):
    """base_year: 판정 기준연도(기지정 구역 재현 시 고시 연도). rules: RULESETS 항목(기본 서울)."""
    r = rules or RULES
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    if area_m2 is None:
        area_m2 = ring_area_m2(rings[0]) - sum(ring_area_m2(r) for r in rings[1:])

    blds = [f for f in wfs_collect("lt_c_bldginfo", bbox)
            if point_in_rings(*centroid(f["geometry"]), rings)]
    verdicts = [judge_building(f["properties"], base_year, r) for f in blds]
    known = [v for v in verdicts if v is not None]
    old = sum(known)

    pcls = [f for f in wfs_collect("lp_pa_cbnd_bubun", bbox)
            if point_in_rings(*centroid(f["geometry"]), rings)]
    land = [f for f in pcls
            if not str(f["properties"].get("jibun") or "").rstrip().endswith(ROAD_SUFFIX)]
    small = sum(1 for f in land if ring_area_m2(
        f["geometry"]["coordinates"][0][0] if f["geometry"]["type"] == "MultiPolygon"
        else f["geometry"]["coordinates"][0]) < r["small_parcel_m2"])

    cov = len(known) / len(blds) if blds else 0
    pct_known = old / len(known) * 100 if known else None      # 판정가능 건물 기준(상한)
    pct_cons = old / len(blds) * 100 if blds else None         # 건물 총수 기준(하한, 미판정=비노후 가정)
    if cov < COVERAGE_MIN or not known:
        verdict = "보류"                                        # 대장 미연계 건물 과다 → 보완 필요
    elif pct_cons >= r["old_ratio_min"] * 100:
        verdict = "충족"
    elif pct_known >= r["old_ratio_min"] * 100 or (old + (len(blds) - len(known))) / len(blds) * 100 >= r["old_ratio_min"] * 100:
        verdict = "조건부충족"                                   # 연계값 또는 최댓값(미연계 전부 노후 가정)이 기준 이상 → 미연계 처리에 따라 갈림
    else:
        verdict = "미충족"                                      # 미연계 건물을 전부 노후로 보아도 기준 미달
    r = {
        "구역명": name,
        "기준연도": base_year or BASE_YEAR,
        "면적_m2": round(area_m2, 1),
        "건물_총": len(blds),
        "건물_판정가능": len(known),
        "건물_노후": old,
        "판정커버리지": round(cov * 100, 1),
        "노후도_pct": round(pct_known, 1) if pct_known is not None else None,
        "노후도_pct_보수": round(pct_cons, 1) if pct_cons is not None else None,
        "노후도_판정": verdict,
        "노후도_충족": verdict == "충족",                          # 조례 §6① 필수요건(보수 기준)
        "기준표": r["law"],
        "면적_충족": area_m2 >= r["area_min_m2"],                       # 조례 §6① 필수요건
        "필지_대상": len(land),
        "필지_과소": small,
        "과소필지_pct": round(small / len(land) * 100, 1) if land else None,
        "과소필지_충족": (small / len(land) >= r["small_parcel_min"]) if land else None,  # 선택요건
        "호수밀도_단순": round(len(blds) / (area_m2 / 10000), 1),       # 특례 미반영 참고치
    }
    r["_blds"] = blds   # 시각화·보고서용 원자료
    r["_pcls"] = pcls
    return r


def judge_address(address, radius_m=250):
    """주소 기반 예비 진단 — 반경 원을 구역으로 간주(경계 미확정 시)."""
    cx, cy = geocode(address)
    dlat = radius_m / 110540
    dlon = radius_m / (111320 * math.cos(math.radians(cy)))
    ring = [[cx + dlon * math.cos(t * math.pi / 18), cy + dlat * math.sin(t * math.pi / 18)]
            for t in range(37)]
    return judge_zone([ring], f"{address} 반경 {radius_m}m (예비)", math.pi * radius_m ** 2)


if __name__ == "__main__":
    import sys
    addr = sys.argv[1] if len(sys.argv) > 1 else "서울특별시 노원구 상계동 154-3"
    res = judge_address(addr)
    print(json.dumps({k: v for k, v in res.items() if not k.startswith("_")},
                     ensure_ascii=False, indent=2))
