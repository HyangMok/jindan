# -*- coding: utf-8 -*-
"""사업유형별 요건 판정 — 재개발 외 유형(주거환경개선·재건축·가로주택·소규모재건축·자율주택·소규모재개발)

기준표 TYPE_RULES는 조문에서 옮긴 값(서울 기준). 판정은 캐시 데이터로 API 재호출 없이 수행.
  - 도시정비법 시행령 별표1(2026-07-01 시행) 2호·3호·4호 후단
  - 서울시 도시 및 주거환경정비 조례 §2·§6①(1호 주거환경개선, 2호 주택정비형 재개발, 3호 도시정비형)·§6④
  - 빈집 및 소규모주택 정비에 관한 특례법 시행령 §3①·② + 서울시 빈집 및 소규모주택 정비 조례 §3③⑤⑥
가로구역 자동 생성: 도로 지목 필지를 경계로 서로 맞닿은 대지 필지의 연결 성분 = "도로로 둘러싸인 일단의 지역"(소규모법 시행령 §3②1).
출력: data/type_matrix.json
"""
import glob
import json
import os
import sys

from pyproj import Transformer
from shapely.geometry import shape, Point, Polygon
from shapely.ops import transform as T, unary_union
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jindan  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
to_m = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True).transform
to_deg = Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True).transform

# ── 유형별 기준표(서울) — 값은 조문 원문에서 전기, 근거 조문 병기 ──
TYPE_RULES = {
    "주택정비형 재개발": dict(law="서울 조례 §6①2 + 시행령 별표1 2호·4호 후단",
                       area_min=10000, old_min=0.60, opt=dict(small_min=0.40, road_max=0.40, density_min=60),
                       deem_old=0.75),   # 별표1 4호 후단: 노후도 3/4 이상이면 조례 선택요건을 갖춘 것으로 봄
    "주거환경개선": dict(law="서울 조례 §6①1", density_min=80, old_min=0.60, road_max=0.20, small_min=0.50),
    "도시정비형 재개발(역세권)": dict(law="서울 조례 §6①3", station_m=500, old_min=0.60),
    "재건축": dict(law="시행령 별표1 3호 다목 + 서울 조례 §6④", site_min=10000, hh_min=200,
                note="재건축진단(법 §12)은 별도 — 데이터 판정 불가"),
    "가로주택정비": dict(law="소규모법 시행령 §3①2·②, 서울 소규모 조례 §3⑤", area_max=13000, old_min=0.60,
                     old_min_promo=0.50, house_min=dict(단독=10, 공동=20, 합=20), block=True),
    "소규모재건축": dict(law="소규모법 시행령 §3①3", area_max=10000, old_min=0.60, hh_max=200, complex=True),
    "자율주택정비": dict(law="소규모법 시행령 §3①1, 서울 소규모 조례 §3③", old_min=0.60,
                     house_max=dict(단독=18, 연립다세대=36, 합=36), zone_cond="빈집밀집·관리지역·해제구역 등 대상지역 요건 별도"),
    "소규모재개발": dict(law="소규모법 시행령 §3①4, 서울 소규모 조례 §3⑥", station_m=250, area_max=5000, old_min=0.60),
}


def _geom_m(f):
    return T(to_m, shape(f["geometry"]))


def metrics(z, poly_m, year, rules=jindan.RULESETS["서울"], station_m=None):
    """경계(EPSG:5186 폴리곤) 안의 건물·필지로 유형 판정에 필요한 지표를 계산."""
    ring_deg = [list(T(to_deg, poly_m).exterior.coords)]
    inb = [f["properties"] for f in z["blds"] if jindan.point_in_rings(*jindan.centroid(f["geometry"]), ring_deg)]
    v = [jindan.judge_building(p, year, rules) for p in inb]
    known = [x for x in v if x is not None]
    n = len(inb)
    area = poly_m.area
    pcls = [(f["properties"], _geom_m(f)) for f in z["pcls"]]
    inp = [(p, g) for p, g in pcls if poly_m.contains(g.representative_point())]
    land = [(p, g) for p, g in inp if not str(p.get("jibun") or "").rstrip().endswith(jindan.ROAD_SUFFIX)]
    roads_all = [g for p, g in pcls if str(p.get("jibun") or "").rstrip().endswith("도")]
    small = sum(1 for p, g in land if g.area < rules["small_parcel_m2"])
    # 접도율 근사(도로 폭 미반영 상한)
    rtree = STRtree(roads_all) if roads_all else None
    land_ok = {}
    for p, g in land:
        ok = False
        if rtree is not None:
            gb = g.buffer(0.3)
            for i in rtree.query(gb):
                if gb.intersection(roads_all[i]).length / 2 >= 4.0:
                    ok = True; break
        land_ok[p.get("pnu")] = ok
    matched = [b for b in inb if b.get("pnu") in land_ok]
    touching = sum(1 for b in matched if land_ok[b.get("pnu")])
    # 가로구역 근사: 경계 둘레 중 도로 필지에 접한 길이 비율, 내부 도로 필지 수
    ring_line = poly_m.exterior
    road_touch = 0.0
    if rtree is not None:
        rb = ring_line.buffer(0.5)
        for i in rtree.query(rb):
            road_touch += rb.intersection(roads_all[i]).length / 2
    enclosed = min(1.0, road_touch / ring_line.length) if ring_line.length else 0
    inner_roads = sum(1 for p, g in inp if str(p.get("jibun") or "").rstrip().endswith("도") and poly_m.contains(g))
    use = lambda code: sum(1 for b in inb if str(b.get("usability") or "").startswith(code))
    return dict(
        면적_m2=round(area), 건물=n, 연계=len(known), 커버리지=round(len(known) / n * 100, 1) if n else 0,
        노후_상한=round(sum(known) / len(known) * 100, 1) if known else None,
        노후_하한=round(sum(known) / n * 100, 1) if n else None,
        노후_최대=round((sum(known) + (n - len(known))) / n * 100, 1) if n else None,
        과소필지_pct=round(small / len(land) * 100, 1) if land else None,
        호수밀도_단순=round(n / (area / 10000), 1) if area else None,
        접도율_근사=round(touching / n * 100, 1) if n else None,
        단독주택_동=use("01"), 공동주택_동=use("02"),
        가로구역_둘러싸임=round(enclosed * 100), 내부_도로필지=inner_roads,
        역거리_m=station_m,
    )


def _state(cond_lo, cond_hi):
    """상·하한 시나리오로 4상태: 둘 다 참=충족, 상한만 참=조건부, 둘 다 거짓=미충족."""
    if cond_lo and cond_hi:
        return "충족"
    if cond_hi:
        return "조건부"
    return "미충족"


def judge_types(m, is_complex=False, promo=False):
    """유형별 판정. 반환: {유형: (상태, 사유)}. 세대수는 대장 표제부가 필요해 '보류' 사유로 남긴다."""
    R = TYPE_RULES
    out = {}
    if m["건물"] == 0 or m["커버리지"] < jindan.COVERAGE_MIN * 100:
        return {k: ("보류", "대장 연계 50% 미만") for k in R}
    lo, hi = m["노후_하한"], m["노후_상한"]
    mx = m.get("노후_최대", hi)
    old = lambda th: (lo >= th * 100, hi >= th * 100 or mx >= th * 100)   # 미충족은 최댓값(미연계 전부 노후 가정)도 미달일 때만
    # 1) 주택정비형 재개발
    r = R["주택정비형 재개발"]
    o_lo, o_hi = old(r["old_min"])
    opt = (m["과소필지_pct"] is not None and m["과소필지_pct"] >= r["opt"]["small_min"] * 100) \
        or (m["접도율_근사"] is not None and m["접도율_근사"] <= r["opt"]["road_max"] * 100) \
        or (m["호수밀도_단순"] >= r["opt"]["density_min"])
    d_lo, d_hi = old(r["deem_old"])
    if m["면적_m2"] < r["area_min"]:
        out["주택정비형 재개발"] = ("미충족", f"면적 {m['면적_m2']/1e4:.2f}만㎡ < 1만㎡")
    else:
        s = _state(o_lo, o_hi)
        if s == "미충족":
            out["주택정비형 재개발"] = ("미충족", f"노후도 {lo}~{hi}% < 60%")
        else:
            if d_lo:
                why = "노후도 ≥75%로 선택요건 의제(별표1 4호 후단)"
            elif opt:
                why = "선택요건 충족(과소필지·접도율·호수밀도 중 1)"
            elif d_hi:
                s, why = "조건부", "선택요건 미충족이나 상한 기준 75% 의제 가능"
            else:
                s, why = "조건부", "필수요건 충족, 선택요건 미확정(접도율은 근사 상한값·호수밀도는 하한값이라 미충족 확정 불가)"
            out["주택정비형 재개발"] = (s, why)
    # 2) 주거환경개선
    r = R["주거환경개선"]
    dens = m["호수밀도_단순"] >= r["density_min"]
    o_lo, o_hi = old(r["old_min"])
    alt = (m["접도율_근사"] is not None and m["접도율_근사"] <= r["road_max"] * 100) or \
          (m["과소필지_pct"] is not None and m["과소필지_pct"] >= r["small_min"] * 100)
    if not dens:
        out["주거환경개선"] = ("보류", f"호수밀도 참고값(동수/ha, 특례 미반영) {m['호수밀도_단순']} < 80 — 특례 산정 전에는 미확정")
    else:
        s = _state(o_lo or alt, o_hi or alt)
        out["주거환경개선"] = (s, "호수밀도 ≥80 + " + ("노후도" if o_hi else "접도율/과소필지"))
    # 3) 도시정비형(역세권)
    r = R["도시정비형 재개발(역세권)"]
    if m["역거리_m"] is None:
        out["도시정비형 재개발(역세권)"] = ("보류", "역 승강장 거리 미산정")
    elif m["역거리_m"] > r["station_m"]:
        out["도시정비형 재개발(역세권)"] = ("미충족", f"역 {m['역거리_m']}m > 500m")
    else:
        o_lo, o_hi = old(r["old_min"])
        out["도시정비형 재개발(역세권)"] = (_state(o_lo, o_hi), f"역 {m['역거리_m']}m + 노후도 {lo}~{hi}% (제외지역 미검토)")
    # 4) 재건축
    r = R["재건축"]
    if not is_complex:
        out["재건축"] = ("해당없음", "주택단지(공동주택) 아님")
    else:
        o_lo, o_hi = old(0.60)  # 별표1 3호 다: '노후·불량건축물로서' — 단지 건물의 연한 충족을 노후 판단으로 사용
        site = m["면적_m2"] >= r["site_min"]
        s = _state(o_lo and site, o_hi and site)
        out["재건축"] = (s, ("부지 ≥1만㎡" if site else "부지 <1만㎡·세대수 200 확인 필요") + " / 재건축진단 별도")
    # 5) 가로주택
    r = R["가로주택정비"]
    th = r["old_min_promo"] if promo else r["old_min"]
    o_lo, o_hi = old(th)
    house_ok = m["단독주택_동"] >= r["house_min"]["단독"] or (m["단독주택_동"] + m["공동주택_동"]) >= r["house_min"]["합"]
    if is_complex:
        out["가로주택정비"] = ("해당없음", "주택단지는 소규모재건축 대상")
    elif m["면적_m2"] >= r["area_max"]:
        out["가로주택정비"] = ("미충족", f"면적 {m['면적_m2']/1e4:.2f}만㎡ ≥ 1.3만㎡(서울 조례)")
    else:
        block_ok = m["가로구역_둘러싸임"] >= 90 and m["내부_도로필지"] == 0
        s = _state(o_lo, o_hi)
        why = f"면적 {m['면적_m2']:,}㎡, 가로구역 둘러싸임 {m['가로구역_둘러싸임']}%" + \
              ("" if block_ok else " → 가로구역 요건 확인 필요") + \
              ("" if house_ok else ", 기존주택 호수 미달(세대수는 표제부 확인)")
        if s != "미충족" and (not house_ok or not block_ok):
            s = "보류"
        out["가로주택정비"] = (s, why)
    # 6) 소규모재건축
    r = R["소규모재건축"]
    if not is_complex:
        out["소규모재건축"] = ("해당없음", "주택단지(공동주택) 아님")
    elif m["면적_m2"] >= r["area_max"]:
        out["소규모재건축"] = ("미충족", f"면적 {m['면적_m2']/1e4:.1f}만㎡ ≥ 1만㎡")
    else:
        o_lo, o_hi = old(r["old_min"])
        out["소규모재건축"] = ("보류" if _state(o_lo, o_hi) != "미충족" else "미충족", "세대수 200 미만 여부는 표제부 확인")
    # 7) 자율주택
    r = R["자율주택정비"]
    if is_complex:
        out["자율주택정비"] = ("해당없음", "주택단지")
    elif m["단독주택_동"] >= r["house_max"]["단독"] or (m["단독주택_동"] + m["공동주택_동"]) >= r["house_max"]["합"]:
        out["자율주택정비"] = ("미충족", f"기존주택 {m['단독주택_동']+m['공동주택_동']}채 ≥ 36채(서울 조례)")
    else:
        o_lo, o_hi = old(r["old_min"])
        out["자율주택정비"] = ("보류" if _state(o_lo, o_hi) != "미충족" else "미충족", "대상지역 요건(관리지역·해제구역 등) 별도 확인")
    # 8) 소규모재개발
    r = R["소규모재개발"]
    if m["면적_m2"] >= r["area_max"]:
        out["소규모재개발"] = ("미충족", f"면적 ≥ 5천㎡")
    elif m["역거리_m"] is None:
        out["소규모재개발"] = ("보류", "역 승강장 거리 미산정")
    else:
        out["소규모재개발"] = ("미충족" if m["역거리_m"] > r["station_m"] else "보류", "역 250m 과반·도로 접함 확인")
    if is_complex:   # 정비기반시설이 양호한 주택단지(법 §2 2호 다목)는 재건축·소규모재건축 축으로만 판정
        for k in ("주택정비형 재개발", "주거환경개선", "도시정비형 재개발(역세권)"):
            out[k] = ("해당없음", "정비기반시설 양호한 주택단지 → 재건축 축")
    return out


def blocks(z, min_area=3000, max_area=12000):
    """가로구역 자동 생성: 대지 필지의 연결 성분(도로 지목 필지로 분리) → 면적 조건에 맞는 블록 목록."""
    pcls = [(f["properties"], _geom_m(f)) for f in z["pcls"]]
    land = [g.buffer(0) for p, g in pcls if not str(p.get("jibun") or "").rstrip().endswith(jindan.ROAD_SUFFIX)]
    tree = STRtree(land)
    seen, comps = set(), []
    for i in range(len(land)):
        if i in seen:
            continue
        comp, stack = [], [i]; seen.add(i)
        while stack:
            k = stack.pop(); comp.append(k)
            for j in tree.query(land[k].buffer(0.2)):
                if j not in seen and land[j].intersects(land[k].buffer(0.2)):
                    seen.add(j); stack.append(j)
        u = unary_union([land[k] for k in comp])
        if u.geom_type == "Polygon" and min_area <= u.area <= max_area:
            comps.append(Polygon(u.exterior.coords))  # 내부 구멍 제거
    return comps


if __name__ == "__main__":
    STATION = {"상계동 154-3일대": 161}   # 상계역 승강장 경계 거리(실측, 신청서 표1)
    out = []
    for fn in sorted(glob.glob(os.path.join(CACHE, "*.json"))):
        z = json.load(open(fn, encoding="utf-8"))
        poly = T(to_m, Polygon(z["rings"][0]))
        m = metrics(z, poly, z["year"], station_m=STATION.get(z["name"]))
        j = judge_types(m, is_complex=False, promo=("마천5" in z["name"]))
        out.append(dict(구역=z["name"], 구분="고시 경계" if z["year"] < 2026 else "미지정(반경 250m)", 지표=m, 판정=j))
        # 가로구역 데모: 상계·답십리에서 자동 생성한 블록 중 건물 수 최다 1개
        if z["name"] in ("상계동 154-3일대", "답십리"):
            cands = []
            for b in blocks(z):
                mb = metrics(z, b, 2026)
                if mb["건물"] >= 15:
                    cands.append((mb["건물"], b, mb))
            if cands:
                nb, b, mb = max(cands, key=lambda x: x[0])
                jb = judge_types(mb)
                out.append(dict(구역=f"{z['name']} 내 가로구역(자동 생성)", 구분="가로구역(대지 필지 연결 성분)", 지표=mb, 판정=jb,
                                경계=[list(c) for c in T(to_deg, b).exterior.coords]))
    # 재건축 단지(상계주공, 스크래치 rebuild_results 실측: 별표1 연한 충족 동수·부지 필지 면적)
    for nm, hh, site, aged, tot in (("상계주공7단지", 21, 90944, 21, 21), ("상계주공9단지", 24, 99511, 23, 23), ("상계주공10단지", 23, 112708, 23, 23)):
        m = dict(면적_m2=site, 건물=hh, 연계=tot, 커버리지=round(tot / hh * 100, 1), 노후_상한=round(aged / tot * 100, 1), 노후_하한=round(aged / hh * 100, 1),
                 과소필지_pct=0.0, 호수밀도_단순=round(hh / (site / 1e4), 1), 접도율_근사=None, 단독주택_동=0, 공동주택_동=hh,
                 가로구역_둘러싸임=0, 내부_도로필지=0, 역거리_m=None)
        out.append(dict(구역=nm, 구분="주택단지(1988 준공)", 지표=m, 판정=judge_types(m, is_complex=True)))
    json.dump(out, open(os.path.join(ROOT, "data", "type_matrix.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    types = list(TYPE_RULES)
    print("구역".ljust(26), " | ".join(t[:6] for t in types))
    for r in out:
        print(r["구역"][:26].ljust(26), " | ".join(r["판정"][t][0].ljust(6) for t in types),
              f"| 면적 {r['지표']['면적_m2']/1e4:.2f}만㎡ 노후 {r['지표']['노후_하한']}~{r['지표']['노후_상한']} 밀도 {r['지표']['호수밀도_단순']} 접도 {r['지표']['접도율_근사']} 단독 {r['지표']['단독주택_동']} 둘러싸임 {r['지표']['가로구역_둘러싸임']}")
