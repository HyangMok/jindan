# -*- coding: utf-8 -*-
"""검증 구역의 건물·필지 원자료를 로컬 캐시(data/cache/*.json)에 저장 — 이후 분석은 API 재호출 없이 수행"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jindan  # noqa: E402
import shapefile  # noqa: E402
from pyproj import Transformer  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
os.makedirs(CACHE, exist_ok=True)
SHP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "shp", "UPIS_C_UQ181")  # 서울 열린데이터광장 의제처리구역 위치정보(OA-20957) SHP를 data/shp/ 에 압축 해제

ZONES = [(1174, "상계동 154-3일대", 2025), (2545, "창신동 23일대", 2025), (596, "마천5", 2024), (1104, "신림7", 2024),
         (699, "고척동 253일대", 2024), (1849, "면목7", 2024), (461, "서계 통합구역", 2024), (1258, "상도14", 2025),
         (2062, "대림1", 2025), (2765, "방학3", 2025)]
UNDESIGNATED = [("서울특별시 관악구 신림동 1420", "신림 난곡"), ("서울특별시 동대문구 답십리동 471", "답십리"), ("서울특별시 중랑구 망우동 486", "망우")]

r = shapefile.Reader(SHP, encoding="cp949")
tr = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)


def rings_of(rid):
    shp = r.shape(rid)
    parts = list(shp.parts) + [len(shp.points)]
    return [[list(tr.transform(x, y)) for x, y in shp.points[a:b]] for a, b in zip(parts[:-1], parts[1:])]


def save(name, rings, year, blds, pcls):
    json.dump({"name": name, "year": year, "rings": rings, "blds": blds, "pcls": pcls},
              open(os.path.join(CACHE, name.replace(" ", "_") + ".json"), "w", encoding="utf-8"), ensure_ascii=False)


for rid, name, yr in ZONES:
    fn = os.path.join(CACHE, name.replace(" ", "_") + ".json")
    if os.path.exists(fn):
        print("skip", name); continue
    rings = rings_of(rid)
    xs = [p[0] for rg in rings for p in rg]; ys = [p[1] for rg in rings for p in rg]
    bbox = (min(xs) - 0.0006, min(ys) - 0.0006, max(xs) + 0.0006, max(ys) + 0.0006)  # 감도 분석용 여유 60m
    blds = jindan.wfs_collect("lt_c_bldginfo", bbox)
    pcls = jindan.wfs_collect("lp_pa_cbnd_bubun", bbox)
    save(name, rings, yr, blds, pcls)
    print(name, "건물", len(blds), "필지", len(pcls))

import math  # noqa: E402
for addr, name in UNDESIGNATED:
    fn = os.path.join(CACHE, name.replace(" ", "_") + ".json")
    if os.path.exists(fn):
        print("skip", name); continue
    cx, cy = jindan.geocode(addr)
    dlat = 250 / 110540; dlon = 250 / (111320 * math.cos(math.radians(cy)))
    ring = [[cx + dlon * math.cos(t * math.pi / 18), cy + dlat * math.sin(t * math.pi / 18)] for t in range(37)]
    bbox = (cx - dlon * 1.3, cy - dlat * 1.3, cx + dlon * 1.3, cy + dlat * 1.3)
    blds = jindan.wfs_collect("lt_c_bldginfo", bbox)
    pcls = jindan.wfs_collect("lp_pa_cbnd_bubun", bbox)
    save(name, [ring], 2026, blds, pcls)
    print(name, "건물", len(blds), "필지", len(pcls))
print("캐시 완료")
