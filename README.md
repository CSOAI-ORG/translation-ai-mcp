# Translation AI MCP

> Language tools - text translation, language detection, grammar checking, tone adjustment, localization validation

Built by **MEOK AI Labs** | [meok.ai](https://meok.ai)

## Features

| Tool | Description |
|------|-------------|
| `translate_text` | See tool docstring for details |
| `detect_language` | See tool docstring for details |
| `check_grammar` | See tool docstring for details |
| `adjust_tone` | See tool docstring for details |
| `validate_localization` | See tool docstring for details |

## Installation

```bash
pip install mcp
```

## Usage

### As an MCP Server

```bash
python server.py
```

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "translation-ai-mcp": {
      "command": "python",
      "args": ["/path/to/translation-ai-mcp/server.py"]
    }
  }
}
```

## Rate Limits

Free tier includes **30-50 calls per tool per day**. Upgrade at [meok.ai/pricing](https://meok.ai/pricing) for unlimited access.

## License

MIT License - see [LICENSE](LICENSE) for details.

---

Built with FastMCP by MEOK AI Labs
