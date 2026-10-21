"""LLM clients (SAP AI Core native SDK) and schema-validated agent execution."""
import copy
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Protocol

from jsonschema import ValidationError

from app.chatbot import tracing
from app.chatbot.config_loader import AgentSpec, ModelSpec, Registry

log = logging.getLogger(__name__)

_STRICT_UNSUPPORTED = {"$schema", "$id", "minLength", "maxLength", "title"}


class AgentOutputError(RuntimeError):
    """Raised when an agent cannot produce output matching its JSON Schema."""

    def __init__(self, agent: str, detail: str):
        super().__init__(f"Agent {agent!r} produced invalid output: {detail}")
        self.agent = agent
        self.detail = detail


class LLMClient(Protocol):
    """Minimal interface every model backend implements (`last_usage()` is optional)."""

    def complete(self, *, system: str, messages: list[dict], schema: dict,
                 generation: dict) -> str | dict:
        """Returns the model's JSON answer (parsed dict or raw text)."""
        ...


def strict_schema(schema: dict) -> dict:
    """Copy of `schema` without keywords OpenAI strict structured outputs rejects."""
    def clean(node, is_properties=False):
        if isinstance(node, dict):
            if is_properties:
                return {k: clean(v) for k, v in node.items()}
            return {k: clean(v, is_properties=(k == "properties"))
                    for k, v in node.items() if k not in _STRICT_UNSUPPORTED}
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node
    return clean(copy.deepcopy(schema))


def parse_json(text: str) -> dict:
    """Parses a JSON object from model text, tolerating code fences or surrounding prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


class _UsageMixin:
    """Token usage of this thread's last call (clients are shared by concurrent tool calls)."""

    def _set_usage(self, input_tokens, output_tokens) -> None:
        if not hasattr(self, "_usage"):
            self._usage = threading.local()
        self._usage.value = (input_tokens, output_tokens)

    def last_usage(self) -> tuple[int | None, int | None]:
        return getattr(getattr(self, "_usage", None), "value", (None, None))


class SapOpenAIClient(_UsageMixin):
    """OpenAI-family deployment on SAP AI Core (chat completions + strict JSON schema)."""

    def __init__(self, proxy_client, model_name: str):
        from gen_ai_hub.proxy.native.openai import OpenAI
        self._client = OpenAI(proxy_client=proxy_client, max_retries=2)
        self.model_name = model_name

    def complete(self, *, system, messages, schema, generation):
        kwargs = {
            "model_name": self.model_name,
            "messages": [{"role": "system", "content": system}, *messages],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": schema.get("title", "output"), "schema": strict_schema(schema), "strict": True}},
            "timeout": generation.get("timeout", 120.0),
        }
        if "max_tokens" in generation:
            kwargs["max_completion_tokens"] = generation["max_tokens"]
        for key in ("reasoning_effort", "temperature"):
            if key in generation:
                kwargs[key] = generation[key]
        resp = self._client.chat.completions.create(**kwargs)
        usage = getattr(resp, "usage", None)
        self._set_usage(getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None))
        return resp.choices[0].message.content or ""


class SapBedrockClient(_UsageMixin):
    """Anthropic (Bedrock Converse) deployment on SAP AI Core.

    Structured output is forced through a single tool whose input schema is the agent schema.
    """

    _TOOL = "emit_output"

    def __init__(self, proxy_client, model_name: str):
        from gen_ai_hub.proxy.native.amazon.clients import Session
        self._client = Session().client(model_name=model_name, proxy_client=proxy_client)
        self.model_name = model_name

    def complete(self, *, system, messages, schema, generation):
        inference = {"maxTokens": generation.get("max_tokens", 4096)}
        if "temperature" in generation:
            inference["temperature"] = generation["temperature"]
        resp = self._client.converse(
            system=[{"text": system}],
            messages=[{"role": m["role"], "content": [{"text": m["content"]}]} for m in messages],
            inferenceConfig=inference,
            toolConfig={
                "tools": [{"toolSpec": {"name": self._TOOL,
                                        "description": "Return the final structured output.",
                                        "inputSchema": {"json": strict_schema(schema)}}}],
                "toolChoice": {"tool": {"name": self._TOOL}},
            },
        )
        usage = resp.get("usage") or {}
        self._set_usage(usage.get("inputTokens"), usage.get("outputTokens"))
        content = resp["output"]["message"]["content"]
        for part in content:
            if "toolUse" in part:
                return part["toolUse"]["input"]
        return "".join(part.get("text", "") for part in content)


def _normalize_url(url: str, suffix: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith(suffix) else url + suffix


def build_sap_clients(settings, registry: Registry) -> dict[str, LLMClient]:
    """Creates one client per model in the registry using explicit AI Core credentials."""
    from gen_ai_hub.proxy.core.proxy_clients import get_proxy_client
    proxy = get_proxy_client(
        "gen-ai-hub",
        base_url=_normalize_url(settings.AICORE_BASE_URL, "/v2"),
        auth_url=_normalize_url(settings.AICORE_AUTH_URL, "/oauth/token"),
        client_id=settings.AICORE_CLIENT_ID,
        client_secret=settings.AICORE_CLIENT_SECRET,
        resource_group=settings.AICORE_RESOURCE_GROUP,
    )
    factories: dict[str, Callable[[ModelSpec], LLMClient]] = {
        "sap_openai": lambda m: SapOpenAIClient(proxy, m.model_name),
        "sap_bedrock": lambda m: SapBedrockClient(proxy, m.model_name),
    }
    return {key: factories[m.provider](m) for key, m in registry.models.items()}


class Agent:
    """Runs one configured agent and guarantees schema-valid output."""

    def __init__(self, spec: AgentSpec, client: LLMClient):
        self.spec = spec
        self.client = client

    @property
    def name(self) -> str:
        return self.spec.name

    def _errors(self, data) -> list[str]:
        return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
                for e in self.spec.validator.iter_errors(data)]

    def run(self, user_content: str, *, history: list[dict] | None = None,
            **prompt_vars) -> dict:
        """Calls the model; on schema violation retries once with the errors fed back.

        Raises `AgentOutputError` when the second attempt is still invalid. Every call is recorded
        in `agent_runs` (see `app.chatbot.tracing`), whatever its outcome.
        """
        system = self.spec.render_prompt(**prompt_vars)
        system += ("\n\nYour entire response must be a single JSON object valid against this "
                   f"JSON Schema:\n{json.dumps(self.spec.schema, ensure_ascii=False)}")
        messages = [*(history or []), {"role": "user", "content": user_content}]
        recorded_input = json.dumps({"history": history, "message": user_content}, ensure_ascii=False) \
            if history else user_content
        started, attempts, tokens = time.perf_counter(), [], [None, None]

        def record(status: str, output: dict | None = None, error: str | None = None) -> None:
            tracing.record_run(agent=self.name, model=getattr(self.client, "model_name", None) or self.spec.model,
                               system_prompt=system, input=recorded_input, output=output, attempts=attempts,
                               status=status, error=error, latency_ms=round((time.perf_counter() - started) * 1000),
                               input_tokens=tokens[0], output_tokens=tokens[1])

        try:
            data, detail = self._attempts(system, messages, attempts, tokens)
        except Exception as e:
            record("error", error=f"{type(e).__name__}: {e}")
            raise
        if data is None:
            record("invalid", error=detail)
            raise AgentOutputError(self.name, detail)
        record("ok", output=data)
        return data

    def _attempts(self, system: str, messages: list[dict], attempts: list, tokens: list) -> tuple[dict | None, str]:
        """At most two model calls; returns (valid output or None, schema errors of the last attempt)."""
        detail = ""
        for attempt in range(2):
            raw = self.client.complete(system=system, messages=messages,
                                       schema=self.spec.schema, generation=self.spec.generation)
            used = getattr(self.client, "last_usage", lambda: (None, None))()
            for i, n in enumerate(used):
                if n is not None:
                    tokens[i] = (tokens[i] or 0) + n
            try:
                data = raw if isinstance(raw, dict) else parse_json(raw)
                errors = self._errors(data)
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                data, errors = None, [f"not valid JSON: {e}"]
            attempts.append({"raw": raw, "errors": errors})
            if not errors:
                return data, ""
            detail = "; ".join(errors[:10])
            log.warning("agent %s attempt %d invalid: %s", self.name, attempt + 1, detail)
            messages = [*messages,
                        {"role": "assistant", "content": raw if isinstance(raw, str) else json.dumps(raw)},
                        {"role": "user", "content": "Your previous response did not match the JSON Schema. "
                                                    f"Errors: {detail}. Return a corrected JSON object only."}]
        return None, detail


def build_agents(registry: Registry, clients: dict[str, LLMClient]) -> dict[str, Agent]:
    """Binds every registered agent to the client of its configured model."""
    return {name: Agent(spec, clients[spec.model]) for name, spec in registry.agents.items()}
