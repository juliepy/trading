"""
Classic Pivot Level Calculator
===============================
从前一交易日 OHLC 计算经典 Pivot 支撑阻力位。

Usage
-----
python pivot.py <high> <low> <close>
python pivot.py 4622.83 4509.12 4563.54

也可作为模块导入：
    from pivot import calc_pivots
    levels = calc_pivots(4622.83, 4509.12, 4563.54)
"""

from __future__ import annotations
import sys


def calc_pivots(high: float, low: float, close: float) -> dict[str, float]:
    """
    经典 Pivot 公式：
        P  = (H + L + C) / 3
        R1 = 2P - L
        R2 = P + (H - L)
        R3 = R1 + (H - L)
        S1 = 2P - H
        S2 = P - (H - L)
        S3 = S1 - (H - L)
    """
    p = (high + low + close) / 3
    r = high - low
    return {
        "P":  p,
        "R1": 2 * p - low,
        "R2": p + r,
        "R3": 2 * p - low + r,   # R1 + (H - L)
        "S1": 2 * p - high,
        "S2": p - r,
        "S3": 2 * p - high - r,  # S1 - (H - L)
    }


def _fmt(value: float) -> str:
    """Format pivot number consistently."""
    # Use 2 decimals; if integer-like (e.g. for large indices) use commas
    return f"{value:,.2f}"


def print_pivots(high: float, low: float, close: float) -> None:
    levels = calc_pivots(high, low, close)

    print(f"\n{'═'*48}")
    print("  Classic Pivot Levels")
    print(f"  H={_fmt(high)}  L={_fmt(low)}  C={_fmt(close)}")
    print(f"{'═'*48}")
    print(f"  R3  {_fmt(levels['R3']):>12}   ── 强阻力")
    print(f"  R2  {_fmt(levels['R2']):>12}   ── 第二阻力")
    print(f"  R1  {_fmt(levels['R1']):>12}   ── 第一阻力")
    print(f"  {'─'*44}")
    print(f"  P   {_fmt(levels['P']):>12}   ── 平衡位 (Pivot)")
    print(f"  {'─'*44}")
    print(f"  S1  {_fmt(levels['S1']):>12}   ── 第一支撑")
    print(f"  S2  {_fmt(levels['S2']):>12}   ── 第二支撑")
    print(f"  S3  {_fmt(levels['S3']):>12}   ── 强支撑")
    print(f"{'═'*48}")

    # Quick reference string for copy-paste into report
    p = levels["P"]
    r1, s1 = levels["R1"], levels["S1"]
    print(f"\n  报告用快捷格式:")
    print(f"  Pivot {_fmt(p)}  R1 {_fmt(r1)}  S1 {_fmt(s1)}\n")


def main() -> None:
    if len(sys.argv) != 4:
        print(__doc__)
        print("Error: expected exactly 3 arguments: <high> <low> <close>")
        sys.exit(1)

    try:
        high  = float(sys.argv[1])
        low   = float(sys.argv[2])
        close = float(sys.argv[3])
    except ValueError as exc:
        print(f"Error: {exc}  — high, low, close must be numeric")
        sys.exit(1)

    if not (high >= low):
        print("Error: high must be >= low")
        sys.exit(1)

    if not (high >= close >= low):
        # Close outside H-L range is technically possible (e.g. adjusted prices),
        # but worth flagging.
        print(f"Warning: close ({close}) is outside the high-low range ({low}–{high})")

    print_pivots(high, low, close)


if __name__ == "__main__":
    main()
