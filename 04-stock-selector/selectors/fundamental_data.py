#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基本面数据获取模块 (FundamentalData) — 通过 akshare 免费接口"""

import pandas as pd
from typing import Dict


class FundamentalData:

    def __init__(self, cache=None):
        """
        :param cache: StockCache 实例（可选）。传入后基本面数据会被缓存 24 小时，
                     避免每次分析都重复调用慢速 THS/EM 接口。
        """
        self._cache = cache

    def get_stock_fundamental(self, code: str) -> Dict:
        """
        获取股票基本面数据
        返回: roe, profit_growth, dividend_yield, revenue_growth, pe
        失败时返回默认零值，保证不影响选股流程
        """
        result = {
            'roe': 0.0,
            'profit_growth': 0.0,
            'dividend_yield': 0.0,
            'revenue_growth': 0.0,
            'pe': 0.0,
        }

        # ── 缓存命中直接返回 ─────────────────────────────────────────
        if self._cache is not None:
            cached = self._cache.get_fundamental(code)
            if cached is not None:
                return cached

        try:
            import akshare as ak

            # ── 财务指标（ROE、利润增长等） ──────────────────────────────
            try:
                df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    print(f'[FundamentalData] {code} THS列名: {list(df.columns)}', flush=True)
                    # 净资产收益率 ROE
                    _ROE_KEYS = ('净资产收益率', 'ROE', 'roe', '加权净资产收益率')
                    for col in df.columns:
                        if any(k in str(col) for k in _ROE_KEYS):
                            val = _to_float(row[col])
                            if val is not None:
                                result['roe'] = val
                            break
                    # 净利润增长率
                    _PROFIT_KEYS = ('净利润增长', '净利润同比', '归母净利润增长', '净利润增长率')
                    for col in df.columns:
                        if any(k in str(col) for k in _PROFIT_KEYS):
                            val = _to_float(row[col])
                            if val is not None:
                                result['profit_growth'] = val
                            break
                    # 营收增长率
                    _REV_KEYS = ('营业总收入同比', '营业收入增长', '营收同比', '营业总收入增长', '收入增长')
                    for col in df.columns:
                        if any(k in str(col) for k in _REV_KEYS):
                            val = _to_float(row[col])
                            if val is not None:
                                result['revenue_growth'] = val
                            break
            except Exception as _e:
                print(f'[FundamentalData] {code} THS财务指标获取失败: {_e}', flush=True)

            # ── 市盈率（EM个股信息，无股息率字段） ─────────────────────────
            try:
                spot = ak.stock_individual_info_em(symbol=code)
                if spot is not None and not spot.empty:
                    spot_dict = dict(zip(spot.iloc[:, 0], spot.iloc[:, 1]))
                    print(f'[FundamentalData] {code} EM个股信息keys: {list(spot_dict.keys())}', flush=True)
                    pe_val = spot_dict.get('市盈率(动)', spot_dict.get('市盈率(TTM)', spot_dict.get('市盈率', 0)))
                    result['pe'] = _to_float(pe_val) or 0.0
                    # 流通市值（供调用方使用）
                    _fmc = spot_dict.get('流通市值')
                    if _fmc is not None:
                        result['float_market_cap_str'] = str(_fmc)
            except Exception as _e:
                print(f'[FundamentalData] {code} EM个股信息获取失败: {_e}', flush=True)

            # ── 股息率：EM个股信息无此字段，改用 stock_a_lg_indicator ────
            try:
                _lg = ak.stock_a_lg_indicator(symbol=code)
                if _lg is not None and not _lg.empty:
                    # 返回最近一行，字段含 pe、pb、dividend_yield
                    _last = _lg.iloc[-1]
                    _div = _last.get('股息率') if hasattr(_last, 'get') else None
                    if _div is None:
                        # 尝试列名匹配
                        for _col in _lg.columns:
                            if '股息' in str(_col) or 'dividend' in str(_col).lower():
                                _div = _last[_col]
                                break
                    if _div is not None:
                        result['dividend_yield'] = _to_float(_div) or 0.0
                    print(f'[FundamentalData] {code} lg_indicator列名: {list(_lg.columns)}', flush=True)
            except Exception as _e:
                print(f'[FundamentalData] {code} lg_indicator股息率获取失败: {_e}', flush=True)

        except Exception as _e:
            print(f'[FundamentalData] {code} akshare整体失败: {_e}', flush=True)

        # ── 写入缓存 ─────────────────────────────────────────────────
        if self._cache is not None:
            try:
                self._cache.save_fundamental(code, result)
            except Exception:
                pass

        return result

    def close(self):
        """占位方法，保持接口一致"""
        pass


def _to_float(val) -> float | None:
    try:
        s = str(val).replace('%', '').replace(',', '').strip()
        return float(s)
    except Exception:
        return None
