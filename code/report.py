# -*- coding: utf-8 -*-
"""우리동네 정비진단 — 진단서 자동 생성기 (PoC v0.1)

judge_zone() 결과를 받아 A4 진단서 HTML을 만들고 headless Chrome으로 PDF 렌더.
사용: python report.py  (상계5동 배치 결과 JSON을 읽어 진단서 생성)
"""
import json
import os
import subprocess
import sys
from datetime import date

CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"


def build_html(z, out_html):
    old_pct = z["노후도_pct"]
    old_lo = z.get("노후도_pct_보수", old_pct)
    verdict = z.get("노후도_판정", "충족" if z["노후도_충족"] else "미충족")
    old_status = True if verdict == "충족" else (False if verdict == "미충족" else None)
    old_label = {"충족": "충족", "미충족": "미충족", "조건부충족": "조건부 충족", "보류": "판정 보류"}[verdict]
    ra = None
    try:
        _rp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "road_access_result.json")
        for r in json.load(open(_rp, encoding="utf-8")):
            if z["구역명"].split("(")[0].strip().startswith(r["구역"].split(" ")[0]):
                ra = r
    except Exception:
        ra = None
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    def _find(fname):
        try:
            for r in json.load(open(os.path.join(_root, "data", fname), encoding="utf-8")):
                if z["구역명"].split("(")[0].strip().startswith(r["구역"].split(" ")[0]):
                    return r
        except Exception:
            return None
    rw = _find("road_width_result.json"); dn = _find("density_result.json"); tm = _find("timing_result.json")
    if rw:
        road_txt = f"{rw['접도율_6m']}~{rw['접도율_폭미반영']}%*(폭 6m 반영 하한~폭 미반영 상한)"
        road_st = True if rw["접도율_폭미반영"] <= 40 else (None if rw["접도율_6m"] <= 40 else False)
    else:
        road_txt, road_st = (f"≈{ra['접도율_근사']}%*(근사)" if ra else "미산정"), None
    if dn:
        dens_txt = f"{dn['호수밀도_특례근사']}동/ha(특례 근사, 단순 {dn['호수밀도_단순']})"; dens_st = dn["호수밀도_특례근사"] >= 60
    else:
        dens_txt, dens_st = f"{z['호수밀도_단순']}동/ha*(단순 참고)", None
    rows = [
        ("노후건축물(연한 기준) 비율(동수) ≥ 60%", "필수", f"{old_lo}~{old_pct}%",
         old_status, "조례 제6조①2, 제4조·별표1"),
        ("구역 면적 ≥ 1만㎡", "필수", f"{z['면적_m2']/10000:,.1f}만㎡".replace(".0만", "만"),
         z["면적_충족"], "조례 제6조①2"),
        ("과소필지(90㎡ 미만) ≥ 40%", "선택", f"{z['과소필지_pct']}%",
         z["과소필지_충족"], "조례 제6조①2가, 제2조9"),
        ("호수밀도 ≥ 60동/ha", "선택", dens_txt, dens_st, "조례 제6조①2다, 제2조5"),
        ("주택접도율 ≤ 40% (도로 폭 6m)", "선택", road_txt, road_st, "조례 제6조①2나, 제2조10"),
    ]
    must_ok = verdict == "충족" and z["면적_충족"]
    cond_ok = verdict == "조건부충족" and z["면적_충족"]
    tr = "\n".join(
        f"<tr><td>{n}<span class='tag {'must' if k=='필수' else 'opt'}'>{k}</span></td>"
        f"<td class='v'>{v}</td>"
        f"<td class='{'ok' if s else ('no' if s is False else 'na')}'>"
        f"{(old_label if n.startswith('노후') else ('충족' if s else ('미충족' if s is False else '참고')))}</td>"
        f"<td class='law'>{law}</td></tr>"
        for n, k, v, s, law in rows)

    ttr = ""
    try:
        import types as _t  # noqa  (동명 표준모듈 회피용 — 아래에서 경로 지정 import)
        _tm = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "type_matrix.json"), encoding="utf-8"))
        _row = next((r for r in _tm if r["구역"] == z["구역명"].split("(")[0].strip()), None)
        if _row:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import importlib.util as _iu
            _spec = _iu.spec_from_file_location("jtypes", os.path.join(os.path.dirname(os.path.abspath(__file__)), "types.py")); _jt = _iu.module_from_spec(_spec); _spec.loader.exec_module(_jt)
            _cls = {"충족": "ok", "미충족": "no"}
            ttr = chr(10).join(f"<tr><td>{k}</td><td class='{_cls.get(v[0], 'na')}'>{v[0]}</td><td style='font-size:10.5px'>{v[1]}</td><td class='law'>{_jt.TYPE_RULES[k]['law']}</td></tr>"
                             for k, v in _row["판정"].items())
    except Exception as _e:
        ttr = f"<tr><td colspan='4' class='na'>유형별 판정 자료 없음 ({_e})</td></tr>"
    if tm:
        c26, c36 = tm["노후도_2026"], tm["노후도_2036"]
        timing_tr = (f"<tr><td>보수값(미연계 비노후 가정)</td><td class='v'>{c26[0]}%</td><td class='v'>{c36[0]}%</td><td class='{'ok' if tm['도달연도_보수값'] else 'na'}'>{tm['도달연도_보수값'] or '2050년 이후'}</td></tr>"
                     f"<tr><td>연계값(대장 연계 건물 기준)</td><td class='v'>{c26[1]}%</td><td class='v'>{c36[1]}%</td><td class='{'ok' if tm['도달연도_연계값'] else 'na'}'>{tm['도달연도_연계값'] or '2050년 이후'}</td></tr>")
    else:
        timing_tr = "<tr><td colspan='4' class='na'>시점 예측 자료 없음</td></tr>"
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 0; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Malgun Gothic',sans-serif; color:#1a1d21; width:210mm; padding:16mm 18mm; }}
  .kicker {{ font-size:11px; letter-spacing:.14em; color:#C4320A; font-weight:700; }}
  h1 {{ font-size:23px; margin:4px 0 2px; }}
  .meta {{ font-size:11px; color:#52575e; border-bottom:2px solid #1a1d21; padding-bottom:10px; }}
  .verdict {{ margin:16px 0; padding:14px 18px; border:2px solid {'#067647' if must_ok else ('#B54708' if (cond_ok or verdict == '보류') else '#C4320A')};
             border-radius:10px; background:{'#f0faf4' if must_ok else ('#fffaeb' if (cond_ok or verdict == '보류') else '#fef3f2')}; }}
  .verdict b {{ font-size:17px; color:{'#067647' if must_ok else ('#B54708' if (cond_ok or verdict == '보류') else '#C4320A')}; }}
  .verdict p {{ font-size:12px; color:#52575e; margin-top:4px; }}
  h2 {{ font-size:13px; margin:16px 0 6px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  th {{ text-align:left; font-size:11px; color:#52575e; border-bottom:1.5px solid #1a1d21; padding:5px 6px; }}
  td {{ padding:7px 6px; border-bottom:1px solid #e4e6e9; }}
  td.v {{ font-weight:700; text-align:right; white-space:nowrap; }}
  td.ok {{ color:#067647; font-weight:700; }} td.no {{ color:#C4320A; font-weight:700; }}
  td.na {{ color:#878d96; }} td.law {{ font-size:10.5px; color:#878d96; }}
  .tag {{ font-size:9.5px; padding:1px 6px; border-radius:99px; margin-left:6px; vertical-align:1px; }}
  .tag.must {{ background:#fee4e2; color:#C4320A; }} .tag.opt {{ background:#eef2f6; color:#52575e; }}
  .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-top:6px; }}
  .cell {{ border:1px solid #e4e6e9; border-radius:8px; padding:9px 11px; }}
  .cell .k {{ font-size:10.5px; color:#52575e; }} .cell .n {{ font-size:17px; font-weight:800; }}
  .foot {{ margin-top:18px; font-size:10px; color:#878d96; line-height:1.6;
          border-top:1px solid #e4e6e9; padding-top:9px; }}
</style></head><body>
  <div class="kicker">정비구역 지정요건 자동 진단서</div>
  <div style="display:inline-block;font-size:9.5px;color:#B54708;border:1px solid #B54708;border-radius:4px;padding:2px 6px;margin:4px 0 2px">판정 범위: 노후도·면적·과소필지·접도율(근사) / 참고: 호수밀도 / 미반영: 불량건축물(§2③가~다목)·재건축진단·주민동의·기본계획</div>
  <h1>{z['구역명']}</h1>
  <div class="meta">진단 기준일 {date.today().isoformat()} · 기준연도 {z.get('기준연도', 2026)} · <b>경계 출처: {z.get('경계출처', '이용자 지정(공식 경계 아님)')}</b> ·
    근거: 도시 및 주거환경정비법 제16조, 동법 시행령 별표1, 서울특별시 도시 및 주거환경정비 조례(시행 2026-05-18) 제2조·제4조·제6조·별표1</div>
  <div class="verdict">
    <b>{'주택정비형 재개발 필수요건 충족 (선택요건 1개 이상 별도 확인 필요)' if must_ok else ('필수요건 조건부 충족 — 대장 미연계 건물 보완 판정 필요' if cond_ok else ('판정 보류 — 대장 미연계 건물 과다' if verdict == '보류' else '필수요건 미충족'))}</b>
    <p>노후도 {old_lo}~{old_pct}%(기준 60%, 보수값(미연계 건물 비노후 가정)~연계값(대장 연계 건물 기준)) · 면적 {z['면적_m2']:,.0f}㎡(기준 1만㎡) · 판정 커버리지 {z.get('판정커버리지', '-')}%.
    선택요건은 {'과소필지 충족.' if z['과소필지_충족'] else '추가 확인 필요(접도율은 도로 폭 미반영 근사, 호수밀도는 특례 미산정).'} 요건 충족은 정비구역 지정의 필요조건이며 지정을 보장하지 않습니다.</p>
  </div>
  <h2>요건별 판정</h2>
  <table>
    <tr><th>요건</th><th style="text-align:right">진단값</th><th>판정</th><th>근거 조문</th></tr>
    {tr}
  </table>
  <h2>충족 예상 시점 — 지자체 모드 (건물별 사용승인일 분포에 별표1 연한을 적용해 60% 도달 연도 산출)</h2>
  <table>
    <tr><th>기준</th><th style="text-align:right">2026년 노후도</th><th style="text-align:right">2036년 노후도</th><th>60% 도달 연도</th></tr>
    {timing_tr}
  </table>
  <h2>사업유형별 가능성 (유형별 기준표 적용, 세대수·역 거리·재건축진단 등 미보유 항목은 보류)</h2>
  <table>
    <tr><th>사업유형</th><th>판정</th><th>사유</th><th>근거</th></tr>
    {ttr}
  </table>
  <h2>기초 현황</h2>
  <div class="grid">
    <div class="cell"><div class="k">구역 내 건축물</div><div class="n">{z['건물_총']:,}동</div></div>
    <div class="cell"><div class="k">노후·불량 판정</div><div class="n">{z['건물_노후']:,}동</div></div>
    <div class="cell"><div class="k">대장 미연계(승인일 無)</div><div class="n">{z['건물_총']-z['건물_판정가능']:,}동</div></div>
    <div class="cell"><div class="k">과소필지</div><div class="n">{z['필지_과소']:,}필지</div></div>
  </div>
  <div class="foot">
    * 주택접도율은 연속지적도 도로 지목 필지와 4m 이상 접한 대지의 건물 비율입니다. 하한은 도로 폴리곤을 3m 침식해 접한 지점의 폭이 6m 이상인 경우만 센 값(현황도로·사도 미반영), 상한은 폭 미반영 값입니다. 상한이 40% 이하일 때만 충족으로 확정합니다.<br>
    * 호수밀도는 조례 제2조5호의 산정 특례(공동주택 최다세대층 기준, 존치 공원·학교 제외 등)를 반영하지 않은 단순 동수/ha 참고치입니다.<br>
    본 진단서는 <b>판정 범위 고지 없이 인용·배포할 수 없으며</b>, 이용자 지정 경계에 대한 판정은 해당 경계가 정비구역으로 지정된다는 의미가 아닙니다. 브이월드·국가법령정보센터 개방 데이터 기반의 근사 자동 판정으로 법적 효력이 없으며,
    정비계획 입안을 위한 정밀 판정에는 「도시 및 주거환경정비법」에 따른 실태조사가 필요합니다.
    대장 미연계 건축물(사용승인일 없음)은 건축물대장 표제부 조회 및 조례 제4조③(재산세 등 부과 개시 연도 기준)에 따른 보완 판정 대상이며, 본 진단서의 노후도는 이를 제외한 상한값과 비노후로 본 하한값의 범위로 표기합니다.<br>
    데이터: 브이월드 건축물정보·연속지적도(WFS), 서울 열린데이터광장 의제처리구역 위치정보, 국가법령정보센터.
  </div>
</body></html>"""
    open(out_html, "w", encoding="utf-8").write(html)


def to_pdf(html_path, pdf_path):
    from urllib.request import pathname2url
    url = "file:" + pathname2url(os.path.abspath(html_path))  # '#' 등 특수문자 인코딩
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}", url],
                   check=True, capture_output=True)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if src:
        zones = json.load(open(src, encoding="utf-8"))
    else:
        raise SystemExit("사용법: python report.py <batch_results.json>")
    outdir = os.path.join(os.path.dirname(here), "진단서")
    os.makedirs(outdir, exist_ok=True)
    for z in zones:
        stem = z["구역명"].split("(")[0].replace(" ", "_")
        h = os.path.join(outdir, f"진단서_{stem}.html")
        p = os.path.join(outdir, f"진단서_{stem}.pdf")
        build_html(z, h)
        to_pdf(h, p)
        print("생성:", p)
