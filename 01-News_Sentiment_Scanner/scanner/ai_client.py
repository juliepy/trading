"""
scanner/ai_client.py
LLM 客户端初始化 — 支持 GPT 和 DeepSeek

环境变量（写入 .env 或 shell）：
  # GPT
  OPENAI_API_KEY       OpenAI API Key（GPT 必填）
  OPENAI_MODEL         GPT 模型名（可选，默认 gpt-4.1）

  # DeepSeek
  DEEPSEEK_API_KEY     DeepSeek API Key（DeepSeek 必填）
  DEEPSEEK_MODEL       DeepSeek 模型名（可选，默认 deepseek-chat）

  # 统一切换入口
  LLM_MODEL            设置此变量即可切换后端：
                         LLM_MODEL=gpt-4.1            → GPT
                         LLM_MODEL=deepseek-chat      → DeepSeek V3
                         LLM_MODEL=deepseek-reasoner  → DeepSeek R1
"""

import os
from pathlib import Path
from openai import OpenAI

# 加载项目根目录的 .env 文件
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# 配置
_LLM_MODEL = os.environ.get("LLM_MODEL", "")
_GPT_KEY   = os.environ.get("OPENAI_API_KEY", "")
_GPT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1")
_DS_KEY    = os.environ.get("DEEPSEEK_API_KEY", "")
_DS_MODEL  = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


def _resolve() -> tuple:
    """返回 (client, model_name)，根据环境变量自动选择后端"""
    m = _LLM_MODEL.strip()
    if m.lower().startswith("deepseek") or (not m and _DS_KEY):
        model = m if m else _DS_MODEL
        if not _DS_KEY:
            raise RuntimeError("未设置 DEEPSEEK_API_KEY")
        return OpenAI(base_url="https://api.deepseek.com/v1", api_key=_DS_KEY), model
    # 默认 GPT
    model = m if m else _GPT_MODEL
    if not _GPT_KEY:
        raise RuntimeError("未设置 OPENAI_API_KEY")
    return OpenAI(base_url="https://api.openai.com/v1", api_key=_GPT_KEY), model


client, model = _resolve()
