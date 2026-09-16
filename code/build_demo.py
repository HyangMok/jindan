# 노후도 지도 데모 빌드 — GeoJSON 3종을 인라인한 단일 HTML 생성
import json
import os
import sys

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(D, "code")); import jindan  # noqa: E402
ZONE_FILE = "상계동_154-3일대.json"
_src = os.path.join(D, "data", "cache_joined", ZONE_FILE)
if not os.path.exists(_src):
    _src = os.path.join(D, "data", "cache", ZONE_FILE)   # 표제부 조인 전 캐시로도 동작
z = json.load(open(_src, encoding="utf-8"))
YEAR = z.get("year", 2025)
rings = z["rings"]
zone = json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": rings}, "properties": {"name": z["name"]}}]}, ensure_ascii=False)
_bf = []
for f in z["blds"]:
    if not jindan.point_in_rings(*jindan.centroid(f["geometry"]), rings):
        continue
    p = f["properties"]; v = jindan.judge_building(p, YEAR)
    yr = int(p["useapr_day"][:4]) if p.get("useapr_day") and str(p["useapr_day"])[:4].isdigit() else None
    _bf.append({"type": "Feature", "geometry": f["geometry"], "properties": {"nm": p.get("bld_nm") or "", "yr": yr, "age": (YEAR - yr) if yr else None, "flr": p.get("grnd_flr"), "strct": p.get("strct_cd"), "use": p.get("usability"), "old": v, "area": p.get("totalarea")}})
blds = json.dumps({"type": "FeatureCollection", "features": _bf}, ensure_ascii=False)
_pf = []
for f in z["pcls"]:
    if not jindan.point_in_rings(*jindan.centroid(f["geometry"]), rings):
        continue
    p = f["properties"]; jb = str(p.get("jibun") or "").rstrip()
    if jb.endswith(jindan.ROAD_SUFFIX):
        continue
    g = f["geometry"]; ring = g["coordinates"][0][0] if g["type"] == "MultiPolygon" else g["coordinates"][0]
    area = round(jindan.ring_area_m2(ring), 1)
    _pf.append({"type": "Feature", "geometry": g, "properties": {"jibun": jb, "area": area, "small": area < jindan.RULESETS["서울"]["small_parcel_m2"]}})
pcls = json.dumps({"type": "FeatureCollection", "features": _pf}, ensure_ascii=False)

html = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>우리동네 정비진단 — 상계5동 실증 데모</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root {
    --ink: #1a1d21; --ink2: #52575e; --ink3: #878d96;
    --surface: #fcfcfb; --panel: #ffffff; --line: #e4e6e9;
    --old: #C4320A; --ok: #175CD3; --na: #98A2B3; --small: #6941C6;
    --good-bg: #e8f5ee; --good-fg: #067647;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Pretendard', 'Malgun Gothic', sans-serif; background: var(--surface); color: var(--ink); height: 100vh; display: flex; flex-direction: column; }
  header { padding: 14px 20px 12px; border-bottom: 1px solid var(--line); background: var(--panel); }
  header h1 { font-size: 17px; font-weight: 700; }
  header h1 .accent { color: var(--old); }
  header p { font-size: 12px; color: var(--ink2); margin-top: 3px; }
  .wrap { flex: 1; display: flex; min-height: 0; }
  aside { width: 296px; flex: none; overflow-y: auto; background: var(--panel); border-right: 1px solid var(--line); padding: 16px; }
  #map { flex: 1; background: #dfe3e8; }
  .hero { border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; }
  .hero .label { font-size: 12px; color: var(--ink2); }
  .hero .num { font-size: 34px; font-weight: 800; color: var(--old); line-height: 1.15; }
  .hero .sub { font-size: 12px; color: var(--ink2); margin-top: 2px; }
  .badge { display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 99px; background: var(--good-bg); color: var(--good-fg); margin-left: 6px; vertical-align: 4px; }
  .badge.no { background: #f2f4f7; color: var(--ink2); }
  h2 { font-size: 12px; font-weight: 700; color: var(--ink2); text-transform: none; margin: 14px 0 6px; }
  table.req { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }
  table.req td:first-child { width: 62%; }
  table.req td { word-break: keep-all; }
  table.req td { padding: 5px 4px; border-bottom: 1px solid var(--line); vertical-align: top; }
  table.req td:last-child { text-align: right; white-space: nowrap; }
  .mode { display: flex; gap: 6px; margin: 6px 0 10px; }
  .mode button { flex: 1; font-size: 12px; padding: 6px 4px; border: 1px solid var(--line); background: var(--panel); border-radius: 8px; cursor: pointer; color: var(--ink2); }
  .mode button.on { border-color: var(--ink); color: var(--ink); font-weight: 700; }
  .legend { font-size: 12px; color: var(--ink2); }
  .legend .row { display: flex; align-items: center; gap: 7px; padding: 2.5px 0; }
  .sw { width: 14px; height: 14px; border-radius: 3px; flex: none; }
  .toggles label { display: flex; gap: 7px; align-items: center; font-size: 12px; color: var(--ink2); padding: 3px 0; cursor: pointer; }
  .note { font-size: 11px; color: var(--ink3); line-height: 1.5; margin-top: 14px; border-top: 1px solid var(--line); padding-top: 10px; }
  .leaflet-tooltip.bld { font-family: inherit; font-size: 12px; line-height: 1.55; border: 1px solid var(--line); box-shadow: 0 4px 14px rgba(0,0,0,.12); border-radius: 8px; padding: 8px 10px; }
  .tt-title { font-weight: 700; }
  .tt-verdict { font-weight: 700; }
  .tt-verdict.old { color: var(--old); } .tt-verdict.ok { color: var(--ok); } .tt-verdict.na { color: var(--na); }
  .src { font-size: 11px; color: var(--ink3); }
</style>
</head>
<body>
<header>
  <h1>우리동네 정비진단 <span class="accent">— 상계동 154-3일대 재개발구역 실증</span></h1>
  <p>서울특별시고시 제2025-218호(2025.4.17. 지정) · 216,364.5㎡ · 브이월드 개방 데이터 + 건축물대장 표제부 조인 기반 자동 판정 데모 (기준연도 2025, 고시년)</p>
</header>
<div class="wrap">
<aside>
  <div class="hero">
    <div class="label">노후·불량건축물 비율 <span style="color:var(--ink3)">(서울 조례 제4조·별표1)</span></div>
    <div class="num">81.3%<span class="badge">필수요건 충족</span></div>
    <div class="sub">판정 가능 1,013동 중 824동 · 보수값(미연계 비노후 가정) 78.1% · 기준 60% · 커버리지 96.0%(조인 전 83.1%)</div>
  </div>

  <h2>정비계획 입안대상지역 요건 (조례 제6조, 주택정비형 재개발)</h2>
  <table class="req">
    <tr><td>노후도(동수) ≥ 60% <b>[필수]</b></td><td><b style="color:var(--good-fg)">78.1~81.3% 충족</b></td></tr>
    <tr><td>구역 면적 ≥ 1만㎡ <b>[필수]</b></td><td><b style="color:var(--good-fg)">21.7만㎡ 충족</b></td></tr>
    <tr><td>과소필지(&lt;90㎡) ≥ 40% [선택]</td><td>22.0% 미충족</td></tr>
    <tr><td>호수밀도 ≥ 60동/ha [선택]</td><td>48.7* 특례 미반영(참고)</td></tr>
    <tr><td>주택접도율 ≤ 40% [선택]</td><td title="도로 폭 6m 반영 하한 ~ 폭 미반영 상한">39.6~80.1% 미확정(근사)</td></tr>
  </table>

  <h2>표시 모드</h2>
  <div class="mode">
    <button id="mode-verdict" class="on">노후 판정</button>
    <button id="mode-decade">준공 연대</button>
  </div>
  <div class="legend" id="legend"></div>

  <h2>레이어</h2>
  <div class="toggles">
    <label><input type="checkbox" id="ly-small"> 과소필지(&lt;90㎡, 231필지) 표시</label>
    <label><input type="checkbox" id="ly-zone" checked> 정비구역 경계</label>
  </div>

  <div class="note">
    본 판정은 브이월드 개방 데이터 기반 <b>근사 자동 판정</b>이며, 법적 효력이 없고
    정밀 판정에는 실태조사가 필요합니다. 건축물대장 표제부(공공데이터포털 건축HUB) 조인으로 미연계 178동 중 136동을 보완했고, 표제부가 없는 42동은 조례 제4조③
    (재산세 부과연도 기준) 보완 판정 대상(특정무허가건축물 후보)입니다.<br><br>
    <span class="src">데이터: 브이월드 건축물정보·연속지적도(WFS)/배경지도, 서울 열린데이터광장 의제처리구역, 국가법령정보센터 서울시 도시정비조례, 공공데이터포털 건축물대장 표제부</span>
  </div>
</aside>
<div id="map"></div>
</div>
<script>
const ZONE = __ZONE__;
const BLDS = __BLDS__;
const PCLS = __PCLS__;
const KEY = new URLSearchParams(location.search).get("vworld") || "";  // 브이월드 WMTS는 도메인 등록 키 필요 — 없으면 OpenStreetMap

const C = { old: "#C4320A", ok: "#175CD3", na: "#98A2B3", small: "#6941C6" };
const DECADES = [
  { max: 1979, c: "#7C2D12", label: "~1979년" },
  { max: 1989, c: "#C2410C", label: "1980년대" },
  { max: 1999, c: "#F97316", label: "1990년대" },
  { max: 2009, c: "#FDB37B", label: "2000년대" },
  { max: 9999, c: "#FFEAD5", label: "2010년~" },
];

const map = L.map("map", { zoomControl: true, zoomAnimation: false, fadeAnimation: false, markerZoomAnimation: false })
  .setView([37.66439, 127.07153], 16);
const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" });
const base = KEY ? L.tileLayer(`https://api.vworld.kr/req/wmts/1.0.0/${KEY}/white/{z}/{y}/{x}.png`, { maxZoom: 19, attribution: "© 브이월드" }) : osm;
const baseNormal = KEY ? L.tileLayer(`https://api.vworld.kr/req/wmts/1.0.0/${KEY}/Base/{z}/{y}/{x}.png`, { maxZoom: 19, attribution: "© 브이월드" }) : osm;
const baseSat = KEY ? L.tileLayer(`https://api.vworld.kr/req/wmts/1.0.0/${KEY}/Satellite/{z}/{y}/{x}.jpeg`, { maxZoom: 19, attribution: "© 브이월드" }) : osm;
base.addTo(map);
L.control.layers({ "백지도": base, "일반지도": baseNormal, "위성영상": baseSat }, null, { position: "topright" }).addTo(map);

let mode = "verdict";

function decadeColor(yr) {
  for (const d of DECADES) if (yr <= d.max) return d.c;
  return C.na;
}
function styleFor(f) {
  const p = f.properties;
  if (mode === "verdict") {
    const col = p.old === true ? C.old : p.old === false ? C.ok : C.na;
    return { color: "#ffffff", weight: 0.7, dashArray: p.old == null ? "3 2" : null, fillColor: col, fillOpacity: 0.78 };
  }
  const col = p.yr ? decadeColor(p.yr) : C.na;
  return { color: "#ffffff", weight: 0.7, dashArray: p.yr ? null : "3 2", fillColor: col, fillOpacity: 0.82 };
}
function ttHtml(p) {
  const v = p.old === true ? '<span class="tt-verdict old">노후·불량건축물</span>'
          : p.old === false ? '<span class="tt-verdict ok">양호</span>'
          : '<span class="tt-verdict na">대장 미연계(사용승인일 없음)</span>';
  return `<div class="tt-title">${p.nm || "(무명)"}&nbsp;</div>` +
    `준공 ${p.yr ?? "미상"}${p.age != null ? ` · 경과 ${p.age}년` : ""} · 지상 ${p.flr ?? "?"}층<br>` +
    v + `<br><span style="color:#878d96">근거: 서울 도시정비조례 제4조·별표1</span>`;
}
const bldLayer = L.geoJSON(BLDS, {
  style: styleFor,
  onEachFeature: (f, ly) => ly.bindTooltip(() => ttHtml(f.properties), { className: "bld", sticky: true }),
}).addTo(map);

const smallLayer = L.geoJSON(PCLS, {
  filter: f => f.properties.small,
  style: { color: C.small, weight: 1.4, fillColor: C.small, fillOpacity: 0.25 },
  onEachFeature: (f, ly) => ly.bindTooltip(`과소필지 · ${f.properties.jibun} · ${f.properties.area}㎡`, { className: "bld", sticky: true }),
});

const zoneLayer = L.geoJSON(ZONE, { style: { color: "#1a1d21", weight: 2.6, dashArray: "8 5", fill: false } }).addTo(map);
function fit() {
  map.invalidateSize();
  const z = map.getBoundsZoom(zoneLayer.getBounds());
  if (z >= 10 && z <= 18) map.fitBounds(zoneLayer.getBounds(), { padding: [16, 16] });
  else map.setView([37.66439, 127.07153], 16);
}
window.addEventListener("load", () => { fit(); setTimeout(fit, 400); setTimeout(fit, 1500); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) fit(); });

function renderLegend() {
  const el = document.getElementById("legend");
  if (mode === "verdict") {
    el.innerHTML = [
      `<div class="row"><span class="sw" style="background:${C.old}"></span>노후·불량 (824동)</div>`,
      `<div class="row"><span class="sw" style="background:${C.ok}"></span>양호 (189동)</div>`,
      `<div class="row"><span class="sw" style="background:${C.na};border:1.5px dashed #667085"></span>대장 없음·승인일 미상 (42동)</div>`,
    ].join("");
  } else {
    el.innerHTML = DECADES.map(d => `<div class="row"><span class="sw" style="background:${d.c};border:1px solid #e4e6e9"></span>${d.label}</div>`).join("") +
      `<div class="row"><span class="sw" style="background:${C.na};border:1.5px dashed #667085"></span>준공연도 미상</div>`;
  }
}
renderLegend();

document.getElementById("mode-verdict").onclick = e => { mode = "verdict"; swap(e.target); };
document.getElementById("mode-decade").onclick = e => { mode = "decade"; swap(e.target); };
function swap(btn) {
  document.querySelectorAll(".mode button").forEach(b => b.classList.remove("on"));
  btn.classList.add("on");
  bldLayer.setStyle(styleFor);
  renderLegend();
}
document.getElementById("ly-small").onchange = e => e.target.checked ? smallLayer.addTo(map) : map.removeLayer(smallLayer);
document.getElementById("ly-zone").onchange = e => e.target.checked ? zoneLayer.addTo(map) : map.removeLayer(zoneLayer);

// 캡처·공유용 URL 파라미터: ?mode=decade&small=1
const qp = new URLSearchParams(location.search);
if (qp.get("mode") === "decade") document.getElementById("mode-decade").click();
if (qp.get("small") === "1") { document.getElementById("ly-small").checked = true; smallLayer.addTo(map); }
</script>
</body>
</html>
"""

html = html.replace("__ZONE__", zone).replace("__BLDS__", blds).replace("__PCLS__", pcls)
out = os.path.join(D, "demo_local.html")
open(out, "w", encoding="utf-8").write(html)
print("saved:", out, len(html) // 1024, "KB")
