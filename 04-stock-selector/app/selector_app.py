#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选股引擎 — Web服务入口
提供三种策略的选股 API
"""

import os
import sys
from datetime import datetime

# ── 路径注入（使 data/ selectors/ utils/ 均可直接 import）─────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 04-stock-selector/
for _sub in ('data', 'selectors', 'utils'):
    _p = os.path.join(_ROOT, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flask import Flask, render_template, jsonify, request

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

from config import WEB_HOST, WEB_PORT

# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _compute_indicators(df) -> dict:
    """从历史K线 DataFrame 计算 MA/RSI/MACD/KDJ/BOLL/ATR，缺数据的字段不写入。"""
    import numpy as np
    result = {}
    try:
        close = df['close'].astype(float).values
        high  = df['high'].astype(float).values
        low   = df['low'].astype(float).values
        n = len(close)

        def _ema_series(arr, period):
            k = 2.0 / (period + 1)
            out = np.empty(len(arr))
            out[0] = arr[0]
            for i in range(1, len(arr)):
                out[i] = arr[i] * k + out[i - 1] * (1 - k)
            return out

        # MA
        for p, name in [(5, 'ma5'), (10, 'ma10'), (20, 'ma20'), (60, 'ma60')]:
            if n >= p:
                result[name] = round(float(np.mean(close[-p:])), 3)

        # RSI(14) — simple average seed
        if n >= 15:
            delta  = np.diff(close)
            up_arr = np.where(delta > 0, delta, 0.0)
            dn_arr = np.where(delta < 0, -delta, 0.0)
            avg_up = float(np.mean(up_arr[-14:]))
            avg_dn = float(np.mean(dn_arr[-14:]))
            rsi = 100.0 - 100.0 / (1 + avg_up / avg_dn) if avg_dn > 0 else 100.0
            result['rsi'] = round(rsi, 2)

        # MACD(12,26,9)
        if n >= 35:
            ema12      = _ema_series(close, 12)
            ema26      = _ema_series(close, 26)
            dif_series = ema12 - ema26
            dea_series = _ema_series(dif_series, 9)
            result['dif']  = round(float(dif_series[-1]), 4)
            result['dea']  = round(float(dea_series[-1]), 4)
            result['macd'] = round(float((dif_series[-1] - dea_series[-1]) * 2), 4)

        # KDJ(9,3,3)
        if n >= 9:
            k_val, d_val = 50.0, 50.0
            window = min(n, 60)
            h_w, l_w, c_w = high[-window:], low[-window:], close[-window:]
            for i in range(len(c_w) - 9 + 1):
                h9  = float(np.max(h_w[i:i + 9]))
                l9  = float(np.min(l_w[i:i + 9]))
                rsv = (c_w[i + 8] - l9) / (h9 - l9) * 100 if (h9 - l9) > 0 else 50.0
                k_val = rsv / 3 + k_val * 2 / 3
                d_val = k_val / 3 + d_val * 2 / 3
            j_val = 3 * k_val - 2 * d_val
            result.update({
                'kdj_k': round(k_val, 2),
                'kdj_d': round(d_val, 2),
                'kdj_j': round(j_val, 2),
            })

        # BOLL(20, 2σ)
        if n >= 20:
            mid = float(np.mean(close[-20:]))
            std = float(np.std(close[-20:], ddof=1))
            result['boll_mid']   = round(mid, 3)
            result['boll_upper'] = round(mid + 2 * std, 3)
            result['boll_lower'] = round(mid - 2 * std, 3)

        # ATR(14)
        if n >= 15:
            tr_arr = [
                max(high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i]  - close[i - 1]))
                for i in range(-14, 0)
            ]
            result['atr'] = round(float(np.mean(tr_arr)), 3)

    except Exception as _e:
        print(f'⚠️ _compute_indicators 失败: {_e}', flush=True)

    return result


def _fetch_eastmoney_fund_flow(code: str) -> dict:
    """东方财富实时资金流向明细（超大/大/中/小单净流入 + 主力净占比）。
    字段说明（push2 fflow/get）：
      f62  主力净流入（元）   f184 主力净流入占比（%）
      f66  超大单净流入（元） f69  超大单净流入占比
      f72  大单净流入（元）   f75  大单净流入占比
      f78  中单净流入（元）   f81  中单净流入占比
      f84  小单净流入（元）   f87  小单净流入占比
    """
    import urllib.request, urllib.parse, json as _json
    secid  = '1.' + code if code.startswith('6') else '0.' + code
    fields = 'f62,f184,f66,f69,f72,f75,f78,f81,f84,f87'
    url = ('https://push2.eastmoney.com/api/qt/stock/fflow/get?'
           + urllib.parse.urlencode({'secid': secid, 'fields': fields}))
    req = urllib.request.Request(
        url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        obj = _json.loads(resp.read().decode('utf-8', 'ignore'))
    d = obj.get('data') or {}
    mapping = {
        'f62':  'main_net_inflow',      # 主力净流入（元）
        'f184': 'main_net_inflow_pct',  # 主力净流入占比（%）
        'f66':  'super_large_net',      # 超大单净流入（元）
        'f72':  'large_net',            # 大单净流入（元）
        'f78':  'medium_net',           # 中单净流入（元）
        'f84':  'small_net',            # 小单净流入（元）
    }
    result = {v: float(d[k]) for k, v in mapping.items() if d.get(k) is not None}
    # main_ratio 是 main_net_inflow_pct 的别名，LLM prompt 中两者均引用
    if 'main_net_inflow_pct' in result:
        result['main_ratio'] = result['main_net_inflow_pct']
    return result


def _fetch_eastmoney_days_continuous(code: str):
    """从东方财富历史资金流向K线计算主力连续净流入/流出天数 + 近5日累计净流入。
    返回 dict：
      days_continuous: 正整数=连续净流入N天；负整数=连续净流出N天
      main_net_5day:   近5个交易日主力净流入累计（元）
    失败时返回 None。
    """
    import urllib.request, urllib.parse, json as _json
    secid = '1.' + code if code.startswith('6') else '0.' + code
    url = ('https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?'
           + urllib.parse.urlencode({
               'lmt': '0', 'klt': '101',
               'fields1': 'f1,f2,f3,f7',
               'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63',
               'secid': secid,
           }))
    req = urllib.request.Request(
        url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        obj = _json.loads(resp.read().decode('utf-8', 'ignore'))
    klines = (obj.get('data') or {}).get('klines') or []
    if not klines:
        return None
    # kline 格式: "date,main_net,main_pct,super_large_net,..."（fields2 顺序）
    # f52 对应 index=1（主力净流入元）
    main_flows = []
    for kl in klines[-10:]:
        parts = kl.split(',')
        if len(parts) > 1:
            try:
                main_flows.append(float(parts[1]))
            except (ValueError, IndexError):
                pass
    if not main_flows:
        return None
    # 连续方向天数
    positive = main_flows[-1] >= 0
    count = 0
    for v in reversed(main_flows):
        if (v >= 0) == positive:
            count += 1
        else:
            break
    # 近5日累计净流入
    last5 = main_flows[-5:] if len(main_flows) >= 5 else main_flows
    main_net_5day = sum(last5)
    return {
        'days_continuous': count if positive else -count,
        'main_net_5day':   round(main_net_5day, 2),
    }


# ── 页面路由 ────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


# ── 选股 API ─────────────────────────────────────────────────────────────────
_UNIVERSE_MAP = {
    'hs300':    '000300',   # 沪深300
    'zz500':    '000905',   # 中证500
    'gem_star': 'gem_star', # 创业板+科创板
}


def _resolve_index_code(universe: str) -> str:
    """将前端 universe 值转为后端 index_code"""
    return _UNIVERSE_MAP.get(universe or 'hs300', '000300')


@app.route('/api/selector/run', methods=['POST'])
def api_run_selector():
    """
    运行选股器
    请求体: {"type": "short|long|enhanced", "top_n": 5, "universe": "hs300|zz500|gem_star"}
    """
    data = request.json or {}
    selector_type = data.get('type', 'long')
    top_n = int(data.get('top_n', 5))
    index_code = _resolve_index_code(data.get('universe', 'hs300'))

    try:
        if selector_type == 'short':
            from short_term_selector import ShortTermSelector
            selector = ShortTermSelector(index_code=index_code)
        elif selector_type == 'enhanced':
            from enhanced_long_term_selector import EnhancedLongTermSelector
            selector = EnhancedLongTermSelector(index_code=index_code)
        else:
            from long_term_selector import LongTermSelector
            selector = LongTermSelector(index_code=index_code)

        stocks = selector.select_top_stocks(top_n=top_n)
        selector.close()

        return jsonify({
            'status': 'success',
            'type': selector_type,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'data': stocks,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/selector/report', methods=['POST'])
def api_get_selector_report():
    """
    生成选股文字报告
    请求体: {"type": "short|long|enhanced", "stocks": [...], "universe": "hs300|zz500|gem_star"}
    """
    data = request.json or {}
    selector_type = data.get('type', 'long')
    stocks = data.get('stocks', [])
    index_code = _resolve_index_code(data.get('universe', 'hs300'))

    if not stocks:
        return jsonify({'status': 'error', 'message': '无数据'})

    try:
        if selector_type == 'short':
            from short_term_selector import ShortTermSelector
            selector = ShortTermSelector(index_code=index_code)
        elif selector_type == 'enhanced':
            from enhanced_long_term_selector import EnhancedLongTermSelector
            selector = EnhancedLongTermSelector(index_code=index_code)
        else:
            from long_term_selector import LongTermSelector
            selector = LongTermSelector(index_code=index_code)

        report = selector.generate_report(stocks)
        selector.close()

        return jsonify({'status': 'success', 'report': report})

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


# ── GPT 深度分析 API ──────────────────────────────────────────────────────────
@app.route('/api/selector/gpt-analyze', methods=['POST'])
def api_gpt_analyze():
    """
    对选股结果调用 GPT-4.1 生成深度研报
    请求体: {"type": "short|long|enhanced", "top_n": 5}
      或传入已计算好的股票列表: {"stocks": [...]}
    可选: {"stream": true}  — 流式返回
    """
    from flask import Response, stream_with_context
    data = request.json or {}
    stocks = data.get('stocks')
    selector_type = data.get('type', 'long')
    index_code = _resolve_index_code(data.get('universe', 'hs300'))

    # 若未传 stocks，先运行选股器
    if not stocks:
        top_n = int(data.get('top_n', 5))
        try:
            if selector_type == 'short':
                from short_term_selector import ShortTermSelector
                selector = ShortTermSelector(index_code=index_code)
            elif selector_type == 'enhanced':
                from enhanced_long_term_selector import EnhancedLongTermSelector
                selector = EnhancedLongTermSelector(index_code=index_code)
            else:
                from long_term_selector import LongTermSelector
                selector = LongTermSelector(index_code=index_code)
            stocks = selector.select_top_stocks(top_n=top_n)
            selector.close()
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'选股失败: {e}'})

    if not stocks:
        return jsonify({'status': 'error', 'message': '选股结果为空，无法进行 GPT 分析'})

    # 将选股器输出适配为 gpt_analyst 所需格式
    codes = [s['code'] for s in stocks]
    stocks_data = []
    for s in stocks:
        det    = s.get('details') or {}
        ff     = det.get('fund_flow') or {}
        trade  = det.get('trade_points') or {}

        # 各选股器将不同指标存入 details 的不同子键
        trend_info  = det.get('trend') or {}       # long_term / enhanced
        rsi_info    = det.get('rsi') or {}          # short_term
        kdj_info    = det.get('kdj') or {}          # short_term
        macd_info   = det.get('macd') or {}         # short_term
        boll_info   = det.get('bollinger') or {}    # short_term
        vol_info    = det.get('volume') or {}       # both
        strength    = det.get('strength') or {}     # long_term / enhanced

        # 根据 details 内容区分短线/中长线评分来源
        is_short = 'rsi' in det    # short_term_selector 特征键
        is_long  = 'trend' in det  # long_term_selector 特征键

        # 从 enhanced 选股器的 details['fundamental'] 提取基本面数据
        _fund_det = det.get('fundamental') or {}

        entry = {
            'code':         s.get('code'),
            'name':         s.get('name'),
            'price':        s.get('price'),
            'change_pct':   s.get('change_pct'),
            'volume_ratio': vol_info.get('volume_ratio'),
            # 基本面（enhanced 选股器已算；long/short 选股器在补充阶段从缓存填入）
            'fundamental': {
                'roe':            _fund_det.get('roe'),
                'dividend_yield': _fund_det.get('dividend_yield'),
                'revenue_growth': _fund_det.get('revenue_growth'),
                'profit_growth':  _fund_det.get('profit_growth'),
            },
            'tech_indicators': {
                # 均线 —— long_term 在 trend 里；short_term 暂无，后面缓存补充
                'ma20':       trend_info.get('ma20'),
                'ma60':       trend_info.get('ma60'),
                # 短线指标 —— short_term_selector 已计算
                'rsi':        rsi_info.get('value'),
                'macd':       macd_info.get('macd_hist'),   # MACD 柱
                'dif':        macd_info.get('dif'),
                'dea':        macd_info.get('dea'),
                'kdj_k':      kdj_info.get('k'),
                'kdj_d':      kdj_info.get('d'),
                'kdj_j':      kdj_info.get('j'),
                'boll_upper': boll_info.get('upper'),
                'boll_mid':   boll_info.get('middle'),
                'boll_lower': boll_info.get('lower'),
                # 趋势强度
                'adx':        strength.get('adx'),
                'atr':        trade.get('atr'),
                # 量化评分：短线/中长线分开标注
                'short_score': s.get('score') if is_short else None,
                'long_score':  s.get('score') if is_long  else None,
            },
            'fund_flow': {
                # main_in 在 selector 内部单位已是"万元"，还原为元传给 LLM
                'main_net_inflow': (
                    ff.get('main_in') * 10000
                    if ff.get('main_in') is not None else None
                ),
                'main_ratio': ff.get('main_ratio'),
            },
            # 选股专属字段
            'selector_score':    s.get('score'),
            'selector_rating':   s.get('rating'),
            'buy_signals':       s.get('buy_signals', []),
            'stop_loss':         s.get('stop_loss'),
            'take_profit':       s.get('take_profit'),
            'stop_loss_pct':     s.get('stop_loss_pct'),
            'take_profit_pct':   s.get('take_profit_pct'),
            'risk_reward_ratio': s.get('risk_reward_ratio'),
        }
        stocks_data.append(entry)

    # ── 补充数据（行情/技术指标/资金流向/基本面）────────────────────────────
    try:
        import sys as _sys, os as _os
        _data_dir = _os.path.join(_ROOT, 'data')
        if _data_dir not in _sys.path:
            _sys.path.insert(0, _data_dir)
        from stock_cache_db import StockCache as _SC
        _sc = _SC()

        # ① 东方财富批量行情 → pe_ttm / market_cap / volume_ratio / turnover
        _em_batch = {}
        try:
            from eastmoney_api import EastMoneyAPI as _EMAPI
            _em_rows = _EMAPI(timeout=8).get_batch(codes)
            _em_batch = {r['code']: r for r in _em_rows}
            print(f'[补充] EastMoney批量行情成功，获取 {len(_em_batch)} 条', flush=True)
        except Exception as _e:
            print(f'⚠️ EastMoney批量行情失败: {_e}', flush=True)

        for entry in stocks_data:
            _code = entry['code']
            _em   = _em_batch.get(_code) or {}

            # 行情字段补充（volume / turnover / change_amount）
            _si = _sc.get_stock(_code)
            if _si:
                if entry.get('volume') is None:
                    entry['volume'] = _si.get('volume')
                if entry.get('turnover') is None:
                    entry['turnover'] = _si.get('amount')
            # 覆盖/补充东财实时字段
            if _em:
                # pe_ttm：只接受 > 0 的有效值，避免用 0 覆盖
                _pe = _em.get('pe_ratio')
                if _pe and float(_pe) > 0:
                    entry['pe_ttm'] = round(float(_pe), 2)
                if entry.get('market_cap') is None and _em.get('market_cap'):
                    entry['market_cap'] = _em['market_cap']
                # 流通市值：f21
                if entry.get('float_market_cap') is None and _em.get('float_market_cap'):
                    entry['float_market_cap'] = _em['float_market_cap']
                if entry.get('volume_ratio') is None and _em.get('volume_ratio'):
                    entry['volume_ratio'] = _em['volume_ratio']
                if entry.get('turnover') is None and _em.get('turnover'):
                    entry['turnover'] = _em['turnover']
                if entry.get('change_amount') is None and _em.get('change_amount'):
                    entry['change_amount'] = _em['change_amount']

            # ② 技术指标补充：先从缓存，再从K线实时计算
            _ALL_TI = ('ma5', 'ma10', 'ma20', 'ma60', 'rsi',
                       'dif', 'dea', 'macd',
                       'kdj_k', 'kdj_d', 'kdj_j',
                       'boll_upper', 'boll_mid', 'boll_lower', 'atr')
            ti = entry.setdefault('tech_indicators', {})

            # 2a) 从缓存补（MA5/10/20/RSI/MACD/DIF/DEA；MA60 缓存表暂无列，跳过无妨）
            _ti_cache = _sc.get_tech_indicators(_code)
            if _ti_cache:
                for _k in ('ma5', 'ma10', 'ma20', 'rsi', 'macd', 'dif', 'dea'):
                    if ti.get(_k) is None and _ti_cache.get(_k) is not None:
                        ti[_k] = _ti_cache[_k]

            # 2b) 仍有缺失（尤其 MA60/KDJ/BOLL/ATR 缓存无存）→ 从历史K线实时计算全部指标
            _missing_ti = [_k for _k in _ALL_TI if ti.get(_k) is None]
            if _missing_ti:
                print(f'[补充] {_code} 技术指标缺失: {_missing_ti}，启动K线计算…', flush=True)
                try:
                    from hybrid_data_source import get_hybrid_source as _ghs
                    _df = _ghs().get_history_data(_code, days=120)
                    if _df is not None and len(_df) >= 20:
                        _calc = _compute_indicators(_df)
                        for _k, _v in _calc.items():
                            if ti.get(_k) is None and _v is not None:
                                ti[_k] = _v
                        _filled = [k for k in _missing_ti if ti.get(k) is not None]
                        print(f'[补充] {_code} K线指标填入: {_filled}', flush=True)
                    else:
                        print(f'⚠️ {_code} K线数据不足（{len(_df) if _df is not None else 0}条）', flush=True)
                except Exception as _e:
                    import traceback as _tb
                    print(f'⚠️ {_code} K线指标计算失败: {_e}', flush=True)
                    _tb.print_exc()

            # ③ 基本面 PE：仅在东财未提供有效值时从缓存读取
            if not (entry.get('pe_ttm') and float(entry['pe_ttm']) > 0):
                try:
                    _cur = _sc.conn.cursor()
                    _cur.execute('SELECT pe FROM fundamental WHERE code=?', (_code,))
                    _row = _cur.fetchone()
                    if _row and _row[0] and float(_row[0]) > 0:
                        entry['pe_ttm'] = round(float(_row[0]), 2)
                except Exception:
                    pass

            # ⑤ 基本面 ROE / 股息率 / 营收增长率
            #    优先级：entry 已有（enhanced 已算）> StockCache 缓存 > 实时 FundamentalData
            _fund = entry.setdefault('fundamental', {})
            if not any(_fund.get(_k) for _k in ('roe', 'dividend_yield', 'revenue_growth')):
                # 先走缓存（enhanced 模式已写入）
                try:
                    _f_cached = _sc.get_fundamental(_code)
                    if _f_cached:
                        for _fk in ('roe', 'dividend_yield', 'revenue_growth', 'profit_growth'):
                            if _fund.get(_fk) is None and _f_cached.get(_fk) is not None:
                                _fund[_fk] = _f_cached[_fk]
                except Exception:
                    pass
                # 若缓存仍无数据（short/long 模式从未运行过 enhanced），实时抓取
                if not any(_fund.get(_k) for _k in ('roe', 'dividend_yield', 'revenue_growth')):
                    try:
                        import sys as _sys2, os as _os2
                        _sel_dir = _os2.path.join(_ROOT, 'selectors')
                        if _sel_dir not in _sys2.path:
                            _sys2.path.insert(0, _sel_dir)
                        from fundamental_data import FundamentalData as _FD
                        _fd = _FD(cache=_sc)
                        _f_live = _fd.get_stock_fundamental(_code)
                        for _fk in ('roe', 'dividend_yield', 'revenue_growth', 'profit_growth'):
                            if _f_live.get(_fk) is not None:
                                _fund[_fk] = _f_live[_fk]
                        print(f'[补充] {_code} 基本面(实时): ROE={_fund.get("roe")} '
                              f'股息率={_fund.get("dividend_yield")} '
                              f'营收增长={_fund.get("revenue_growth")}', flush=True)
                    except Exception as _e:
                        print(f'⚠️ {_code} 基本面实时获取失败: {_e}', flush=True)

            # ④ 资金流向明细（超大/大/中/小单净流入 + 主力净占比 + 连续天数）
            _ff = entry.setdefault('fund_flow', {})
            try:
                _ff_live = _fetch_eastmoney_fund_flow(_code)
                for _k, _v in _ff_live.items():
                    # live 数据始终覆盖（修正 main_in=0 的假零问题）
                    _ff[_k] = _v
                print(f'[补充] {_code} 资金流向: 主力净={_ff_live.get("main_net_inflow", "N/A")} '
                      f'超大={_ff_live.get("super_large_net", "N/A")} '
                      f'大={_ff_live.get("large_net", "N/A")}', flush=True)
            except Exception as _e:
                print(f'⚠️ {_code} 资金流向获取失败: {_e}', flush=True)

            # 连续净流入/流出天数 + 近5日累计净流入
            try:
                _days_result = _fetch_eastmoney_days_continuous(_code)
                if _days_result is not None:
                    _ff['days_continuous'] = _days_result['days_continuous']
                    _ff['main_net_5day']   = _days_result['main_net_5day']
                    print(f'[补充] {_code} 连续资金方向: {_days_result["days_continuous"]} 天 '
                          f'| 近5日累计: {_days_result["main_net_5day"]/1e8:.2f}亿', flush=True)
            except Exception as _e:
                print(f'⚠️ {_code} 连续天数获取失败: {_e}', flush=True)

        _sc.close()
    except Exception as _e:
        print(f'⚠️ 补充数据失败: {_e}', flush=True)

    sentiment = {
        'score': None,
        'level': '未知',
        'description': '本次分析来自选股引擎，无实时市场情绪评分',
    }

    use_stream = bool(data.get('stream', False))

    try:
        from llm_analyst import run_single_analysis
        if use_stream:
            import json as _json
            def generate():
                for entry in stocks_data:
                    for chunk in run_single_analysis(
                        entry['code'], sentiment, entry,
                        stream=True, selector_type=selector_type
                    ):
                        yield f"data: {_json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            return Response(stream_with_context(generate()), content_type='text/event-stream; charset=utf-8')
        else:
            reports = []
            for entry in stocks_data:
                reports.append(
                    run_single_analysis(
                        entry['code'], sentiment, entry,
                        stream=False, selector_type=selector_type
                    )
                )
            report = '\n\n---\n\n'.join(reports)
            return jsonify({'status': 'success', 'report': report})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/selector/sentiment', methods=['POST'])
def api_sentiment_analyze():
    """
    对单只股票做新闻 + 技术指标综合情绪分析（仿 01-News_Sentiment_Scanner 流程）。
    请求体: {"stock": {...}, "type": "short|long|enhanced"}
    返回:
      {
        "status": "success",
        "sentiment": "正面|负面|中性",
        "score": float,
        "reason": str,
        "news_score": float,
        "news_summary": {"正面": n, "负面": n, "中性": n},
        "articles": [{"title", "published", "sentiment", "score", "reason"}, ...]
      }
    """
    data = request.json or {}
    stock = data.get('stock') or {}
    selector_type = data.get('type', 'long')

    if not stock or not stock.get('code'):
        return jsonify({'status': 'error', 'message': '缺少 stock.code'})

    try:
        from llm_analyst import analyze_stock_sentiment
        result = analyze_stock_sentiment(
            code=stock['code'],
            stock_data=stock,
            selector_type=selector_type,
        )
        return jsonify({'status': 'success',
                        'sentiment':        result['sentiment'],
                        'score':            result['score'],
                        'reason':           result.get('reason', ''),
                        'news_summary_text':result.get('news_summary_text', ''),
                        'technical_analysis': result.get('technical_analysis', ''),
                        'fund_flow_analysis': result.get('fund_flow_analysis', ''),
                        'industry_logic_status': result.get('industry_logic_status', ''),
                        'industry_logic_reason': result.get('industry_logic_reason', ''),
                        'trading_logic_status': result.get('trading_logic_status', ''),
                        'trading_logic_reason': result.get('trading_logic_reason', ''),
                        'scenario_strong': result.get('scenario_strong', ''),
                        'scenario_mid': result.get('scenario_mid', ''),
                        'scenario_weak': result.get('scenario_weak', ''),
                        'impact_score': result.get('impact_score', ''),
                        'confidence': result.get('confidence', ''),
                        'confidence_reason': result.get('confidence_reason', ''),
                        'one_line_conclusion': result.get('one_line_conclusion', ''),
                        'tech_alignment':   result.get('tech_alignment', ''),
                        'conclusion':       result.get('conclusion', ''),
                        'news_score':       result['news_score'],
                        'news_summary':     result['news_summary'],
                        'articles':         result['articles']})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)})


# ── 市场情绪 API ────────────────────────────────────────────────────────────
@app.route('/api/market/sentiment', methods=['GET'])
def api_market_sentiment():
    """
    7维市场情绪评分。
    尝试调用 data/market_sentiment.py（若存在），否则从东方财富全量
    行情缓存快速估算：涨跌比 / 均涨幅 / 涨停率 / 强势股比 / 成交活跃度。
    """
    try:
        from market_sentiment import MarketSentiment
        ms = MarketSentiment()
        result = ms.calculate()
        return jsonify({'status': 'success', 'data': result})
    except ImportError:
        pass
    except Exception as e:
        pass

    # 快速估算：从 stock_cache_db 取当天全量行情
    try:
        from stock_cache_db import StockCache
        cache = StockCache()
        conn = cache.conn
        cursor = conn.cursor()
        from datetime import date as _date
        today = _date.today().isoformat()
        cursor.execute(
            "SELECT change_pct, price FROM stocks WHERE date(update_time)=? AND price>0",
            (today,)
        )
        rows = cursor.fetchall()
        cache.close()

        if len(rows) < 50:
            return jsonify({
                'status': 'success',
                'data': {
                    'score': None, 'level': '数据不足',
                    'description': f'缓存仅 {len(rows)} 条，建议先运行选股或全市场更新',
                    'dimensions': {}
                }
            })

        changes = [r[0] for r in rows if r[0] is not None]
        up   = sum(1 for c in changes if c > 0)
        down = sum(1 for c in changes if c < 0)
        total = len(changes)
        limit_up = sum(1 for c in changes if c >= 9.9)

        up_ratio       = up / total
        avg_change     = sum(changes) / total
        limit_up_rate  = limit_up / total
        strong_ratio   = sum(1 for c in changes if c >= 3) / total

        score = (
            up_ratio       * 30 +
            min(max(avg_change / 5, 0), 1) * 20 +
            min(limit_up_rate / 0.03, 1)   * 20 +
            min(strong_ratio  / 0.15, 1)   * 15 +
            15  # 成交量维度（缓存无量数据，给中性基础分）
        )
        score = round(min(max(score, 0), 100), 1)

        if score >= 75: level = '极度乐观'
        elif score >= 60: level = '乐观'
        elif score >= 50: level = '中性偏多'
        elif score >= 40: level = '中性偏空'
        elif score >= 25: level = '悲观'
        else: level = '极度悲观'

        return jsonify({'status': 'success', 'data': {
            'score': score,
            'level': level,
            'description': f'涨跌比 {up}:{down}，均涨幅 {avg_change:.2f}%，涨停 {limit_up} 只',
            'dimensions': {
                '涨跌比':     round(up_ratio * 100, 1),
                '均涨幅':     round(avg_change, 2),
                '涨停率%':    round(limit_up_rate * 100, 2),
                '强势股比%':  round(strong_ratio * 100, 1),
                '样本数':     total,
            }
        }})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


# ── 龙虎榜 API ──────────────────────────────────────────────────────────────
@app.route('/api/lhb/top', methods=['GET'])
def api_lhb_top():
    """返回龙虎榜净买入 top-10 及情绪分析，先读缓存；无缓存则实时拉取并写入。"""
    try:
        from lhb_fetcher import LHBFetcher
        fetcher = LHBFetcher()
        top = fetcher.get_top_lhb_stocks(limit=10)
        if not top:
            # 尝试实时拉取今日龙虎榜
            fetcher.save_lhb_to_cache()
            top = fetcher.get_top_lhb_stocks(limit=10)
        sentiment = fetcher.analyze_lhb_sentiment()
        return jsonify({'status': 'success', 'data': {'top': top, 'sentiment': sentiment}})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)})


# ── 启动 ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import socket
    try:
        _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _s.connect(("8.8.8.8", 80))
        _local_ip = _s.getsockname()[0]
        _s.close()
    except Exception:
        _local_ip = "127.0.0.1"

    print(f"""
╔══════════════════════════════════════════════════════╗
║              📈 选股引擎 Web服务                      ║
║                                                      ║
║   本机访问:   http://localhost:{WEB_PORT}                ║
║   远程访问:   http://{_local_ip}:{WEB_PORT}          ║
╚══════════════════════════════════════════════════════╝
""")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=True, use_reloader=False)
