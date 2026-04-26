# X Tweet Screenshot MCP

Python stdio MCP server that searches X/Twitter with OpenRouter `x-ai/grok-4.1-fast`, extracts tweet links, opens each tweet with Playwright, saves screenshots, and returns Grok text plus screenshot paths.

The returned `tweets[].text` is designed to be a Simplified Chinese summary, while screenshots keep the original post content unchanged. The search prompt also prioritizes high-signal, important updates within the requested domain instead of routine chatter.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[test]"
playwright install chromium
$env:OPENROUTER_API_KEY="your_openrouter_key"
```

You can also put the key in a local `.env` file:

```text
OPENROUTER_API_KEY=your_openrouter_key
```

## Run

```powershell
x-tweet-screenshot-mcp
```

Or:

```powershell
python -m x_tweet_screenshot_mcp
```

## MCP Client Config

Example stdio configuration:

```json
{
  "mcpServers": {
    "x-tweet-screenshot": {
      "command": "python",
      "args": ["-m", "x_tweet_screenshot_mcp"],
      "env": {
        "OPENROUTER_API_KEY": "your_openrouter_key"
      }
    }
  }
}
```

## Tool

`search_x_tweets_with_screenshots`

Inputs:

- `query` string, required: X search topic.
- `output_dir` string, required: folder for screenshots.
- `max_results` integer, default `5`.
- `days` integer, default `1`.
- `allowed_x_handles` string array, optional, max 10.
- `excluded_x_handles` string array, optional, max 10.
- `include_images` boolean, default `false`.
- `include_videos` boolean, default `false`.
- `create_run_subdir` boolean, default `true`.

Output includes:

- `query`, `model`, `output_dir`, `raw_grok_content`.
- `tweets[]` with `text`, `url`, `author_handle`, `posted_at`, `screenshot_path`, `screenshot_status`, `error`.
- `tweets[].text` should be a Chinese summary of the post content, and `importance_reason` explains why the post matters in the requested domain.
- `usage`, if returned by OpenRouter.

## Notes

- Screenshots are best effort. X login walls, rate limits, CAPTCHA, or unavailable posts are returned per tweet as `screenshot_status: "failed"` instead of failing the whole tool.
- The server first uses OpenRouter `openrouter:web_search`, then falls back to the deprecated `web` plugin, then to prompt-only search instructions if needed.
- Tweet URLs are normalized to `https://x.com/<handle>/status/<id>` before screenshotting.

## Tests

```powershell
pytest
```
