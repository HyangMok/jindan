# -*- coding: utf-8 -*-
"""주택접도율 — 도로 폭을 반영한 산정 (조례 §2 10호: 폭 4m 이상 도로에 길이 4m 이상 접한 대지의 건축물 비율)

도로 필지 폭 추정: 연속지적도 도로 지목('도') 필지 폴리곤의 평균 폭 ≈ 2 × 면적 / 둘레 (가늘고 긴 형상 가정).
  - 폭 4m 미만으로 추정되는 도로 필지는 접도로 인정하지 않음 (막다른 도로 6m 특례·현황도로·사도는 미반영)
  - 재개발 선택요건(§6①2나)은 도로 폭 6m 기준이므로 6m 변형도 병산
근사의 방향: 지적 도로만 세므로 현황도로 누락분만큼 과소 가능 → 이 값이 40% 이하이면 선택요건 '범위 내'로 볼 수 있는 방향(과소 근사),
  폭 미반영 값(road_access.py)은 과대 근사. 두 값이 함께 40% 이하일 때 확정.
출력: data/road_width_result.json
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


def est_width(g):
    return 2 * g.area / g.length if g.length else 0


def road_rate(z, min_width):
    """min_width: 접한 지점의 도로 폭 하한(m). 도로 폴리곤을 min_width/2 만큼 침식한 뒤 접한 구간 근처에 남아 있으면 그 지점의 폭이 min_width 이상."""
    rings = z["rings"]
    pcls = [(f["properties"], T(to_m, shape(f["geometry"]))) for f in z["pcls"]]
    roads = [(g, est_width(g)) for p, g in pcls if str(p.get("jibun") or "").rstrip().endswith("도")]
    road_g = [g for g, w in roads]
    eroded = [g.buffer(-min_width / 2) if min_width > 0 else g for g in road_g]
    lands = [(p, g) for p, g in pcls if not str(p.get("jibun") or "").rstrip().endswith(jindan.ROAD_SUFFIX)]
    if not road_g or not lands:
        return None
    tree = STRtree(road_g)
    ok = {}
    for p, g in lands:
        gb = g.buffer(0.3); hit = False
        for i in tree.query(gb):
            shared = gb.intersection(road_g[i])
            if shared.length / 2 < 4.0:
                continue
            if min_width <= 0 or (not eroded[i].is_empty and eroded[i].distance(shared) <= min_width / 2 + 0.5):
                hit = True; break
        ok[p.get("pnu")] = hit
    wide = [g for g, e in zip(road_g, eroded) if not e.is_empty]
    inb = [f["properties"] for f in z["blds"] if jindan.point_in_rings(*jindan.centroid(f["geometry"]), rings)]
    touching = sum(1 for b in inb if ok.get(b.get("pnu")))
    return dict(건물=len(inb), 접도건물=touching, 접도율=round(touching / len(inb) * 100, 1) if inb else None,
                도로필지=len(roads), 폭이상=len(wide), 폭중앙값=round(sorted(w for g, w in roads)[len(roads) // 2], 1) if roads else None)


if __name__ == "__main__":
    out = []
    for fn in sorted(glob.glob(os.path.join(CACHE, "*.json"))):
        z = json.load(open(fn, encoding="utf-8"))
        r0 = road_rate(z, 0.0); r4 = road_rate(z, 4.0); r6 = road_rate(z, 6.0)
        if not r0:
            continue
        out.append(dict(구역=z["name"], 건물=r0["건물"], 접도율_폭미반영=r0["접도율"], 접도율_4m=r4["접도율"] if r4 else None, 접도율_6m=r6["접도율"] if r6 else None,
                        도로필지=r0["도로필지"], 폭4m이상=r4["폭이상"] if r4 else 0, 폭6m이상=r6["폭이상"] if r6 else 0, 폭중앙값=r0["폭중앙값"]))
        print(f"{z['name']}: 폭 미반영 {r0['접도율']}% | 4m 이상 도로만 {r4['접도율'] if r4 else None}% | 6m 이상 {r6['접도율'] if r6 else None}% | 도로 필지 {r0['도로필지']}(4m↑ {r4['폭이상'] if r4 else 0}, 6m↑ {r6['폭이상'] if r6 else 0}, 폭 중앙값 {r0['폭중앙값']}m)")
    json.dump(out, open(os.path.join(ROOT, "data", "road_width_result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
