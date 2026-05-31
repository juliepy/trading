"""
A 股行情下载 — 东方财富 HTTP + 新浪 HTTP + akshare 降级

支持周期（对外）:
  daily — 日线（前复权，约 5 年）
  4h    — 4 小时（内部由 60 分钟 K 线聚合，约 2 年）

本地缓存: data/{symbol}_{daily|4h}.csv，默认 4 小时有效期。
列名: Open / High / Low / Close / Volume
"""

import json
import os
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import pandas as pd

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# key → {code, market, name}
# market: 1=上交所, 0=深交所
SYMBOLS: dict[str, dict[str, str]] = {
    "HS300":  {"code": "510300", "market": "1", "name": "沪深300ETF", "is_index": "0"},
    "BOC":   {"code": "601988", "market": "1", "name": "中国银行", "is_index": "0"},
}

_EM_KLT_DAILY = "101"
_EM_KLT_60MIN = "60"
CACHE_MAX_AGE_HOURS = 4
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}

# 对外下载/回测/绘图周期（1h 仅作 4h 聚合中间数据，不持久化）
DOWNLOAD_TIMEFRAMES = ("daily", "4h")

# 4H 回测最低要求：不足则自动全量重拉分钟线
MIN_4H_BARS = 250
MIN_4H_SPAN_DAYS = 120
_EM_60MIN_CHUNK_DAYS = 30

# 新浪 CN_MarketData.getKLineData  scale: 60=60分钟  240=日线  datalen 最大约 1023
_SINA_KLINE_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData"
)
_SINA_DATALEN = 1023


def _http_get(url: str, timeout: int = 15) -> bytes | None:
    if _HAS_REQUESTS:
        try:
            resp = _requests.get(
                url, headers=_HEADERS, timeout=timeout, verify=False,
                proxies={"http": None, "https": None},
            )
            if resp.status_code == 200:
                return resp.content
        except Exception:
            pass
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ctx),
        )
        req = urllib.request.Request(url, headers=_HEADERS)
        with opener.open(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    col_map: dict[str, str] = {}
    for col in df.columns:
        lc = str(col).lower()
        if lc in ("open", "开盘", "开盘价"):
            col_map[col] = "Open"
        elif lc in ("high", "最高", "最高价"):
            col_map[col] = "High"
        elif lc in ("low", "最低", "最低价"):
            col_map[col] = "Low"
        elif lc in ("close", "收盘", "收盘价"):
            col_map[col] = "Close"
        elif lc in ("volume", "成交量", "vol", "amount", "成交额"):
            col_map[col] = "Volume"
    df = df.rename(columns=col_map)
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c not in df.columns:
            df[c] = 0.0
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    return df.sort_index()


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    agg = df.resample(rule, closed="left", label="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    return agg.dropna(subset=["Open", "Close"])


def _resample_to_4h(df: pd.DataFrame) -> pd.DataFrame:
    return _resample(df, "4h")


def _fetch_em_kline(
    market: str,
    code: str,
    klt: str,
    start_date: str,
    end_date: str,
    adjust: str = "1",
) -> pd.DataFrame | None:
    """东方财富 push2his K 线。adjust: 0不复权 1前复权 2后复权"""
    secid = f"{market}.{code}"
    params = urllib.parse.urlencode({
        "secid":   secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt":     klt,
        "fqt":     adjust,
        "beg":     start_date,
        "end":     end_date,
        "lmt":     "1000000",
    })
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + params
    try:
        raw = _http_get(url, timeout=15)
        if not raw:
            return None
        obj = json.loads(raw.decode("utf-8", "ignore"))
        klines = (obj.get("data") or {}).get("klines") or []
        if not klines:
            return None
        records = []
        for row in klines:
            parts = row.split(",")
            if len(parts) < 6:
                continue
            try:
                records.append({
                    "dt":     parts[0],
                    "Open":   float(parts[1]),
                    "Close":  float(parts[2]),
                    "High":   float(parts[3]),
                    "Low":    float(parts[4]),
                    "Volume": float(parts[5]),
                })
            except (ValueError, IndexError):
                continue
        if not records:
            return None
        df = pd.DataFrame(records)
        df.index = pd.to_datetime(df["dt"])
        df = df[["Open", "High", "Low", "Close", "Volume"]]
        return df[df["Close"] > 0].sort_index()
    except Exception as exc:
        print(f"  [东方财富] {code} klt={klt} 失败: {exc}")
        return None


def _is_index(code: str) -> bool:
    for info in SYMBOLS.values():
        if info["code"] == code:
            return info.get("is_index") == "1"
    return code.startswith("399") or code == "000001"


def _sina_symbol(market: str, code: str) -> str:
    """market: 1=上交所(sh)  0=深交所(sz)"""
    prefix = "sh" if market == "1" else "sz"
    return f"{prefix}{code}"


def _fetch_sina_kline(
    market: str,
    code: str,
    scale: int,
    datalen: int = _SINA_DATALEN,
) -> pd.DataFrame | None:
    """
    新浪 A 股 K 线 HTTP。
    scale: 60 → 60 分钟；240 → 日线（未复权，与东方财富前复权略有偏差）
    """
    symbol = _sina_symbol(market, code)
    params = urllib.parse.urlencode({
        "symbol":  symbol,
        "scale":   scale,
        "ma":      "no",
        "datalen": datalen,
    })
    url = f"{_SINA_KLINE_URL}?{params}"
    try:
        raw = _http_get(url, timeout=15)
        if not raw:
            return None
        data = json.loads(raw.decode("utf-8", "ignore"))
        if not isinstance(data, list) or not data:
            return None
        records = []
        for row in data:
            try:
                records.append({
                    "dt":     row["day"],
                    "Open":   float(row["open"]),
                    "High":   float(row["high"]),
                    "Low":    float(row["low"]),
                    "Close":  float(row["close"]),
                    "Volume": float(row.get("volume") or 0),
                })
            except (KeyError, ValueError, TypeError):
                continue
        if not records:
            return None
        df = pd.DataFrame(records)
        df.index = pd.to_datetime(df["dt"])
        df = df[["Open", "High", "Low", "Close", "Volume"]]
        return df[df["Close"] > 0].sort_index()
    except Exception as exc:
        print(f"  [新浪] {symbol} scale={scale} 失败: {exc}")
        return None


def _fetch_sina_daily(
    market: str, code: str, since: pd.Timestamp | None = None,
) -> pd.DataFrame | None:
    df = _fetch_sina_kline(market, code, scale=240)
    if df is None or df.empty:
        return None
    if since is not None:
        df = df[df.index >= since - pd.Timedelta(days=5)]
    return df


def _fetch_sina_60min(
    market: str, code: str, since: pd.Timestamp | None = None,
) -> pd.DataFrame | None:
    df = _fetch_sina_kline(market, code, scale=60)
    if df is None or df.empty:
        return None
    if since is not None:
        df = df[df.index >= since - pd.Timedelta(days=5)]
    return df


def _fetch_ak_daily(code: str) -> pd.DataFrame | None:
    try:
        import akshare as ak
        end_date = datetime.today().strftime("%Y%m%d")
        start_date = (datetime.today() - timedelta(days=365 * 5)).strftime("%Y%m%d")

        if _is_index(code):
            prefix = "sh" if code.startswith(("000", "5")) else "sz"
            df = ak.stock_zh_index_daily(symbol=f"{prefix}{code}")
            df = df.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
            df.index = pd.to_datetime(df.index)
            df = df.loc[start_date:end_date]
        else:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start_date, end_date=end_date, adjust="qfq",
            )
            date_col = next(
                (c for c in df.columns if c in ("日期", "date", "Date")),
                df.columns[0],
            )
            df = df.set_index(date_col)
            df.index = pd.to_datetime(df.index)
            df = _normalise_columns(df)

        return df[df["Close"] > 0].sort_index()
    except Exception as exc:
        print(f"  [akshare] {code} 日线失败: {exc}")
        return None


def _4h_cache_insufficient(df: pd.DataFrame | None) -> bool:
    """4H 缓存太短则 SuperTrend 几乎无交易，回测结果会全 0。"""
    if df is None or df.empty:
        return True
    if len(df) < MIN_4H_BARS:
        return True
    span_days = (df.index.max() - df.index.min()).days
    return span_days < MIN_4H_SPAN_DAYS


def _fetch_em_60min_long(
    market: str, code: str, days: int = 730,
) -> pd.DataFrame | None:
    """分段拉取东方财富 60 分钟线（单次接口仅 ~1.5 个月）。"""
    end_str = datetime.today().strftime("%Y%m%d")
    start_str = (datetime.today() - timedelta(days=days)).strftime("%Y%m%d")

    # 先尝试一次长区间（部分品种可一次返回较多数据）
    single = _fetch_em_kline(market, code, _EM_KLT_60MIN, start_str, end_str)
    if single is not None and len(single) >= MIN_4H_BARS * 2:
        return single

    end_dt = datetime.today()
    start_dt = end_dt - timedelta(days=days)
    chunks: list[pd.DataFrame] = []
    if single is not None and not single.empty:
        chunks.append(single)

    cur = start_dt
    while cur < end_dt:
        chunk_end = min(cur + timedelta(days=_EM_60MIN_CHUNK_DAYS), end_dt)
        df = _fetch_em_kline(
            market, code, _EM_KLT_60MIN,
            cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d"),
        )
        if df is not None and not df.empty:
            chunks.append(df)
        cur = chunk_end + timedelta(days=1)
        time.sleep(0.15)

    if not chunks:
        return None
    combined = pd.concat(chunks).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined[combined["Close"] > 0]


def _fetch_ak_60min_long(code: str, days: int = 730) -> pd.DataFrame | None:
    """分段拉取 akshare 60 分钟线。"""
    try:
        import akshare as ak
    except ImportError:
        return None

    end_dt = datetime.today()
    start_dt = end_dt - timedelta(days=days)
    chunks: list[pd.DataFrame] = []
    cur = start_dt
    while cur < end_dt:
        chunk_end = min(cur + timedelta(days=_EM_60MIN_CHUNK_DAYS), end_dt)
        try:
            df = ak.stock_zh_a_hist_min_em(
                symbol=code, period="60",
                start_date=cur.strftime("%Y-%m-%d %H:%M:%S"),
                end_date=chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
                adjust="qfq",
            )
        except Exception:
            df = None
        if df is not None and not df.empty:
            time_col = next(
                (c for c in df.columns if c in ("时间", "datetime", "Date")),
                df.columns[0],
            )
            df = df.set_index(time_col)
            df.index = pd.to_datetime(df.index)
            df = _normalise_columns(df)
            chunks.append(df[df["Close"] > 0])
        cur = chunk_end + timedelta(minutes=1)
        time.sleep(0.15)

    if not chunks:
        return None
    combined = pd.concat(chunks).sort_index()
    return combined[~combined.index.duplicated(keep="last")]


def _load_cache(path: str) -> pd.DataFrame | None:
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df if not df.empty else None
    except Exception:
        return None


def _merge_df(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        return new
    combined = pd.concat([existing, new]).sort_index()
    return combined[~combined.index.duplicated(keep="last")]


def _needs_update(existing: pd.DataFrame | None, tf: str) -> tuple[bool, pd.Timestamp | None]:
    if existing is None or existing.empty:
        return True, None
    last_dt = existing.index.max()
    gap_hours = (pd.Timestamp.now() - last_dt).total_seconds() / 3600
    threshold = 1.0 if tf == "1h" else 4.0
    if gap_hours < threshold:
        return False, None
    return True, last_dt


def _fetch_daily(
    market: str, code: str, since: pd.Timestamp | None = None,
) -> pd.DataFrame | None:
    end_date = datetime.today().strftime("%Y%m%d")
    if since is not None:
        start_date = (since - pd.Timedelta(days=5)).strftime("%Y%m%d")
    else:
        start_date = (datetime.today() - timedelta(days=365 * 5)).strftime("%Y%m%d")

    print(f"  [日线] 尝试东方财富 ({code})...")
    df = _fetch_em_kline(market, code, _EM_KLT_DAILY, start_date, end_date)
    if df is not None and not df.empty:
        print(f"  [日线] OK 东方财富 {len(df)} 行  "
              f"({df.index[0].date()} ~ {df.index[-1].date()})")
        return df

    print(f"  [日线] -- 降级新浪 ({code})...")
    df = _fetch_sina_daily(market, code, since=since)
    if df is not None and not df.empty:
        print(f"  [日线] OK 新浪 {len(df)} 行  "
              f"({df.index[0].date()} ~ {df.index[-1].date()})")
        return df

    print(f"  [日线] -- 降级 akshare ({code})...")
    df = _fetch_ak_daily(code)
    if df is not None and not df.empty:
        if since is not None:
            df = df[df.index >= since - pd.Timedelta(days=5)]
        print(f"  [日线] OK akshare {len(df)} 行")
        return df

    print(f"  [日线] FAIL {code}")
    return None


def _fetch_1h_long(market: str, code: str, days: int = 730) -> pd.DataFrame | None:
    """全量 60 分钟线：东方财富分段 → 新浪 → akshare，取数据量最多者。"""
    if _is_index(code):
        print(f"  [1H] {code} 指数分钟线暂不支持长历史")
        return None

    print(f"  [1H] 东方财富分段拉取 ({code}, {days} 天)...")
    em_df = _fetch_em_60min_long(market, code, days=days)

    print(f"  [1H] 新浪 ({code})...")
    sina_df = _fetch_sina_60min(market, code)

    print(f"  [1H] akshare 分段 ({code})...")
    ak_df = _fetch_ak_60min_long(code, days=days)

    best: pd.DataFrame | None = None
    for name, df in [("东方财富", em_df), ("新浪", sina_df), ("akshare", ak_df)]:
        if df is None or df.empty:
            continue
        if best is None or len(df) > len(best):
            best = df
            print(f"  [1H] 当前最优 {name} {len(df)} 行  "
                  f"({str(df.index[0])[:16]} ~ {str(df.index[-1])[:16]})")

    return best


def _fetch_1h_recent(
    market: str, code: str, since: pd.Timestamp,
) -> pd.DataFrame | None:
    """增量：拉取最近一段 60 分钟线。"""
    start_date = (since - pd.Timedelta(days=5)).strftime("%Y%m%d")
    end_date = datetime.today().strftime("%Y%m%d")
    df = _fetch_em_kline(market, code, _EM_KLT_60MIN, start_date, end_date)
    if df is not None and not df.empty:
        return df

    df = _fetch_sina_60min(market, code, since=since)
    if df is not None and not df.empty:
        return df

    if not _is_index(code):
        try:
            import akshare as ak
            end_dt = datetime.today().strftime("%Y-%m-%d %H:%M:%S")
            start_dt = (since - pd.Timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
            raw = ak.stock_zh_a_hist_min_em(
                symbol=code, period="60",
                start_date=start_dt, end_date=end_dt, adjust="qfq",
            )
            if raw is not None and not raw.empty:
                time_col = next(
                    (c for c in raw.columns if c in ("时间", "datetime", "Date")),
                    raw.columns[0],
                )
                raw = raw.set_index(time_col)
                raw.index = pd.to_datetime(raw.index)
                return _normalise_columns(raw)
        except Exception:
            pass
    return None


def _fetch_1h(
    market: str, code: str, since: pd.Timestamp | None = None,
) -> pd.DataFrame | None:
    if since is None:
        return _fetch_1h_long(market, code)

    print(f"  [1H] 增量 ({code}, since={str(since)[:16]})...")
    df = _fetch_1h_recent(market, code, since)
    if df is not None and not df.empty:
        print(f"  [1H] OK 增量 {len(df)} 行")
        return df
    print(f"  [1H] FAIL {code}")
    return None


def _fetch_4h(
    market: str,
    code: str,
    since: pd.Timestamp | None = None,
    existing: pd.DataFrame | None = None,
) -> pd.DataFrame | None:
    df1h = _fetch_1h_long(market, code) if since is None else _fetch_1h(market, code, since=since)

    if df1h is None or df1h.empty:
        return None

    df4h = _resample_to_4h(df1h)
    print(f"  [4H] 1H={len(df1h)} 行 → 4H={len(df4h)} 行  "
          f"({str(df4h.index[0])[:10]} ~ {str(df4h.index[-1])[:10]})")

    if since is not None and existing is not None and not existing.empty:
        df4h = _merge_df(existing, df4h)

    return df4h


def download_all(force: bool = False) -> dict[str, pd.DataFrame]:
    """
    下载/更新全部标的，返回 {symbol_tf: DataFrame}。
    key 示例: HS300_daily, HS300_4h, BOC_daily
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    result: dict[str, pd.DataFrame] = {}

    for name, info in SYMBOLS.items():
        market = info["market"]
        code   = info["code"]
        display = info["name"]

        timeframes = [
            (tf, os.path.join(DATA_DIR, f"{name}_{tf}.csv"))
            for tf in DOWNLOAD_TIMEFRAMES
        ]

        for tf, path in timeframes:
            key = f"{name}_{tf}"
            existing = None if force else _load_cache(path)
            need_update, since = _needs_update(existing, tf)

            if tf == "4h" and existing is not None and _4h_cache_insufficient(existing):
                if not force:
                    print(f"[{name}] {display} 4h    缓存不足 ({len(existing)} 行)，"
                          f"跳过增量；请 python run.py --force 重拉分钟线")
                    result[key] = existing
                    continue
                since = None  # force 时全量重拉

            if not force and not need_update:
                last_str = str(existing.index.max())[:16]
                print(f"[{name}] {display} {tf:5s} 已是最新 ({len(existing)} 行，最新 {last_str})")
                result[key] = existing
                continue

            mode = "增量" if since is not None else "全量"
            since_str = str(since)[:10] if since else "初始"
            print(f"[{name}] {display} {tf:5s} {mode}下载（起点={since_str}）...")

            if tf == "daily":
                new_df = _fetch_daily(market, code, since=since)
            else:
                new_df = _fetch_4h(market, code, since=since, existing=existing)

            if new_df is not None and not new_df.empty:
                merged = _merge_df(existing, new_df) if existing is not None else new_df
                merged.to_csv(path)
                added = len(merged) - (len(existing) if existing is not None else 0)
                print(f"  -> {mode}完成：新增 {max(added, 0)} 行，共 {len(merged)} 行")
                result[key] = merged
            elif existing is not None:
                print(f"  [警告] {tf} 更新失败，使用旧缓存（{len(existing)} 行）")
                result[key] = existing
            else:
                fallback = _load_cache(path)
                if fallback is not None:
                    print(f"  [警告] {tf} 下载失败，使用旧缓存（{len(fallback)} 行）")
                    result[key] = fallback
                else:
                    print(f"  [错误] {tf} 下载全部失败: {name}")

    return result


def get_symbol_info(key: str) -> dict[str, str] | None:
    """根据 short key（如 HS300）返回配置。"""
    return SYMBOLS.get(key.upper())


if __name__ == "__main__":
    data = download_all(force=True)
    print()
    print(f"{'Key':<16} {'行数':>6}  {'开始':>12}  {'结束':>12}  {'最新收盘':>10}")
    print("-" * 64)
    for key, df in sorted(data.items()):
        if df is not None and not df.empty:
            print(f"{key:<16} {len(df):>6}  "
                  f"{str(df.index[0])[:10]:>12}  "
                  f"{str(df.index[-1])[:10]:>12}  "
                  f"{df['Close'].iloc[-1]:>10.2f}")
