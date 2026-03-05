# Draft: ChatGPT API Error Investigation

## Requirements (confirmed)
- User reports "一直提示chatgpt api出错" (continuously getting ChatGPT API errors)
- User asks "还有额度吗？" (is there still quota/balance?)
- User states "我只需要使用chatgpt codex" (I only need to use ChatGPT Codex)

## Technical Decisions
- Need to investigate current OpenAI API configuration and usage
- Need to clarify what "chatgpt codex" means (likely refers to Codex model for code generation)

## Research Findings
- Project contains multiple LLM integration points:
  - `vision_comparison.py`: `call_chatgpt()` function using OPENAI_API_KEY
  - `gcc_evolution/config.py`: `llm_api_key`, `llm_api_base` configuration
  - `gcc_evolution/llm_client.py`: LLM client supporting multiple providers
- System appears to support multiple LLM providers (OpenAI, Anthropic, DeepSeek)

## Open Questions
1. Which specific API endpoint is failing?
2. What error message is being shown?
3. Is this related to quota/balance or authentication issues?
4. Does user want to switch from ChatGPT to Codex model specifically?
5. What is the current LLM provider configuration?

## Scope Boundaries
- INCLUDE: Diagnosing API error, checking configuration, suggesting fixes
- EXCLUDE: Implementing code changes (will create work plan if needed)