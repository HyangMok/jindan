# -*- coding: utf-8 -*-
"""건축물대장 표제부 조인 — 대장 미연계 건물의 사용승인일 보완 (공공데이터포털 건축HUB API)

사용: .env 에 BLDG_KEY=<공공데이터포털 인증키(Decoding)> 추가 후
      python join_ledger.py "상계동 154-3일대"
동작: data/cache/<구역>.json 의 건물 중 useapr_day 가 없는 건물의 PNU(시군구코드·법정동코드·번·지)로
      표제부(getBrTitleInfo)를 조회해 사용승인일(useAprDay)·구조(strctCdNm)·세대수(hhldCnt)를 채우고,
      조인 전/후 노후도(보수값~연계값)와 커버리지를 비교해 data/join_result.json 에 기록.
API: https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo (무상, 일 1,000건 기본 한도)
"""
import glob
import json
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jindan  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
URL = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"


def load_key():
    k = os.environ.get("BLDG_KEY")
    if not k:
        env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env):
            for line in open(env, encoding="utf-8"):
                if line.startswith("BLDG_KEY="):
                    k = line.split("=", 1)[1].strip()
    if not k:
        raise SystemExit("BLDG_KEY 없음 — 공공데이터포털에서 건축HUB(건축물대장정보) 활용신청 후 .env 에 BLDG_KEY= 추가")
    return k


LCACHE = os.path.join(ROOT, "data", "ledger_cache")
os.makedirs(LCACHE, exist_ok=True)


def title_info(key, pnu):
    """PNU(19자리) → 표제부 목록. 시군구 5 + 법정동 5 + 대지구분 1 + 번 4 + 지 4. 필지 단위로 파일 캐시."""
    fp = os.path.join(LCACHE, pnu + ".json")
    if os.path.exists(fp):
        return json.load(open(fp, encoding="utf-8"))
    gb = "1" if pnu[10] == "2" else "0"   # PNU 11번째 자리: 1=일반(대지), 2=산 → 건축HUB platGbCd 0=대지, 1=산
    q = dict(serviceKey=key, sigunguCd=pnu[:5], bjdongCd=pnu[5:10], platGbCd=gb, bun=pnu[11:15], ji=pnu[15:19], numOfRows=50, pageNo=1)
    data = urllib.request.urlopen(URL + "?" + urllib.parse.urlencode(q), timeout=30).read()
    root = ET.fromstring(data)
    items = [{c.tag: c.text for c in item} for item in root.iter("item")]
    json.dump(items, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
    return items


def main(zone_name):
    key = load_key()
    fn = next((f for f in glob.glob(os.path.join(CACHE, "*.json")) if zone_name in os.path.basename(f)), None)
    if not fn:
        raise SystemExit("캐시 구역 없음: " + zone_name)
    z = json.load(open(fn, encoding="utf-8"))
    rings = z["rings"]; year = z["year"]
    inb = [f["properties"] for f in z["blds"] if jindan.point_in_rings(*jindan.centroid(f["geometry"]), rings)]
    before = [jindan.judge_building(p, year) for p in inb]
    missing = [p for p, v in zip(inb, before) if v is None and p.get("pnu")]
    print(f"{z['name']}: 건물 {len(inb)} / 미연계 {sum(v is None for v in before)} / PNU 보유 미연계 {len(missing)}")
    filled, calls, no_ledger, multi_ambig = 0, 0, 0, 0
    cache = {}
    for p in missing:
        pnu = p["pnu"]
        if pnu not in cache:
            for _try in range(3):
                try:
                    cache[pnu] = title_info(key, pnu); calls += 1; break
                except Exception as e:
                    cache[pnu] = []; print("  조회 실패", pnu, str(e)[:40])
        items = [it for it in cache[pnu] if it.get("useAprDay")]
        if not items:
            no_ledger += 1; continue
        # 같은 필지에 여러 동: 연면적으로 매칭, 연면적이 없으면 전 동의 노후 판정이 일치할 때만 채움(불일치는 미확정)
        ta0 = float(p.get("totalarea") or 0)
        if ta0 > 0 or len(items) == 1:
            it = min(items, key=lambda it: abs(float(it.get("totArea") or 0) - ta0)) if ta0 > 0 else items[0]
        else:
            vs = set()
            for it in items:
                q = dict(p); q["useapr_day"] = it["useAprDay"][:8]; q["strct_cd"] = q.get("strct_cd") or it.get("strctCd"); q["usability"] = q.get("usability") or it.get("mainPurpsCd"); q["grnd_flr"] = q.get("grnd_flr") or (int(it["grndFlrCnt"]) if str(it.get("grndFlrCnt") or "").isdigit() else None)
                vs.add(jindan.judge_building(q, year))
            if len(vs) != 1:
                multi_ambig += 1; continue
            it = items[0]
        p["useapr_day"] = it["useAprDay"][:8]
        p["strct_cd"] = p.get("strct_cd") or it.get("strctCd")
        p["usability"] = p.get("usability") or it.get("mainPurpsCd")
        p["grnd_flr"] = p.get("grnd_flr") or (int(it["grndFlrCnt"]) if str(it.get("grndFlrCnt") or "").isdigit() else None)
        p["hhld_cnt"] = it.get("hhldCnt")
        filled += 1
    after = [jindan.judge_building(p, year) for p in inb]

    def stat(v):
        known = [x for x in v if x is not None]
        return dict(커버리지=round(len(known) / len(v) * 100, 1), 연계값=round(sum(known) / len(known) * 100, 1) if known else None,
                    보수값=round(sum(known) / len(v) * 100, 1), 최댓값=round((sum(known) + len(v) - len(known)) / len(v) * 100, 1))
    res = dict(구역=z["name"], 기준연도=year, 건물=len(inb), 미연계_전=sum(x is None for x in before), 보완=filled, 대장없음=no_ledger, 다동필지_미확정=multi_ambig, API호출=calls,
               조인_전=stat(before), 조인_후=stat(after))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    # 조인된 속성을 포함한 캐시 사본 저장(진단서·데모용)
    jd = os.path.join(ROOT, "data", "cache_joined"); os.makedirs(jd, exist_ok=True)
    json.dump(z, open(os.path.join(jd, os.path.basename(fn)), "w", encoding="utf-8"), ensure_ascii=False)
    out = os.path.join(ROOT, "data", "join_result.json")
    prev = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
    prev = [r for r in prev if r["구역"] != res["구역"]] + [res]
    json.dump(prev, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "상계동")
