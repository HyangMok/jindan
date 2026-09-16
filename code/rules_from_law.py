# -*- coding: utf-8 -*-
"""조례 별표 → 기준표 자동 생성기 (법령정보 연계의 실체)

국가법령정보 API(자치법규 XML)에서 조례를 받아
 1) 별표 첨부(hwp)를 내려받아 표를 파싱 → 공동주택 노후 연한표(5층 이상/4층 이하)
 2) 조문에서 재개발 노후도·과소필지 임계값, 면적 요건, 비공동주택 연한을 추출
하여 jindan.RULESETS와 같은 구조의 기준표를 만든다. 수동 기준표와 대조해 일치 여부를 검증.
"""
import re, zlib, struct, io, sys, json, urllib.request, urllib.parse
import olefile

def _load_oc():
    """국가법령정보 API 인증 ID(OC) — 환경변수 LAW_OC 또는 코드 폴더 .env 의 LAW_OC=... (law.go.kr 오픈API 신청 시 발급, 이메일 ID)"""
    import os
    v = os.environ.get("LAW_OC")
    if not v:
        env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env):
            for line in open(env, encoding="utf-8"):
                if line.startswith("LAW_OC="):
                    v = line.split("=", 1)[1].strip()
    if not v:
        raise SystemExit("LAW_OC 없음 — .env 에 LAW_OC=<법령정보 OC> 추가")
    return v


OC = _load_oc()

def _get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()

def fetch_ordin_xml(mst):
    return _get(f"http://www.law.go.kr/DRF/lawService.do?OC={OC}&target=ordin&MST={mst}&type=XML").decode("utf-8")

def hwp_text(data):
    f = olefile.OleFileIO(io.BytesIO(data)); comp = f.openstream("FileHeader").read()[36] & 1; out = []
    for e in f.listdir():
        if e[0] != "BodyText": continue
        d = f.openstream(e).read(); d = zlib.decompress(d, -15) if comp else d; i = 0
        while i < len(d):
            h = struct.unpack_from("<I", d, i)[0]; tag, size = h & 0x3FF, (h >> 20) & 0xFFF; i += 4
            if size == 0xFFF: size = struct.unpack_from("<I", d, i)[0]; i += 4
            if tag == 67:
                t = d[i:i+size].decode("utf-16le", "ignore"); t = re.sub(r"[\x00-\x1f]", " ", t)
                t = re.sub(r"[\u4e00-\u9fff\ue000-\uf8ff]{2,}", "", t).strip()
                if t: out.append(t)
            i += size
    return out

def strip(x): return re.sub(r"<!\[CDATA\[|\]\]>|<[^>]+>", "", x)

def parse_apt_table(cells):
    """별표1 셀 시퀀스 → [(준공연도상한, 5층↑연한), ...], [(연도상한, 4층↓연한), ...]
    셀 패턴: 연도 라벨 다음에 1개 또는 2개의 'N년' 셀. 1개면 5층↑ 열이 상위 행과 병합(30년 유지)."""
    rows5, rows4, last5 = [], [], None
    i = 0
    while i < len(cells):
        c = cells[i]
        m_before = re.match(r"^(\d{4})[년.\s\d]*이전", c); m_after = re.match(r"^(\d{4})[년.\s\d]*이후", c); m_year = re.match(r"^(\d{4})년?$", c)
        if m_before or m_after or m_year:
            year = int((m_before or m_after or m_year).group(1))
            ymax = year if (m_before or m_year) else 9999
            yrs = []
            j = i + 1
            while j < len(cells) and re.match(r"^\d{1,2}년$", cells[j]) and len(yrs) < 2:
                yrs.append(int(cells[j][:-1])); j += 1
            if len(yrs) == 2: last5 = yrs[0]; rows5.append((ymax, yrs[0])); rows4.append((ymax, yrs[1]))
            elif len(yrs) == 1:
                if last5 is None: rows5.append((ymax, yrs[0])); rows4.append((ymax, yrs[0]))
                else: rows5.append((ymax, last5)); rows4.append((ymax, yrs[0]))
            i = j
        else:
            i += 1
    # 정리: 5층↑은 마지막 값 유지 구간을 압축
    def compress(rows):
        out = []
        for ymax, lim in rows:
            if out and out[-1][1] == lim and ymax != 9999: out[-1] = (ymax, lim)
            else: out.append((ymax, lim))
        if out and out[-1][0] != 9999: out.append((9999, out[-1][1]))
        return out
    return compress(rows5), compress(rows4)

def build_rules(mst, name):
    xml = fetch_ordin_xml(mst)
    # ── 별표1 (공동주택 연한표) ──
    cells = None
    for b in re.split(r"(?=<별표번호>)", xml):
        t = re.search(r"<별표제목>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</별표제목>", b)
        if not (t and "노후" in t.group(1)): continue
        body = strip(re.search(r"<별표내용>(.*?)</별표내용>", b, re.S).group(1)) if "<별표내용>" in b else ""
        if "년" in body and "┼" in body:  # 본문에 표가 인라인된 경우(서울)
            cells = [c.strip() for c in re.split(r"[│┃|]", body) if c.strip() and not re.fullmatch(r"[─┌┐└┘├┤┬┴┼\s]+", c)]
        else:  # 첨부 hwp (경기)
            link = re.search(r"(https?://www\.law\.go\.kr/flDownload\.do\?[^<\]\s]+)", b)
            cells = hwp_text(_get(link.group(1).replace("&amp;", "&")))
        break
    rows5, rows4 = parse_apt_table(cells)
    # ── 조문: 임계값 ──
    text = strip(xml)
    seg = text
    for mm in re.finditer(r"(주택정비형 재개발구역|재개발사업은)(.{0,900})", text, re.S):
        if "노후" in mm.group(0) and ("퍼센트" in mm.group(0) or "%" in mm.group(0)):
            seg = mm.group(0); break
    m = re.search(r"노후[ㆍ·]?불량건축물의 수가[^%퍼]{0,60}?(\d{2})\s*(?:퍼센트|%)", seg)
    old_min = int(m.group(1)) / 100 if m else None
    m2 = re.search(r"과소필지[^%퍼]{0,80}?(\d{2})\s*(?:퍼센트|%)\s*이상", seg)
    small_min = int(m2.group(1)) / 100 if m2 else None
    m3 = re.search(r"토지면적이\s*(\d+)\s*제곱미터\s*미만", text)
    small_m2 = int(m3.group(1)) if m3 else 90
    m4 = re.search(r"(?:시[ㆍ·]도\s*)?조례로 정하는 면적[^0-9]{0,20}(\d+)\s*(?:만)?\s*제곱미터", text)
    area_min = (int(m4.group(1)) * (10000 if "만" in text[m4.start():m4.end()] else 1)) if m4 else 10000
    m5 = re.search(r"단독주택[^:：]{0,60}(?:철근콘크리트|철골)[^:：]{0,80}[:：]\s*(\d{2})년", text)
    nonhouse_rc = int(m5.group(1)) if m5 else 30
    m6 = re.search(r"가목 이외의 (?:공동주택|건축물)[^:：]{0,30}[:：]?\s*(\d{2})년", text)
    default = int(m6.group(1)) if m6 else 20
    return {"name": name, "mst": mst, "apt_5up": rows5, "apt_4dn": rows4, "apt_other": default,
            "nonhouse_rc": nonhouse_rc, "default": default, "old_ratio_min": old_min,
            "small_parcel_m2": small_m2, "small_parcel_min": small_min, "area_min_m2": area_min}

if __name__ == "__main__":
    sys.path.insert(0, ".")
    import jindan
    out = {}
    for name, mst in (("서울", 2130189), ("경기", 2136197)):
        r = build_rules(mst, name); out[name] = r
        man = jindan.RULESETS[name]
        # 수동 기준표와 대조: 1975~2000년 각 연도, 5층↑/4층↓ 연한 비교
        def auto_limit(y, five):
            for ymax, lim in (r["apt_5up"] if five else r["apt_4dn"]):
                if y <= ymax: return lim
            return 30
        mism = [(y, f) for y in range(1975, 2001) for f in (True, False) if auto_limit(y, f) != man["apt_limit"](y, f)]
        print(f"[{name}] 별표 자동 파싱: 5층↑ {r['apt_5up']} | 4층↓ {r['apt_4dn']}")
        print(f"       임계값: 노후도 {r['old_ratio_min']} 과소필지 {r['small_parcel_min']}({r['small_parcel_m2']}㎡) 면적 {r['area_min_m2']} | 비공동RC {r['nonhouse_rc']} 기타 {r['default']}")
        print(f"       수동 기준표 대조(1975~2000, 5층↑/4층↓ 52케이스): 불일치 {len(mism)}건 {mism[:4]}")
        ok = (r['old_ratio_min'] == man['old_ratio_min'] and r['small_parcel_min'] == man['small_parcel_min'] and r['area_min_m2'] == man['area_min_m2'])
        print(f"       임계값 일치: {ok}")
    json.dump(out, open("../data/기준표_자동생성.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
