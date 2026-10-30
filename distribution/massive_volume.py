"""
지수 거래량 = 구성 종목 거래량 합계 (Massive 전 종목 일봉 사용)

- NASDAQ: 나스닥 상장 보통주 전체 (보통주, ADR 보통주 등)
- NYSE:   NYSE 상장 보통주 전체
- S&P 500: 구성종목 약 500개

Massive 의 "그날 미국 전 종목 일봉" 을 하루에 요청 한 번으로 받는다.
- 병합·분할로 조정되기 전의 원래 거래량 (adjusted=false) 이라 과거 숫자가 나중에 바뀌지 않는다
- 그날 실제로 거래된 종목이 다 들어 있어서, 나중에 상장폐지된 종목도 그날 합계에 들어간다
- 일봉 거래량에는 프리마켓·애프터마켓 거래도 포함된다 (매일 같은 기준)

결과는 distribution/volume.csv 에 날짜별로 쌓는다. 이미 있는 날은 다시 받지 않는다 (최근 2거래일만 다시 확인).
종목의 상장 거래소·종류는 distribution/tickers.json 에 모아두고 계속 늘려간다 (상장폐지 종목도 지우지 않음).

실행: MASSIVE_API_KEY=... python distribution/massive_volume.py [시작일 YYYY-MM-DD]
"""
import csv
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent
VOLUME = HERE / "volume.csv"
TICKERS = HERE / "tickers.json"
SP500_LIST = HERE / "sp500_constituents.csv"
KEY = os.environ.get("MASSIVE_API_KEY", "")
API = "https://api.massive.com"
EXCHANGES = {"XNAS": "nasdaq", "XNYS": "nyse"}
COMMON = {"CS", "ADRC", "OS", "NYRS", "GDR"}   # 보통주와 그에 준하는 것 (우선주, ETF, 워런트 등 제외)
WAIT = 12.5                                     # 무료 플랜: 분당 5회
RECHECK = 2                                     # 최근 몇 거래일은 매번 다시 받아서 확인


def get(url):
    sep = "&" if "?" in url else "?"
    for attempt in range(6):
        try:
            with urllib.request.urlopen(f"{url}{sep}apiKey={KEY}", timeout=90) as r:
                data = json.load(r)
            time.sleep(WAIT)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429:            # 요청이 너무 잦음 → 잠시 쉬고 다시
                time.sleep(30)
                continue
            if e.code in (500, 502, 503, 504):
                time.sleep(15 * (attempt + 1))
                continue
            body = e.read().decode("utf-8", "replace")[:300]
            print(f"  Massive 응답 {e.code}: {body}", flush=True)
            raise
        except Exception:
            time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"Massive 요청 실패: {url.split('?')[0]}")


def update_tickers(include_inactive=False):
    """거래소별 종목 목록(종목코드 → [거래소, 종류])을 받아 tickers.json 에 합친다."""
    known = json.loads(TICKERS.read_text(encoding="utf-8")) if TICKERS.exists() else {}
    for ex in EXCHANGES:
        for active in (["true", "false"] if include_inactive else ["true"]):
            url = f"{API}/v3/reference/tickers?market=stocks&exchange={ex}&active={active}&limit=1000"
            while url:
                d = get(url)
                for t in d.get("results", []):
                    # 같은 종목코드가 여러 회사에 쓰였으면 현재 상장된 쪽을 우선
                    if active == "true" or t["ticker"] not in known:
                        known[t["ticker"]] = [ex, t.get("type")]
                url = d.get("next_url")
    TICKERS.write_text(json.dumps(known, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    return known


def sp500_members():
    with SP500_LIST.open(encoding="utf-8") as f:
        return {row["Symbol"] for row in csv.DictReader(f)}   # Massive 는 BRK.B 처럼 점을 씀


def day_volume(day, tickers, sp500):
    try:
        d = get(f"{API}/v2/aggs/grouped/locale/us/market/stocks/{day}?adjusted=false")
    except urllib.error.HTTPError as e:
        # 무료 플랜은 그날 자료를 뉴욕 시간 자정이 지나야 주는 것으로 보임 → 아직 못 받는 날은 건너뛰고 다음 실행에서 받는다
        if e.code in (401, 403):
            return {"date": day, "all_n": 0}
        raise
    res = d.get("results") or []
    out = {"date": day, "nasdaq": 0, "nyse": 0, "sp500": 0, "nasdaq_n": 0, "nyse_n": 0, "sp500_n": 0, "all_n": len(res)}
    for x in res:
        v = x.get("v") or 0
        info = tickers.get(x["T"])
        if info and info[1] in COMMON and info[0] in EXCHANGES:
            k = EXCHANGES[info[0]]
            out[k] += v
            out[k + "_n"] += 1
        if x["T"] in sp500:
            out["sp500"] += v
            out["sp500_n"] += 1
    for k in ("nasdaq", "nyse", "sp500"):
        out[k] = round(out[k])
    return out


def load():
    if not VOLUME.exists():
        return {}
    with VOLUME.open(encoding="utf-8") as f:
        return {r["date"]: r for r in csv.DictReader(f)}


def save(rows):
    cols = ["date", "nasdaq", "nyse", "sp500", "nasdaq_n", "nyse_n", "sp500_n", "all_n"]
    with VOLUME.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for d in sorted(rows):
            w.writerow({c: rows[d][c] for c in cols})


def trading_days(start):
    """야후 나스닥 지수 일봉에 있는 날짜 = 거래일"""
    url = "https://query2.finance.yahoo.com/v8/finance/chart/%5EIXIC?range=2y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    days = [dt.datetime.fromtimestamp(t + off, dt.UTC).date().isoformat() for t in res["timestamp"]]
    # 오늘(뉴욕)은 애프터마켓이 끝난 뒤(20:30 이후)에만 포함
    now = dt.datetime.now(ZoneInfo("America/New_York"))
    today = now.date().isoformat()
    return [d for d in days if d >= start and (d < today or (d == today and now.time() >= dt.time(20, 30)))]


def main():
    if not KEY:
        sys.exit("MASSIVE_API_KEY 가 없습니다")
    start = sys.argv[1] if len(sys.argv) > 1 else (dt.date.today() - dt.timedelta(days=370)).isoformat()
    rows = load()
    tickers = update_tickers(include_inactive=not TICKERS.exists())
    sp500 = sp500_members()
    days = trading_days(start)
    todo = [d for d in days if d not in rows] + [d for d in days[-RECHECK:] if d in rows]
    print(f"거래일 {len(days)}일 중 받을 날 {len(todo)}일 (종목 목록 {len(tickers)}개)")
    for i, d in enumerate(todo, 1):
        r = day_volume(d, tickers, sp500)
        if r["all_n"] == 0:
            print(f"  {d}: 아직 자료 없음")
            continue
        rows[d] = r
        save(rows)   # 중간에 끊겨도 받은 만큼은 남도록 매번 저장
        print(f"  [{i}/{len(todo)}] {d} NASDAQ {r['nasdaq']/1e9:.2f}B ({r['nasdaq_n']}) "
              f"NYSE {r['nyse']/1e9:.2f}B ({r['nyse_n']}) S&P {r['sp500']/1e9:.2f}B ({r['sp500_n']})", flush=True)


if __name__ == "__main__":
    main()
