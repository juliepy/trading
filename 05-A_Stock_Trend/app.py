"""
A 股 SuperTrend Web UI — Flask 前端
"""

import os
import sys
import json
import queue
import threading
import subprocess
from flask import Flask, render_template, Response, jsonify, send_from_directory

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(_ROOT, "templates"))

_state = {"running": False, "log_queue": queue.Queue()}


def _period_from_csv(label: str) -> str:
    """从 data/{sym}_{tf}.csv 推断回测区间（兼容旧版 results_summary）。"""
    parts = [p.strip() for p in label.split("|")]
    if len(parts) < 3:
        return ""
    sym = parts[1].split()[0] if parts[1].split() else ""
    tf = parts[2].strip()
    if not sym or not tf:
        return ""
    csv_path = os.path.join(_ROOT, "data", f"{sym}_{tf}.csv")
    if not os.path.isfile(csv_path):
        return ""
    try:
        import pandas as pd
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        if df.empty:
            return ""
        idx = pd.to_datetime(df.index)
        return f"{idx.min().strftime('%Y-%m-%d')} ~ {idx.max().strftime('%Y-%m-%d')}"
    except Exception:
        return ""


def _parse_results_md() -> list[dict]:
    md_path = os.path.join(_ROOT, "results", "results_summary.md")
    if not os.path.exists(md_path):
        return []
    rows = []
    with open(md_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|") or line.startswith("|---|") or line.startswith("| 策略"):
                continue
            parts = [p.strip() for p in line.strip("|").split("|")]
            # label 含两个 |，拆出后占 3 列；新版含「回测区间」列
            if len(parts) >= 10 and "~" in parts[3]:
                label = " | ".join(parts[0:3])
                period = parts[3]
                rows.append({
                    "label":         label,
                    "period":        period,
                    "total_return":  parts[4],
                    "annual_return": parts[5],
                    "max_drawdown":  parts[6],
                    "win_rate":      parts[7],
                    "num_trades":    parts[8],
                    "sharpe":        parts[9],
                })
            elif len(parts) >= 9:
                label = " | ".join(parts[0:3])
                rows.append({
                    "label":         label,
                    "period":        _period_from_csv(label),
                    "total_return":  parts[3],
                    "annual_return": parts[4],
                    "max_drawdown":  parts[5],
                    "win_rate":      parts[6],
                    "num_trades":    parts[7],
                    "sharpe":        parts[8],
                })
            elif len(parts) >= 7:
                label = parts[0]
                rows.append({
                    "label":         label,
                    "period":        _period_from_csv(label),
                    "total_return":  parts[1],
                    "annual_return": parts[2],
                    "max_drawdown":  parts[3],
                    "win_rate":      parts[4],
                    "num_trades":    parts[5],
                    "sharpe":        parts[6],
                })
    return rows


def _list_images(folder: str) -> list[str]:
    d = os.path.join(_ROOT, folder)
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.lower().endswith(".png"))


def _ensure_charts() -> None:
    """启动 Web UI 时，若 charts/ 为空但 data/ 有 CSV，自动生成 K 线图。"""
    if _list_images("charts"):
        return
    data_dir = os.path.join(_ROOT, "data")
    if not os.path.isdir(data_dir):
        return
    if not any(f.endswith(".csv") for f in os.listdir(data_dir)):
        return
    print("[启动] charts/ 为空，正在生成 K 线图 …")
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    subprocess.run(
        [sys.executable, "-u", os.path.join(_ROOT, "run.py"), "--charts"],
        cwd=_ROOT, env=env, check=False,
    )


@app.route("/")
def index():
    return render_template(
        "index.html",
        results=_parse_results_md(),
        charts=_list_images("charts"),
        eq_plots=_list_images("results"),
        running=_state["running"],
    )


@app.route("/run", methods=["POST"])
def run_backtest():
    if _state["running"]:
        return jsonify({"status": "already_running"})

    while not _state["log_queue"].empty():
        try:
            _state["log_queue"].get_nowait()
        except queue.Empty:
            break

    _state["running"] = True

    def worker():
        try:
            cmd = [sys.executable, "-u", os.path.join(_ROOT, "run.py"), "--plot", "--charts"]
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONUNBUFFERED"] = "1"
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", cwd=_ROOT, env=env,
            )
            for line in proc.stdout:
                _state["log_queue"].put(line.rstrip("\n"))
            proc.wait()
            if proc.returncode == 0:
                _state["log_queue"].put("__DONE__")
            else:
                _state["log_queue"].put(f"__ERROR__ exit code {proc.returncode}")
        except Exception as exc:
            _state["log_queue"].put(f"__ERROR__ {exc}")
        finally:
            _state["running"] = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/stream")
def stream():
    def generate():
        idle = 0
        while True:
            try:
                line = _state["log_queue"].get(timeout=5)
                idle = 0
                yield f"data: {json.dumps({'line': line}, ensure_ascii=False)}\n\n"
                if line.startswith("__DONE__") or line.startswith("__ERROR__"):
                    break
            except queue.Empty:
                idle += 5
                yield ": keepalive\n\n"
                if idle >= 120:
                    yield 'data: {"line": "__TIMEOUT__"}\n\n'
                    break

    return Response(
        generate(), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/status")
def api_status():
    return jsonify({
        "running":  _state["running"],
        "results":  _parse_results_md(),
        "charts":   _list_images("charts"),
        "eq_plots": _list_images("results"),
    })


@app.route("/charts/<path:filename>")
def serve_chart(filename):
    return send_from_directory(os.path.join(_ROOT, "charts"), filename)


@app.route("/results/<path:filename>")
def serve_result(filename):
    return send_from_directory(os.path.join(_ROOT, "results"), filename)


if __name__ == "__main__":
    _ensure_charts()
    print("=" * 50)
    print("  A 股 SuperTrend  →  http://127.0.0.1:5001")
    print("=" * 50)
    app.run(debug=False, host="0.0.0.0", port=5001, threaded=True)
