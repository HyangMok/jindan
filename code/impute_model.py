# -*- coding: utf-8 -*-
"""대장 미연계 건물의 노후 여부를 추정하는 공간 학습 모델 (GeoAI 프로토타입)

학습: 캐시된 구역의 '대장 연계' 건물(사용승인일 있음) → 특징 = 건물 형태(면적·층수·구조·용도) + 공간 근접성(반경 60m 이웃의
      준공연대 중앙값·노후 비율·이웃 수). 라벨 = 조례 기준 노후 여부(기준연도 = 구역 고시년).
평가: 구역별 홀드아웃(leave-one-zone-out) — 다른 구역으로 학습해 해당 구역을 예측 → 일반화 성능.
적용: 미연계 건물에 노후 확률을 부여 → 노후도의 '추정 구간'(상·하한 사이)을 산출, 원래 상·하한과 폭 비교.
출력: data/impute_result.json, 콘솔 요약. 결과는 '추정'이며 확정은 건축물대장 조인으로.
"""
import glob
import json
import math
import os
import sys

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.neighbors import BallTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jindan  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
R_M = 60.0  # 이웃 반경(m)


def load_zone(fn):
    z = json.load(open(fn, encoding="utf-8"))
    rings = z["rings"]
    inb = [f["properties"] | {"_xy": jindan.centroid(f["geometry"])} for f in z["blds"]
           if jindan.point_in_rings(*jindan.centroid(f["geometry"]), rings)]
    allb = [f["properties"] | {"_xy": jindan.centroid(f["geometry"])} for f in z["blds"]]  # 이웃 계산엔 경계 밖도 사용
    return z["name"], z["year"], inb, allb


def features(targets, pool, year):
    """targets: 특징을 만들 건물들, pool: 이웃 후보(연계 건물만), year: 기준연도"""
    lat0 = math.radians(np.mean([b["_xy"][1] for b in pool]))
    def to_m(b): return (b["_xy"][0] * 111320 * math.cos(lat0), b["_xy"][1] * 110540)
    P = np.array([to_m(b) for b in pool]); tree = BallTree(P)
    pyear = np.array([int(b["useapr_day"][:4]) for b in pool])
    pold = np.array([1.0 if jindan.judge_building(b, year) else 0.0 for b in pool])
    X = []
    for b in targets:
        x, y = to_m(b)
        idx = tree.query_radius(np.array([[x, y]]), r=R_M)[0]
        idx = idx[(P[idx, 0] != x) | (P[idx, 1] != y)]  # 자기 자신 제외
        n = len(idx)
        nb_year = float(np.median(pyear[idx])) if n else 1995.0
        nb_old = float(pold[idx].mean()) if n else 0.5
        code = str(b.get("strct_cd") or "")
        X.append([
            float(b.get("archarea") or 0), float(b.get("totalarea") or 0), float(b.get("grnd_flr") or 0), float(b.get("ugrnd_flr") or 0),
            1.0 if code in jindan.RC_CODES else 0.0, 1.0 if code in jindan.STEEL_CODES else 0.0, 1.0 if code in ("11", "12", "19") else 0.0,
            1.0 if str(b.get("usability") or "").startswith("02") else 0.0, 1.0 if str(b.get("usability") or "").startswith("01") else 0.0,
            n, nb_year, nb_old,
        ])
    return np.array(X)


zones = [load_zone(fn) for fn in sorted(glob.glob(os.path.join(CACHE, "*.json")))]
print("구역", len(zones))

# ── 구역 단위 홀드아웃 평가 ──
accs, aucs, rows = [], [], []
for i, (name, year, inb, allb) in enumerate(zones):
    test_lab = [b for b in inb if (b.get("useapr_day") or "")[:4].isdigit()]
    if len(test_lab) < 50: continue
    tr_X, tr_y = [], []
    for j, (n2, y2, inb2, allb2) in enumerate(zones):
        if j == i: continue
        pool2 = [b for b in allb2 if (b.get("useapr_day") or "")[:4].isdigit()]
        lab2 = [b for b in inb2 if (b.get("useapr_day") or "")[:4].isdigit()]
        if len(lab2) < 30: continue
        tr_X.append(features(lab2, pool2, y2)); tr_y += [1 if jindan.judge_building(b, y2) else 0 for b in lab2]
    Xtr = np.vstack(tr_X); ytr = np.array(tr_y)
    pool = [b for b in allb if (b.get("useapr_day") or "")[:4].isdigit()]
    Xte = features(test_lab, pool, year); yte = np.array([1 if jindan.judge_building(b, year) else 0 for b in test_lab])
    clf = GradientBoostingClassifier(n_estimators=200, max_depth=3, learning_rate=0.05, random_state=0).fit(Xtr, ytr)
    p = clf.predict_proba(Xte)[:, 1]; acc = accuracy_score(yte, p >= 0.5)
    auc = roc_auc_score(yte, p) if len(set(yte)) > 1 else float("nan")
    accs.append(acc); aucs.append(auc)
    # 적용: 미연계 건물 추정 → 노후도 추정치와 폭
    unl = [b for b in inb if not (b.get("useapr_day") or "")[:4].isdigit()]
    n_all, n_known = len(inb), len(test_lab); n_old_known = int(yte.sum())
    hi = n_old_known / n_known * 100; lo = n_old_known / n_all * 100
    if unl:
        pu = clf.predict_proba(features(unl, pool, year))[:, 1]
        est = (n_old_known + pu.sum()) / n_all * 100
        # 추정 구간: 확률 0.5 기준 ± 불확실(확률이 0.35~0.65인 건물 수)
        unsure = int(((pu > 0.35) & (pu < 0.65)).sum())
        est_lo = (n_old_known + (pu >= 0.65).sum()) / n_all * 100; est_hi = (n_old_known + (pu > 0.35).sum()) / n_all * 100
    else:
        est = est_lo = est_hi = hi; unsure = 0
    rows.append(dict(구역=name, 기준연도=year, 건물=n_all, 연계=n_known, 미연계=len(unl), 홀드아웃_정확도=round(acc * 100, 1),
                     AUC=round(auc, 3) if auc == auc else None, 원래_하한=round(lo, 1), 원래_상한=round(hi, 1),
                     추정치=round(est, 1), 추정_하한=round(est_lo, 1), 추정_상한=round(est_hi, 1), 불확실_건물=unsure))
    print(f"{name}: 정확도 {acc*100:.1f}% AUC {auc:.3f} | 원래 {lo:.1f}~{hi:.1f}% (폭 {hi-lo:.1f}p) → 추정 {est_lo:.1f}~{est_hi:.1f}% (폭 {est_hi-est_lo:.1f}p, 점추정 {est:.1f}%)")

print(f"\n구역 홀드아웃 평균: 정확도 {np.mean(accs)*100:.1f}%, AUC {np.nanmean(aucs):.3f}")
json.dump({"rows": rows, "mean_acc": float(np.mean(accs)), "mean_auc": float(np.nanmean(aucs)), "radius_m": R_M},
          open(os.path.join(ROOT, "data", "impute_result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
