"""视觉理解 MCP Server

为不支持视觉的编码模型（如 GLM-5.1）提供图片理解能力。
通过 MCP 工具调用视觉模型 API，将图片识别结果以文本回传给主模型。
"""

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ── 配置管理 ──────────────────────────────────────────────

CONFIG_DIR = Path.home() / ".visual-understand-mcp"
CONFIG_FILE = CONFIG_DIR / "config.json"

# env 变量名 → 配置键的映射
ENV_KEY_MAP = {
    "VISION_API_KEY": "api_key",
    "VISION_API_BASE": "api_base",
    "VISION_MODEL": "model",
    "VISION_TEMPERATURE": "temperature",
    "VISION_MAX_TOKENS": "max_tokens",
    "VISION_TIMEOUT": "timeout",
    "VISION_SYSTEM_PROMPT": "system_prompt",
}

# 高级配置的默认值
DEFAULTS = {
    "temperature": "0.1",
    "max_tokens": "12000",
    "timeout": "120",
    "system_prompt": "你是一个图片分析助手，仅用于理解图片内容。请按以下结构分析图片，根据实际内容调整详细程度：1. **文字内容** — 逐字提取图中所有可见文字，保留原始格式和层级关系。2. **错误信息与代码** — 如果图中包含错误信息或代码片段，必须原样输出，不做任何改写或概括；如果没有则忽略此项。3. **视觉布局与元素** — 描述空间排列、尺寸、颜色及关键元素间的关系。UI 截图请识别组件类型及其状态。4. **数据与指标** — 图表、表格请提取数值、坐标轴、标签、趋势及异常数据点。5. **整体概述** — 概括图片的主题、场景和关键信息，提供完整的上下文理解。不适用的部分跳过。只描述图片中可见的内容，不做推理、猜测或延伸解读。保持精确客观，不推测不可见的内容。",
}


def load_config() -> dict[str, str]:
    """读取配置，env 优先，配置文件次之，最后用默认值。"""
    result = {}

    # 先读配置文件
    if CONFIG_FILE.exists():
        try:
            result = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # env 覆盖配置文件
    for env_key, config_key in ENV_KEY_MAP.items():
        val = os.getenv(env_key, "").strip()
        if val:
            result[config_key] = val

    # 补充高级配置的默认值（仅缺失时）
    for key, default in DEFAULTS.items():
        if key not in result or not result[key]:
            result[key] = default

    return result


def save_config(config: dict[str, str]) -> None:
    """将配置写入本地文件（Web 页面移除后保留，可供外部工具调用）。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_settings() -> dict[str, str]:
    """获取有效的配置，必填项缺失时抛出明确错误。"""
    config = load_config()
    missing = [k for k in ("api_base", "model", "api_key") if not config.get(k)]
    if missing:
        raise RuntimeError(
            "视觉理解 MCP 尚未配置，请在 MCP 配置的 env 中设置："
            + ", ".join("VISION_" + k.upper() for k in missing)
        )
    return config


# ── 图片处理工具函数 ──────────────────────────────────────

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def guess_mime_type(image_path: Path) -> str:
    """根据文件后缀推断图片 MIME 类型。"""
    mime_type, _ = mimetypes.guess_type(str(image_path))
    if mime_type and mime_type.startswith("image/"):
        return mime_type
    suffix_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif", ".bmp": "image/bmp",
    }
    result = suffix_map.get(image_path.suffix.lower())
    if result:
        return result
    raise ValueError(
        f"无法识别图片类型：{image_path.suffix}，"
        f"支持格式：{', '.join(sorted(SUPPORTED_EXTENSIONS))}"
    )


def local_image_to_data_url(image_path: str) -> str:
    """将本地图片转为 data:image/...;base64,... 格式。"""
    path = Path(image_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"图片不存在：{path}")
    if not path.is_file():
        raise ValueError(f"路径不是文件：{path}")
    max_size_mb = 20
    file_size_mb = path.stat().st_size / 1024 / 1024
    if file_size_mb > max_size_mb:
        raise ValueError(f"图片过大：{file_size_mb:.2f} MB，限制为 {max_size_mb} MB")
    mime_type = guess_mime_type(path)
    with path.open("rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def validate_image_url(url: str) -> str:
    """校验图片 URL 格式。"""
    if url.startswith(("http://", "https://", "data:image/")):
        return url
    raise ValueError("image_url 必须是 http/https URL 或 data:image/...;base64,... 格式")


def build_image_urls(
    image_path: str | None = None,
    image_url: str | None = None,
    image_paths: list[str] | None = None,
    image_urls: list[str] | None = None,
) -> list[str]:
    """将各种图片输入统一为 URL 列表。"""
    result: list[str] = []
    if image_path:
        result.append(local_image_to_data_url(image_path))
    if image_paths:
        for p in image_paths:
            result.append(local_image_to_data_url(p))
    if image_url:
        result.append(validate_image_url(image_url))
    if image_urls:
        for u in image_urls:
            result.append(validate_image_url(u))
    if not result:
        raise ValueError("必须至少传入一张图片：image_path / image_url / image_paths / image_urls")
    if len(result) > 6:
        raise ValueError(f"一次最多支持 6 张图片，当前 {len(result)} 张")
    return result


# ── 视觉模型 API 调用 ─────────────────────────────────────

def build_endpoint(api_base: str) -> str:
    """拼接完整的 chat completions 端点地址。"""
    api_base = api_base.rstrip("/")
    if api_base.endswith("/chat/completions"):
        return api_base
    return f"{api_base}/chat/completions"


async def call_vision_api(
    *,
    image_url_values: list[str],
    prompt: str,
    system_prompt: str | None,
    temperature: float,
    max_tokens: int,
) -> str:
    """调用视觉模型 API，返回识别结果文本。"""
    if not prompt.strip():
        raise ValueError("prompt 不能为空")
    if temperature < 0:
        raise ValueError("temperature 不能小于 0")
    if max_tokens <= 0:
        raise ValueError("max_tokens 必须大于 0")

    settings = get_settings()
    endpoint = build_endpoint(settings["api_base"])
    timeout_seconds = float(settings.get("timeout", "120"))

    # 构造 OpenAI Chat Completions 兼容请求体
    messages: list[dict[str, Any]] = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})

    content: list[dict[str, Any]] = []
    for url in image_url_values:
        content.append({"type": "image_url", "image_url": {"url": url}})
    content.append({"type": "text", "text": prompt})
    messages.append({"role": "user", "content": content})

    payload: dict[str, Any] = {
        "model": settings["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {settings['api_key']}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        return f"视觉模型 API 请求失败\n地址：{endpoint}\n模型：{settings['model']}\n错误：{exc}"

    if response.status_code >= 400:
        return (
            f"视觉模型 API 调用失败\n"
            f"HTTP {response.status_code}\n"
            f"地址：{endpoint}\n"
            f"模型：{settings['model']}\n"
            f"响应：{response.text[:500]}"
        )

    try:
        data = response.json()
    except ValueError:
        return f"视觉模型 API 返回非 JSON\nHTTP {response.status_code}\n{response.text[:500]}"

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return f"视觉模型 API 返回格式异常\n{json.dumps(data, ensure_ascii=False)[:500]}"


# ── MCP 工具定义 ──────────────────────────────────────────

mcp = FastMCP("visual-understand")


@mcp.tool()
async def understand_image(
    prompt: str,
    image_path: str | None = None,
    image_url: str | None = None,
    image_paths: list[str] | None = None,
    image_urls: list[str] | None = None,
) -> str:
    """调用视觉模型理解图片，将识别结果以文本返回。

    当用户要求识别、分析、OCR、描述、比较图片或截图时，必须调用此工具。
    这是唯一可以"看到"图片的工具，不要用 Read/cat 等文本工具打开图片文件。

    Args:
        prompt: 图片理解任务描述，如"提取图中文字"、"分析截图中的报错信息"。
        image_path: 单张本地图片路径。
        image_url: 单张网络图片 URL 或 data:image base64 格式。
        image_paths: 多张本地图片路径列表。
        image_urls: 多张网络图片 URL 列表。
    """
    settings = get_settings()
    temperature = float(settings.get("temperature", "0.2"))
    max_tokens = int(settings.get("max_tokens", "12000"))
    system_prompt = settings.get("system_prompt", "")

    image_url_values = build_image_urls(
        image_path=image_path,
        image_url=image_url,
        image_paths=image_paths,
        image_urls=image_urls,
    )
    return await call_vision_api(
        image_url_values=image_url_values,
        prompt=prompt,
        system_prompt=system_prompt or None,
        temperature=temperature,
        max_tokens=max_tokens,
    )


@mcp.resource("vision://config")
def get_vision_config() -> str:
    """查看当前视觉模型配置（API Key 脱敏）。"""
    config = load_config()
    api_key = config.get("api_key", "")
    if api_key and len(api_key) >= 10:
        masked = api_key[:6] + "..." + api_key[-4:]
    else:
        masked = "已设置" if api_key else "未设置"
    return (
        f"API Base: {config.get('api_base', '未设置')}\n"
        f"Model: {config.get('model', '未设置')}\n"
        f"API Key: {masked}\n"
        f"Temperature: {config.get('temperature', '0.2')}\n"
        f"Max Tokens: {config.get('max_tokens', '12000')}\n"
        f"Timeout: {config.get('timeout', '120')}s\n"
    )


def main() -> None:
    """MCP Server 入口。"""
    mcp.run()


if __name__ == "__main__":
    main()
