"""
Groq chat call with tools, filling a span with tokens, cost and the
rate-limit headers (week11/pipeline._call_groq, extended for tool calling).

Production behaviour:
  - one client per process (connection pool reused; week 7/11 built a new
    client, i.e. a new TLS handshake, on every call);
  - 429: wait retry-after (capped), up to max_retries;
  - 5xx / connection / timeout: short exponential backoff, LLM_TRANSIENT_RETRIES;
  - gpt-oss malformed tool call (tool_use_failed): one retry;
  - anything else raises LLMError, which the agent turns into a clean stop.
"""
import random
import threading
import time

from . import config


class LLMError(RuntimeError):
    pass


_client = None
_client_lock = threading.Lock()


def client():
    global _client
    with _client_lock:
        if _client is None:
            import groq
            _client = groq.Groq(max_retries=0, timeout=60.0)  # our own retries, so waits are logged
        return _client


def chat(messages, sp, tools=None, model=None, reasoning_effort=None, max_retries=5):
    import groq

    model = model or config.AGENT_MODEL
    extra = {}
    if tools:
        extra["tools"] = tools
        extra["tool_choice"] = "auto"
    effort = reasoning_effort if reasoning_effort is not None else config.REASONING_EFFORT
    if effort and "gpt-oss" in model:
        extra["reasoning_effort"] = effort

    rate_retries = transient = tool_retry = 0
    waited = 0.0
    while True:
        try:
            raw = client().chat.completions.with_raw_response.create(
                model=model, messages=messages, temperature=0, **extra)
            break
        except groq.RateLimitError as exc:
            rate_retries += 1
            if rate_retries > max_retries:
                raise LLMError(f"rate limited {rate_retries} times") from exc
            wait = min(float(exc.response.headers.get("retry-after", 10)), 60)
            waited += wait
            time.sleep(wait)
        except (groq.APIConnectionError, groq.APITimeoutError, groq.InternalServerError) as exc:
            transient += 1
            if transient > config.LLM_TRANSIENT_RETRIES:
                raise LLMError(f"{type(exc).__name__} after {transient} attempts") from exc
            wait = (2 ** transient) + random.random()
            waited += wait
            time.sleep(wait)
        except groq.BadRequestError as exc:
            if "tool_use_failed" in str(exc) and tool_retry < 1:
                tool_retry += 1
                continue
            raise LLMError(f"bad request: {str(exc)[:200]}") from exc
        except groq.APIStatusError as exc:
            raise LLMError(f"API error {exc.status_code}: {str(exc)[:200]}") from exc

    resp = raw.parse()
    headers = raw.headers
    usage = resp.usage
    details = getattr(usage, "completion_tokens_details", None)
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(prompt_details, "cached_tokens", 0) or 0

    sp.set_usage(model, usage.prompt_tokens, usage.completion_tokens, cached)
    sp.attrs.update({
        "provider": "groq",
        "reasoning_effort": effort or "default",
        "reasoning_tokens": getattr(details, "reasoning_tokens", None),
        "queue_ms": round((getattr(usage, "queue_time", 0) or 0) * 1000, 1),
        "rate_limit_retries": rate_retries,
        "transient_retries": transient,
        "retry_wait_s": round(waited, 1),
        "ratelimit_limit_tokens_per_min": headers.get("x-ratelimit-limit-tokens"),
        "ratelimit_remaining_tokens": headers.get("x-ratelimit-remaining-tokens"),
        "ratelimit_limit_requests_per_day": headers.get("x-ratelimit-limit-requests"),
        "ratelimit_remaining_requests": headers.get("x-ratelimit-remaining-requests"),
    })
    return resp.choices[0].message
