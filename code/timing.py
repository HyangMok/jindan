# -*- coding: utf-8 -*-
"""충족 예상 시점 — 건물별 사용승인일 분포로 노후도 필수요건(60%) 도달 연도 산출 (진단서 3장, 지자체 모드)

캐시 데이터로 API 재호출 없이 계산. 기준연도를 올려가며 판정을 반복해
  - 보수값 기준(미연계 건물 비노후 가정) 도달 연도 = 보수적 상한
  - 연계값 기준 도달 연도 = 낙관적 하한
을 구한다. 별표1 연한은 준공연도·구조·층수에 따라 20~30년이므로 단순 '준공+30년'이 아니라 기준표를 그대로 적용.
출력: data/timing_result.json
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jindan  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
THR = 60.0
YEARS = range(2026, 2051)


def reach_year(blds, thr=THR, rules=None):
    rules = rules or jindan.RULESETS["서울"]
    n = len(blds)
    out = {"보수값": None, "연계값": None, "곡선": {}}
    for y in YEARS:
        v = [jindan.judge_building(p, y, rules) for p in blds]
        known = [x for x in v if x is not None]
        cons = sum(known) / n * 100 if n else 0
        link = sum(known) / len(known) * 100 if known else 0
        out["곡선"][y] = (round(cons, 1), round(link, 1))
        if out["보수값"] is None and cons >= thr:
            out["보수값"] = y
        if out["연계값"] is None and link >= thr:
            out["연계값"] = y
    return out


if __name__ == "__main__":
    res = []
    for fn in sorted(glob.glob(os.path.join(CACHE, "*.json"))):
        z = json.load(open(fn, encoding="utf-8"))
        inb = [f["properties"] for f in z["blds"] if jindan.point_in_rings(*jindan.centroid(f["geometry"]), z["rings"])]
        r = reach_year(inb)
        c26 = r["곡선"][2026]; c36 = r["곡선"][2036]
        res.append(dict(구역=z["name"], 건물=len(inb), 노후도_2026=c26, 노후도_2036=c36, 도달연도_보수값=r["보수값"], 도달연도_연계값=r["연계값"],
                        곡선={str(k): v for k, v in r["곡선"].items() if k in (2026, 2028, 2030, 2032, 2034, 2036, 2040)}))
        print(f"{z['name']}: 2026 {c26[0]}~{c26[1]}% → 2036 {c36[0]}~{c36[1]}% | 60% 도달: 보수값 {r['보수값']} / 연계값 {r['연계값']}")
    json.dump(res, open(os.path.join(ROOT, "data", "timing_result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
