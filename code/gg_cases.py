# -*- coding: utf-8 -*-
"""경기도 실지 판정 — 이용자 경계(반경 250m) 모드로 경기 노후 저층지에 경기 기준표를 적용 (기준표 교체의 실지 검증)

같은 건물군에 서울 기준표도 적용해 결론 차이를 병기. 공식 경계는 서울 외 미개방이라 ② 모드로만 판정.
출력: data/gg_cases.json
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jindan  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDS = ["경기도 성남시 수정구 수진동 2100", "경기도 부천시 원미구 원미동 130", "경기도 안양시 만안구 안양동 620-1", "경기도 광명시 광명동 158"]


def judge(address, rules, radius_m=250):
    cx, cy = jindan.geocode(address)
    dlat = radius_m / 110540; dlon = radius_m / (111320 * math.cos(math.radians(cy)))
    ring = [[cx + dlon * math.cos(t * math.pi / 18), cy + dlat * math.sin(t * math.pi / 18)] for t in range(37)]
    return jindan.judge_zone([ring], address, math.pi * radius_m ** 2, 2026, rules)


if __name__ == "__main__":
    out = []
    for a in CANDS:
        try:
            g = judge(a, jindan.RULESETS["경기"]); s = judge(a, jindan.RULESETS["서울"])
            d = {k: v for k, v in g.items() if not k.startswith("_")}
            d["서울기준_노후도"] = f"{s['노후도_pct_보수']}~{s['노후도_pct']}"; d["서울기준_판정"] = s["노후도_판정"]; d["서울기준_과소필지"] = s["과소필지_pct"]
            n, kn, old = d["건물_총"], d["건물_판정가능"], d["건물_노후"]; d["노후도_최대"] = round((old + n - kn) / n * 100, 1) if n else None
            out.append(d)
            print(f"{a}: 건물 {n} 커버 {d['판정커버리지']}% | 경기 기준(50%) {d['노후도_pct_보수']}~{d['노후도_pct']}% {d['노후도_판정']} 과소 {d['과소필지_pct']}% | 서울 기준(60%) {d['서울기준_노후도']}% {d['서울기준_판정']}")
        except Exception as e:
            print(a, "ERR", repr(e)[:80])
    json.dump(out, open(os.path.join(ROOT, "data", "gg_cases.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
