# -*- coding: utf-8 -*-
"""호수밀도 — 조례 §2 5호 산정 특례 근사 (표제부 세대수·층수 이용)

조례 §2 5호: 호수밀도 = 정비구역 1ha당 건축물 동수.
  가. 공동주택·다가구주택은 세대수가 가장 많은 층의 1세대를 1동으로 봄(나머지 층 세대는 미계상)
     → 표제부에 층별 세대수는 없으므로 세대수 ÷ 지상층수(올림)로 '최다층 세대수'를 근사
  나. 특정무허가건축물 포함, 신발생무허가 제외 → 대장 없는 건물은 1동으로 계상(무허가 구분 불가, 상한 방향)
  다. 존치 공원·학교 면적 제외 → 미반영(면적이 커져 밀도 과소 방향)
구역 내 모든 건물의 표제부를 조회(필지 단위 캐시 data/ledger_cache/<pnu>.json)하므로 호출 수 = 필지 수.
사용: python density.py 상도14
출력: data/density_result.json
"""
import glob
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jindan  # noqa: E402
import join_ledger as J  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
LCACHE = os.path.join(ROOT, "data", "ledger_cache")
os.makedirs(LCACHE, exist_ok=True)


def ledger(key, pnu, calls):
    fp = os.path.join(LCACHE, pnu + ".json")
    if os.path.exists(fp):
        return json.load(open(fp, encoding="utf-8"))
    for _ in range(3):
        try:
            items = J.title_info(key, pnu); calls[0] += 1
            json.dump(items, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
            return items
        except Exception as e:
            err = e
    print("  조회 실패", pnu, str(err)[:40])
    return None


def main(zone_name, max_calls=450):
    key = J.load_key()
    fn = next((f for f in glob.glob(os.path.join(CACHE, "*.json")) if zone_name in os.path.basename(f)), None)
    z = json.load(open(fn, encoding="utf-8"))
    rings = z["rings"]
    inb = [f["properties"] for f in z["blds"] if jindan.point_in_rings(*jindan.centroid(f["geometry"]), rings)]
    area_ha = (jindan.ring_area_m2(rings[0]) - sum(jindan.ring_area_m2(r) for r in rings[1:])) / 10000
    pnus = sorted({p["pnu"] for p in inb if p.get("pnu")})
    print(f"{z['name']}: 건물 {len(inb)} / 필지 {len(pnus)} / 면적 {area_ha:.2f}ha")
    calls = [0]
    per_pnu = {}
    for pnu in pnus:
        if calls[0] >= max_calls:
            print("  호출 한도 도달 — 중단"); break
        per_pnu[pnu] = ledger(key, pnu, calls)
    # 필지별 표제부 목록 → 동수 산정. 필지 안의 브이월드 건물 수와 표제부 동 수가 다르면 표제부 기준(대장 기준이 조례 정의).
    units_special = 0.0; units_simple = 0; matched_pnu = 0; unmatched_bld = 0; apt_bld = 0
    counted = set()
    for p in inb:
        pnu = p.get("pnu")
        items = per_pnu.get(pnu)
        if items is None:
            units_simple += 1; units_special += 1; unmatched_bld += 1; continue   # 미조회 → 1동
        if pnu in counted:
            continue
        counted.add(pnu); matched_pnu += 1
        if not items:
            # 표제부 없음(무허가 후보): 브이월드 건물 수만큼 1동씩
            k = sum(1 for q in inb if q.get("pnu") == pnu); units_simple += k; units_special += k; continue
        for it in items:
            units_simple += 1
            use = str(it.get("mainPurpsCd") or "")
            hh = int(it["hhldCnt"]) if str(it.get("hhldCnt") or "").isdigit() else 0
            fl = int(it["grndFlrCnt"]) if str(it.get("grndFlrCnt") or "").isdigit() and int(it["grndFlrCnt"]) > 0 else 1
            if use.startswith("02") or "다가구" in str(it.get("mainPurpsCdNm") or "") or hh > 1:
                units_special += max(1, math.ceil(hh / fl)); apt_bld += 1
            else:
                units_special += 1
    res = dict(구역=z["name"], 면적_ha=round(area_ha, 2), 건물_브이월드=len(inb), 필지=len(pnus), 조회필지=matched_pnu, API호출=calls[0],
               동수_단순=units_simple, 동수_특례근사=round(units_special), 공동다가구=apt_bld,
               호수밀도_단순=round(units_simple / area_ha, 1), 호수밀도_특례근사=round(units_special / area_ha, 1),
               재개발_선택요건60=(units_special / area_ha) >= 60, 주거환경개선80=(units_special / area_ha) >= 80)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    out = os.path.join(ROOT, "data", "density_result.json")
    prev = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
    prev = [r for r in prev if r["구역"] != res["구역"]] + [res]
    json.dump(prev, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "상도14", int(sys.argv[2]) if len(sys.argv) > 2 else 450)
