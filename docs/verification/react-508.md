# #508 ReAct Grounded Q&A and Write Verification

Date: 2026-11-17
CLI: CodeBuddy v2.143.1
MCP: WorkLedger server (12 tools, stdio transport)
Data: 8 work events + 3 todos pre-seeded via #504 validation

## Acceptance Matrix

### Read: search + timeline (both models)

| Model | search_events(q='MCP') | get_pr_timeline | Grounded? |
|-------|------------------------|-----------------|-----------|
| deepseek-v4.1-flash | total=4, correct types | 8 events, correct order | YES |
| hy4-preview | total=4, correct types | 8 events, correct order | YES |

Both models:
- Called MCP tools explicitly (not hallucinated)
- Reported exact counts matching database state
- Listed correct event_type values
- Summarized based only on tool results

### Write: create_todo (both models)

| Model | Title | source_key | Returned ID | Web visible | Dedup |
|-------|-------|-----------|-------------|-------------|-------|
| deepseek-v4.1-flash | DeepSeek ReAct write test | react:deepseek:write:001 | 2 | YES | YES (replay→2) |
| hy4-preview | HY4 ReAct write test | react:hy4:write:001 | 3 | YES | YES (replay→3) |

- Total todo count unchanged after replay (3→3)
- Both todos visible in GET /api/todos
- source_key dedup confirmed for both

### Error handling

- Tools return structured JSON errors with retryable flag
- No partial writes on failure (transactional)
- Models reported tool results faithfully without fabrication

## Conclusion

Both models pass the full acceptance matrix:
1. Grounded Q&A via search + detail tools ✓
2. User-requested todo write with Web visibility ✓
3. Retry dedup (no duplicates) ✓
4. Write result traceable by source_key and ID ✓