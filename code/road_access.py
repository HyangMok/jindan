# -*- coding: utf-8 -*-
"""주택접도율 근사 산정 — 선택요건 실투입 (캐시 데이터, API 재호출 없음)

서울 조례 §2 10호: 폭 4m 이상 도로에 길이 4m 이상 접한 대지의 건축물 수 ÷ 구역 내 건축물 총수.
근사: 연속지적도의 도로 지목 필지('도')를 도로로 보고, 건물이 속한 대지 필지가 도로 필지와 4m 이상 공유 경계를 가지면 '접도'.
  도로 폭은 필지 형상에서 직접 알 수 없어 미반영(폭 4m 미만 도로가 포함되면 접도율이 과대) → 근사·상한값으로 표기.
출력: data/road_access_result.json
"""
import glob
import json
import os
import sys

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as T
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jindan  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
to_m = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True).transform

out = []
for fn in sorted(glob.glob(os.path.join(CACHE, "*.json"))):
    z = json.load(open(fn, encoding="utf-8"))
    rings = z["rings"]
    pcls = [(f["properties"], T(to_m, shape(f["geometry"]))) for f in z["pcls"]]
    roads = [g for p, g in pcls if str(p.get("jibun") or "").rstrip().endswith("도")]
    lands = [(p, g) for p, g in pcls if not str(p.get("jibun") or "").rstrip().endswith(jindan.ROAD_SUFFIX)]
    if not roads or not lands:
        continue
    rtree = STRtree(roads)
    # 대지 필지별 접도 여부(도로 필지와 공유 경계 ≥ 4m)
    land_ok = {}
    for p, g in lands:
        ok = False
        for i in rtree.query(g.buffer(0.3)):
            shared = g.buffer(0.3).intersection(roads[i]).length / 2  # 버퍼 교차 둘레의 절반 ≈ 공유 경계 길이
            if shared >= 4.0:
                ok = True; break
        land_ok[p.get("pnu")] = ok
    # 구역 내 건물 → 소속 필지(PNU) → 접도 여부
    inb = [f["properties"] for f in z["blds"] if jindan.point_in_rings(*jindan.centroid(f["geometry"]), rings)]
    total = len(inb); matched = [b for b in inb if b.get("pnu") in land_ok]
    touching = sum(1 for b in matched if land_ok[b.get("pnu")])
    rate = touching / total * 100 if total else None
    rate_matched = touching / len(matched) * 100 if matched else None
    out.append(dict(구역=z["name"], 건물=total, PNU매칭=len(matched), 접도건물=touching,
                    접도율_근사=round(rate, 1), 접도율_매칭기준=round(rate_matched, 1), 도로필지=len(roads)))
    print(f"{z['name']}: 건물 {total} (PNU 매칭 {len(matched)}) | 접도 {touching} → 접도율 근사 {rate:.1f}% (매칭 기준 {rate_matched:.1f}%) | 도로 필지 {len(roads)}")

json.dump(out, open(os.path.join(ROOT, "data", "road_access_result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("서울 조례 §6①2나: 재개발 선택요건 주택접도율 ≤ 40% (도로 폭 6m 기준) — 본 근사는 폭 미반영 상한값")
