# -*- coding: utf-8 -*-
"""경계 강건성 지표 + 서울·경기 조례 교차 판정 — 캐시 데이터로 API 재호출 없이 계산

강건성 지표(0~100): 경계를 −40·−20·+20·+40m로 변형했을 때 노후도(상한 기준)의 최대 변동폭(%p)과
  판정 결과(충족/조건부/미충족)가 유지되는 비율로 정의.
  robustness = 100 − min(100, 변동폭×10) 를 기본으로 하되, 판정이 뒤집히는 변형이 있으면 '취약' 표시.
교차 판정: 같은 건물군에 서울 기준표와 경기 기준표를 적용해 노후도·판정 차이를 산출.
출력: data/robustness_result.json
"""
import glob
import json
import os
import sys

from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import transform as T

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jindan  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
to_m = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True).transform
to_deg = Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True).transform


def judge_local(blds, pcls, rings, year, rules):
    inb = [f["properties"] for f in blds if jindan.point_in_rings(*jindan.centroid(f["geometry"]), rings)]
    v = [jindan.judge_building(p, year, rules) for p in inb]; known = [x for x in v if x is not None]
    if not inb or not known:
        return None
    cov = len(known) / len(inb); hi = sum(known) / len(known); lo = sum(known) / len(inb)
    thr = rules["old_ratio_min"]
    mx = (sum(known) + (len(inb) - len(known))) / len(inb)   # 최댓값: 미연계 전부 노후 가정
    verdict = "보류" if cov < jindan.COVERAGE_MIN else ("충족" if lo >= thr else ("조건부" if (hi >= thr or mx >= thr) else "미충족"))
    land = [f for f in pcls if jindan.point_in_rings(*jindan.centroid(f["geometry"]), rings)
            and not str(f["properties"].get("jibun") or "").rstrip().endswith(jindan.ROAD_SUFFIX)]
    small = sum(1 for f in land if jindan.ring_area_m2(f["geometry"]["coordinates"][0][0] if f["geometry"]["type"] == "MultiPolygon"
                                                        else f["geometry"]["coordinates"][0]) < rules["small_parcel_m2"])
    return dict(n=len(inb), known=len(known), hi=round(hi * 100, 1), lo=round(lo * 100, 1), verdict=verdict,
                small=round(small / len(land) * 100, 1) if land else None)


out = []
for fn in sorted(glob.glob(os.path.join(CACHE, "*.json"))):
    z = json.load(open(fn, encoding="utf-8"))
    name, year, blds, pcls = z["name"], z["year"], z["blds"], z["pcls"]
    base_ring = z["rings"][0]
    poly_m = T(to_m, Polygon(base_ring))
    # ── 강건성 ──
    base = judge_local(blds, pcls, [base_ring], year, jindan.RULESETS["서울"])
    variants = {}
    for d in (-40, -20, 20, 40):
        g = T(to_deg, poly_m.buffer(d))
        if g.is_empty or g.geom_type != "Polygon":
            continue
        variants[d] = judge_local(blds, pcls, [list(g.exterior.coords)], year, jindan.RULESETS["서울"])
    his = [v["hi"] for v in variants.values() if v] + [base["hi"]]
    los = [v["lo"] for v in variants.values() if v] + [base["lo"]]
    swing = max(max(his) - min(his), max(los) - min(los))
    flips = sum(1 for v in variants.values() if v and v["verdict"] != base["verdict"])
    robust = max(0.0, 100 - swing * 10)
    # ── 교차 판정 ──
    gg = judge_local(blds, pcls, [base_ring], year, jindan.RULESETS["경기"])
    out.append(dict(구역=name, 기준연도=year, 건물=base["n"], 서울_노후도=f"{base['lo']}~{base['hi']}", 서울_판정=base["verdict"],
                    변동폭_p=round(swing, 1), 판정뒤집힘=flips, 강건성=round(robust), 등급=("강건" if flips == 0 and swing < 5 else ("보통" if flips == 0 else "취약")),
                    경기_노후도=f"{gg['lo']}~{gg['hi']}", 경기_판정=gg["verdict"], 경기_과소필지=gg["small"], 서울_과소필지=base["small"],
                    경계별={str(d): (v["verdict"], v["hi"], v["lo"]) for d, v in variants.items() if v}))
    print(f"{name}: 서울 {base['lo']}~{base['hi']}% {base['verdict']} | 변동 {swing:.1f}p 뒤집힘 {flips} → 강건성 {robust:.0f} | 경기 {gg['lo']}~{gg['hi']}% {gg['verdict']} (과소 {gg['small']}%)")

json.dump(out, open(os.path.join(ROOT, "data", "robustness_result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
