# Phase B Model Verification Evidence

Date: 2026-11-17
CLI: CodeBuddy v2.143.1 (C:\nvm4w\nodejs\codebuddy)
Auth: API Management Key (ck_g1uq...redacted)
Environment: Windows 10.0.26200, Python 3.14.3

## DeepSeek Flash (#506)

- Product name: DeepSeek Flash
- Verified model ID: `deepseek-v4.1-flash`
- Command: `codebuddy -p --model deepseek-v4.1-flash --output-format json "Reply with exactly: WORKLEDGER_OK"`
- Result: SUCCESS
- Response text: "WORKLEDGER_OK"
- Session ID: 959a31b5-d325-4044-aee6-404e58bda267
- No fallback observed (explicit --model selection)

## HY4 Flash (#507)

- Product name: HY4 Flash
- Verified model ID: `hy4-preview`
- Command: `codebuddy -p --model hy4-preview --output-format json "Reply with exactly: WORKLEDGER_OK"`
- Result: SUCCESS
- Response text: "WORKLEDGER_OK"
- No fallback observed (explicit --model selection)

## Available models (from CLI --help)

hy4-preview, hy3, hy3-x, deepseek-v4.1-flash, glm-5.3, glm-5.3-flash,
glm-5.3-flashx, glm-5.2, glm-5.1, glm-5v-turbo, minimax-m3-pay,
minimax-m2.7, kimi-k3-2, kimi-k2.8-preview, kimi-k2.7, kimi-k2.6,
deepseek-v4-pro, custom-local:deepseek-v4-pro

## Notes

- "HY4 Flash" maps to `hy4-preview` (no separate "hy4-flash" ID exists in CLI v2.143.1)
- Key is passed via CODEBUDDY_API_KEY env var, never logged or displayed
- Both models responded correctly to a deterministic prompt, confirming real inference (not mock)