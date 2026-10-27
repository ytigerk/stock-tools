"""
SEC 실적 데이터(companyfacts) 정리 모듈

SEC 원본은 회사마다 항목 이름, 보고 방식(누적/분기), 회계연도, 정정, 주식 분할이 제각각이다.
이 모듈은 한 회사의 companyfacts JSON 을 받아 아래처럼 정리된 숫자로 바꾼다.

 - 분기 EPS (희석, 없으면 기본) : 4분기는 "연간 - 9개월 누적" 으로 계산
 - 분기 매출, 분기 영업이익 ("일회성 의심" 판단용)
 - 연간 EPS, 연간 영업이익
 - ROE : 최근 4분기(TTM) 순이익 / 평균 자기자본. 분기 자료가 없는 외국 기업은 최근 회계연도 기준
 - 주식 분할 보정 : 분할 이전에 제출된 숫자는 분할 비율로 나눠서 맞춘다
 - 외국 기업 : 미국 양식(10-K/10-Q) 대신 20-F/40-F 로 연간만 보고. 국제회계기준(IFRS) 항목도 읽는다
"""
import datetime as dt

FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A"}
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
# 미국 회계기준(us-gaap) 항목 이름, 뒤쪽은 국제회계기준(ifrs-full) 항목 이름
EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic",
            "DilutedEarningsLossPerShare", "BasicAndDilutedEarningsLossPerShare", "BasicEarningsLossPerShare"]
REV_TAGS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "Revenue"]
NI_TAGS = ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic",
           "ProfitLossAttributableToOwnersOfParent"]
OP_TAGS = ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"]
EQ_TAGS = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
           "EquityAttributableToOwnersOfParent", "Equity"]


def d(s):
    return dt.date.fromisoformat(s)


def _pick_unit(units, per_share):
    """항목의 단위 고르기. 주당 값은 '.../shares', 금액은 가장 많이 쓰인 통화(USD, CAD, EUR 등)"""
    cands = [(len(v), u) for u, v in units.items() if u.endswith("/shares") == per_share and (per_share or "/" not in u)]
    if not cands:
        return None
    usd = "USD/shares" if per_share else "USD"
    return usd if usd in units else max(cands)[1]


def _facts(facts, tags, per_share):
    """여러 태그의 값을 기간별로 모은다. 같은 기간은 가장 최근에 제출된 값을 쓴다.
    태그 우선순위가 높은 쪽(앞쪽)을 먼저 채우고, 빈 기간만 뒤쪽 태그로 채운다."""
    out, unit_used = {}, None
    for tag in tags:
        units = facts.get(tag, {}).get("units", {})
        unit = _pick_unit(units, per_share)
        if not unit or (unit_used and unit != unit_used):
            continue  # 통화가 다른 항목은 섞지 않는다
        best = {}
        for f in units[unit]:
            if f.get("form") not in FORMS:
                continue
            key = (f.get("start"), f["end"])
            if key not in best or f["filed"] > best[key]["filed"]:
                best[key] = f
        if best:
            unit_used = unit_used or unit
        for key, f in best.items():
            out.setdefault(key, f)
    return out


def _split_factor(filed, splits):
    """filed 날짜 이후에 일어난 분할 비율의 곱. (예: 10:1 분할 이전 제출 값은 10으로 나눠야 함)"""
    k = 1.0
    for day, ratio in splits:
        if day > filed:
            k *= ratio
    return k


def _days(f):
    return (d(f["end"]) - d(f["start"])).days


def quarterly(facts_all, tags, splits, per_share):
    """분기 값 사전 {분기말 날짜: {'v': 값, 'start': 시작일, 'derived': 계산으로 만든 값인지}}"""
    facts = _facts(facts_all, tags, per_share)
    adj = lambda f: f["val"] / (_split_factor(f["filed"], splits) if per_share else 1.0)
    dur = {}
    for (start, end), f in facts.items():
        if not start:
            continue
        n = _days(f)
        kind = "Q" if 80 <= n <= 100 else "H" if 170 <= n <= 190 else "9M" if 260 <= n <= 285 else "FY" if 350 <= n <= 380 else None
        if kind:
            dur.setdefault(kind, []).append((start, end, adj(f), f["form"]))
    q = {end: {"v": v, "start": start, "derived": False} for start, end, v, _ in dur.get("Q", [])}
    if not q:
        return {}  # 분기 보고가 없는 회사(외국 기업 등)는 연간 자료로 분기를 만들지 않는다

    # 누적값에서 빠진 분기 만들기: 6개월-1분기, 9개월-6개월, 연간-9개월
    for longer, shorter in (("H", None), ("9M", "H"), ("FY", "9M")):
        for start, end, v, _ in dur.get(longer, []):
            if end in q:
                continue
            prev_total = prev_end = None
            if shorter is None:  # 6개월 누적 - 1분기
                first = [(e, x["v"]) for e, x in q.items() if x["start"] == start and e < end]
                if first:
                    prev_end, prev_total = max(first)
            else:
                cands = [(e2, v2) for s2, e2, v2, _ in dur.get(shorter, []) if s2 == start and e2 < end]
                if cands:
                    prev_end, prev_total = max(cands)
            if prev_total is None and longer == "FY":
                # 9개월 누적이 없으면 1~3분기 합으로
                inside = sorted((e, x["v"]) for e, x in q.items() if x["start"] >= start and e < end)
                if len(inside) == 3:
                    prev_total, prev_end = sum(v2 for _, v2 in inside), inside[-1][0]
            if prev_total is not None:
                q[end] = {"v": v - prev_total, "start": (d(prev_end) + dt.timedelta(days=1)).isoformat(), "derived": True}
    return dict(sorted(q.items()))


def annual(facts_all, tags, splits, per_share):
    facts = _facts(facts_all, tags, per_share)
    out = {}
    for (start, end), f in facts.items():
        if start and 350 <= _days(f) <= 380 and f["form"].startswith(ANNUAL_FORMS):
            out[end] = f["val"] / (_split_factor(f["filed"], splits) if per_share else 1.0)
    return dict(sorted(out.items()))


def instant(facts_all, tags):
    facts = _facts(facts_all, tags, False)
    return dict(sorted((end, f["val"]) for (start, end), f in facts.items() if not start))


def _match(series, end, back_days, tol=25):
    """end 에서 back_days 전후(±tol일)에 끝나는 기간 찾기"""
    target = d(end) - dt.timedelta(days=back_days)
    best = None
    for e in series:
        gap = abs((d(e) - target).days)
        if gap <= tol and (best is None or gap < best[0]):
            best = (gap, e)
    return best[1] if best else None


def growth(cur, prev):
    """증가율(%)과 상태. 상태: 'ok' / 'turnaround'(흑자 전환) / 'loss'(현재 적자) / None(비교 불가)"""
    if cur is None or prev is None:
        return None, None
    if cur <= 0:
        return None, "loss"
    if prev <= 0:
        return None, "turnaround"
    return round((cur / prev - 1) * 100, 1), "ok"


def _cagr3(cur, base):
    if base is None:
        return None, None
    if cur <= 0:
        return None, "loss"
    if base <= 0:
        return None, "turnaround"
    return round(((cur / base) ** (1 / 3) - 1) * 100, 1), "ok"


def _main_taxonomy(tax):
    """미국 회계기준과 국제회계기준 중 최근 자료가 있는 쪽을 쓴다 (회계기준을 바꾼 회사의 옛 자료가 섞이지 않게)"""
    best, best_end = {}, ""
    for name in ("us-gaap", "ifrs-full"):
        tags = tax.get(name, {})
        last = max((f["end"] for tag in EPS_TAGS + NI_TAGS for items in tags.get(tag, {}).get("units", {}).values()
                    for f in items if f.get("form") in FORMS), default="")
        if last > best_end:
            best, best_end = tags, last
    return best


def summarize(companyfacts, splits=()):
    """한 회사의 정리된 실적 요약"""
    tax = companyfacts.get("facts", {})
    facts = _main_taxonomy(tax)
    splits = sorted(splits)
    eps_q = quarterly(facts, EPS_TAGS, splits, True)
    rev_q = quarterly(facts, REV_TAGS, splits, False)
    op_q = quarterly(facts, OP_TAGS, splits, False)
    ni_q = quarterly(facts, NI_TAGS, splits, False)
    eps_y = annual(facts, EPS_TAGS, splits, True)
    op_y = annual(facts, OP_TAGS, splits, False)
    ni_y = annual(facts, NI_TAGS, splits, False)
    eq = instant(facts, EQ_TAGS)

    # 회사의 가장 오래된 재무 기록 (상장 3년 미만 판단용). EPS 항목만 보면 항목 이름을 바꾼 회사가 신생으로 보이므로 전체 항목에서 찾는다
    all_ends = [f["end"] for tag in facts.values() for items in tag.get("units", {}).values()
                for f in items if f.get("form") in FORMS]
    annual_facts = [f for (s, e), f in _facts(facts, EPS_TAGS + NI_TAGS, True).items() if s and _days(f) >= 350]
    annual_facts += [f for (s, e), f in _facts(facts, NI_TAGS, False).items() if s and _days(f) >= 350]
    last_annual = max(annual_facts, key=lambda f: f["end"], default=None)
    out = {"quarters": [], "foreign": bool(last_annual) and last_annual["form"].startswith(("20-F", "40-F")),
           "firstEnd": min(all_ends) if all_ends else None}

    for end in list(eps_q)[-8:]:
        prev = _match(eps_q, end, 364)
        g, st = growth(eps_q[end]["v"], eps_q[prev]["v"] if prev else None)
        rprev = _match(rev_q, end, 364) if end in rev_q else None
        rg, _ = growth(rev_q[end]["v"], rev_q[rprev]["v"]) if end in rev_q and rprev else (None, None)
        oprev = _match(op_q, end, 364) if end in op_q else None
        og, ost = growth(op_q[end]["v"], op_q[oprev]["v"]) if end in op_q and oprev else (None, None)
        out["quarters"].append({"end": end, "eps": round(eps_q[end]["v"], 4),
                                "epsPrev": round(eps_q[prev]["v"], 4) if prev else None,
                                "epsG": g, "epsSt": st, "derived": eps_q[end]["derived"],
                                "rev": rev_q[end]["v"] if end in rev_q else None,
                                "rev": round(rev_q[end]["v"]) if end in rev_q else None,
                                "revG": rg, "opG": og, "opSt": ost})

    if eps_y:
        last = list(eps_y)[-1]
        old = _match(eps_y, last, 3 * 365)
        cagr, st = _cagr3(eps_y[last], eps_y[old] if old else None)
        out["epsY"] = {"end": last, "eps": round(eps_y[last], 4), "eps3y": round(eps_y[old], 4) if old else None,
                       "cagr": cagr, "st": st}
        oold = _match(op_y, last, 3 * 365)
        if last in op_y and oold:
            c, s = _cagr3(op_y[last], op_y[oold])
            out["epsY"]["opCagr"] = c if s == "ok" else None

    # ROE: 최근 4분기 순이익 합 / (최근 분기말 자기자본과 1년 전 자기자본의 평균)
    ends = list(ni_q)[-4:]
    if len(ends) == 4 and (d(ends[-1]) - d(ends[0])).days <= 300:
        last = ends[-1]
        e_end = eq.get(_match(eq, last, 0, 10)) if _match(eq, last, 0, 10) else None
        e_beg = eq.get(_match(eq, last, 365)) if _match(eq, last, 365) else None
        avg = (e_end + e_beg) / 2 if e_end and e_beg else e_end
        ttm = sum(ni_q[e]["v"] for e in ends)
        out["roe"] = {"end": last, "basis": "TTM", "roe": round(ttm / avg * 100, 1) if avg and avg > 0 else None}
    elif ni_y:
        last = list(ni_y)[-1]
        e_end = eq.get(last)
        e_beg = eq.get(_match(eq, last, 365)) if _match(eq, last, 365) else None
        avg = (e_end + e_beg) / 2 if e_end and e_beg else e_end
        out["roe"] = {"end": last, "basis": "FY", "roe": round(ni_y[last] / avg * 100, 1) if avg and avg > 0 else None}
    return out
