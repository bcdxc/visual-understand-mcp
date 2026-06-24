# 视觉理解 MCP Server

为不支持视觉的编码模型提供图片理解能力。

## 原理

编码模型（如 GLM-5.1）遇到图片时，自动调用 MCP 工具 `understand_image`，由视觉模型完成图片识别，结果以文本回传给编码模型继续推理。无需切换模型，上下文不中断。

```
用户粘贴截图 → 编码模型调用 understand_image → 视觉模型识别 → 文字描述回传 → 继续编码
```

## 安装方式一：通过 PyPI / uvx 使用（推荐）

MCP 配置示例：

```json
{
  "mcpServers": {
    "visual-understand": {
      "command": "uvx",
      "args": ["visual-understand-mcp"],
      "env": {
        "VISION_API_BASE": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "VISION_MODEL": "qwen-vl-max",
        "VISION_API_KEY": "sk-xxx"
      }
    }
  }
}
```

## 安装方式二：本地源码运行

```json
{
  "mcpServers": {
    "visual-understand": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/visual-understand-mcp",
        "run", "visual-understand-mcp"
      ],
      "env": {
        "VISION_API_BASE": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "VISION_MODEL": "qwen-vl-max",
        "VISION_API_KEY": "sk-xxx"
      }
    }
  }
}
```

## 配置项

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VISION_API_BASE` | 视觉模型 API 地址 | 无（必填） |
| `VISION_MODEL` | 视觉模型名称 | 无（必填） |
| `VISION_API_KEY` | 视觉模型密钥 | 无（必填） |
| `VISION_TEMPERATURE` | 输出随机性 | `0.1` |
| `VISION_MAX_TOKENS` | 最大输出长度 | `12000` |
| `VISION_TIMEOUT` | 请求超时（秒） | `120` |
| `VISION_SYSTEM_PROMPT` | 视觉模型系统提示词 | 见下方 |

前三个必填，其余可选。配置也可写入 `~/.visual-understand-mcp/config.json`，env 优先级更高。

默认系统提示词：

> 你是一个图片分析助手。请按以下结构分析图片，根据实际内容调整详细程度：1. **文字内容** — 逐字提取图中所有可见文字，保留原始格式和层级关系，错误信息和代码片段原样输出。2. **视觉布局与元素** — 描述空间排列、尺寸、颜色及关键元素间的关系。UI 截图请识别组件类型及其状态。3. **数据与指标** — 图表、表格请提取数值、坐标轴、标签、趋势及异常数据点。4. **整体概述** — 概括图片的主题、场景和关键信息，提供完整的上下文理解。不适用的部分跳过。保持精确客观，不推测不可见的内容。

## 建议写入 CLAUDE.md

```markdown
进行图片识别任务时，使用 visual-understand MCP 的 understand_image 工具。
```

## 本地调试

```bash
uv run mcp dev src/visual_understand_mcp/server.py
```

## License

MIT
