"""
스크리너 데이터 만들기

1. SEC 종목 목록(거래소 포함)에서 나스닥, NYSE, 기타 거래소 종목을 고른다 (OTC 제외)
2. 야후에서 1년치 일봉을 받아 주가, 50일 평균 거래량을 계산한다
3. 주가 10달러 이상, 50일 평균 거래량 5만 주 이상만 남긴다 (화면에서 조건을 바꿀 수 있도록 넉넉하게)
4. 남은 종목의 SEC 실적을 정리한다 (분기·연간 EPS, 영업이익, ROE, 분할 보정)
5. site/screener/data.json 으로 저장한다. 실제 조건 판정은 화면(브라우저)에서 한다.

실행: SEC_USER_AGENT="이름 이메일" python screener/build_screener.py [companyfacts.zip 경로]
"""
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fundamentals import summarize  # noqa: E402

ROOT = Path(__file__).parent.parent
OUT = ROOT / "site" / "screener"
YAHOO_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
SEC_UA = {"User-Agent": os.environ.get("SEC_USER_AGENT", "")}
EXCHANGES = {"Nasdaq", "NYSE", "CBOE", "TXSE"}
MIN_PRICE, MIN_VOL = 10, 50_000      # 저장 대상 바닥값 (화면 기본 조건보다 넉넉하게)
CHART_DAYS = 260                     # 차트용으로 저장할 거래일 수 (약 1년)
# 보통주가 아닌 것 걸러내기
#  - 나스닥 5글자 코드의 마지막 글자: M/N/O/P 우선주, R 권리, U 유닛, W 워런트, Z 기타
NON_COMMON_5TH = set("MNOPRUWZ")
NON_COMMON_WORDS = ("preferred", "depositary share", "warrant", " units", " rights", "notes due", "debenture")


def is_common(ticker, exchange, long_name):
    if exchange == "Nasdaq" and len(ticker) == 5 and ticker[-1] in NON_COMMON_5TH:
        return False
    name = (long_name or "").lower()
    return not any(w in name for w in NON_COMMON_WORDS)


def http_json(url, headers, timeout=30, tries=4):
    err = None
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return json.load(r)
        except Exception as e:
            err = e
            time.sleep(2 * (a + 1))
    raise RuntimeError(f"{url}: {err}")


def yahoo_daily(sym):
    """1년치 일봉 + 10년치 분할 기록"""
    q = urllib.parse.quote(sym)
    r = http_json(f"https://query2.finance.yahoo.com/v8/finance/chart/{q}?range=1y&interval=1d", YAHOO_UA)["chart"]["result"][0]
    off = r["meta"].get("gmtoffset", 0)
    long_name = r["meta"].get("longName") or r["meta"].get("shortName")
    qt = r["indicators"]["quote"][0]
    bars = []
    for i, ts in enumerate(r.get("timestamp") or []):
        if qt["close"][i] is None or qt["open"][i] is None:
            continue
        day = dt.datetime.fromtimestamp(ts + off, dt.UTC).date().isoformat()
        bars.append([day, round(qt["open"][i], 4), round(qt["high"][i], 4), round(qt["low"][i], 4),
                     round(qt["close"][i], 4), qt["volume"][i] or 0])
    return bars, long_name


def yahoo_splits(sym):
    q = urllib.parse.quote(sym)
    r = http_json(f"https://query2.finance.yahoo.com/v8/finance/chart/{q}?range=10y&interval=3mo&events=split", YAHOO_UA)
    ev = (r["chart"]["result"][0].get("events") or {}).get("splits", {})
    return [(dt.datetime.fromtimestamp(e["date"], dt.UTC).date().isoformat(), e["numerator"] / e["denominator"])
            for e in ev.values() if e.get("denominator")]


def main():
    zip_path = sys.argv[1] if len(sys.argv) > 1 else None
    t0 = time.time()

    # 1. 종목 목록
    tk = http_json("https://www.sec.gov/files/company_tickers_exchange.json", SEC_UA)
    universe = [dict(zip(tk["fields"], r)) for r in tk["data"] if r[3] in EXCHANGES]
    for u in universe:
        u["ysym"] = u["ticker"].replace(".", "-")
    print(f"[1] 종목 목록 {len(universe)}개")

    # 2. 주가
    def price(u):
        try:
            return u, yahoo_daily(u["ysym"])
        except Exception:
            return u, None
    with ThreadPoolExecutor(8) as ex:
        priced = list(ex.map(price, universe))
    rows, failed, skipped = [], 0, 0
    for u, res in priced:
        if res is None:
            failed += 1
            continue
        bars, long_name = res
        if len(bars) < 50:
            continue
        if not is_common(u["ticker"], u["exchange"], long_name):
            skipped += 1
            continue
        last = bars[-1]
        vol50 = sum(b[5] for b in bars[-50:]) / 50
        if last[4] < MIN_PRICE or vol50 < MIN_VOL:
            continue
        rows.append({"t": u["ticker"], "ysym": u["ysym"], "name": u["name"], "ex": u["exchange"], "cik": u["cik"],
                     "price": round(last[4], 2), "vol50": round(vol50), "date": last[0],
                     "hi52": round(max(b[2] for b in bars), 2), "bars": bars[-CHART_DAYS:]})
    print(f"[2] 주가 수신 실패 {failed}개, 보통주 아님 {skipped}개, 바닥 조건 통과 {len(rows)}개 ({time.time() - t0:.0f}초)")

    # 3. 분할 기록
    def sp(r):
        try:
            return yahoo_splits(r["ysym"])
        except Exception:
            return []
    with ThreadPoolExecutor(8) as ex:
        for r, s in zip(rows, ex.map(sp, rows)):
            r["splits"] = s
    print(f"[3] 분할 기록 ({time.time() - t0:.0f}초)")

    # 4. SEC 실적
    if zip_path is None:
        zip_path = ROOT / "companyfacts.zip"
        req = urllib.request.Request("https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip", headers=SEC_UA)
        with urllib.request.urlopen(req, timeout=600) as r, open(zip_path, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    nofund = 0
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        for r in rows:
            name = f"CIK{r['cik']:010d}.json"
            if name not in names:
                r["f"] = None
                nofund += 1
                continue
            try:
                r["f"] = summarize(json.loads(z.read(name)), r["splits"])
            except Exception as e:
                r["f"] = None
                nofund += 1
    print(f"[4] 실적 정리 완료, 실적 없음 {nofund}개 ({time.time() - t0:.0f}초)")

    # 5. 저장 (차트 일봉은 종목별 파일로 따로)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "charts").mkdir(exist_ok=True)
    for r in rows:
        (OUT / "charts" / f"{r['ysym']}.json").write_text(json.dumps(r.pop("bars")), encoding="utf-8")
        r.pop("splits")
    data = {"generatedAt": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "priceDate": max(r["date"] for r in rows), "rows": rows}
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[5] 저장: {len(rows)}개 종목, data.json {(OUT / 'data.json').stat().st_size / 1e6:.1f}MB ({time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
