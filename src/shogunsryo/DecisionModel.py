from abc import ABC, abstractmethod
from enum import Enum
import json
import copy
import os
import time
import urllib.error
import urllib.request

try:  # only OpenAIModel needs it, and main.py doesn't use that one
    from openai import OpenAI
    from openai.types.chat import ChatCompletionMessageParam
except ImportError:
    OpenAI = None  # type: ignore[assignment,misc]
    ChatCompletionMessageParam = dict  # type: ignore[assignment,misc]
from google.genai import Client as GenAIClient
from google.genai import types
from groq import Groq as GroqClient

type ContentType = str | dict


class STATUS(Enum):
    AVAILABLE = 0
    EXHAUSTED = 1
    TEMPORARILY_DOWN = 2


def _classify(e: BaseException) -> tuple[STATUS, float]:
    """
    How long to leave a model alone after an error: (status, seconds). 0 seconds means "just use
    the next model for this one request". The original marked a model exhausted for the WHOLE
    session after any single error, so one temporary hiccup switched everything off for good.
    """
    msg = f"{type(e).__name__}: {e}".lower()
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    if (code in (401, 403, 404) or "invalid api key" in msg or "permission denied" in msg
            or "model_not_found" in msg or "does not exist" in msg):
        return STATUS.EXHAUSTED, float("inf")  # a bad key or a wrong model name won't fix itself
    if (getattr(e, "rate_headers", {}) or {}).get("x-ratelimit-limit-req-minute") == "0":
        return STATUS.EXHAUSTED, float("inf")  # "0 requests per minute": not available on this plan
    if code == 429 or "429" in msg or "rate limit" in msg or "quota" in msg or "resource_exhausted" in msg:
        wait = getattr(e, "retry_after", None)  # the server may say how long to wait
        if isinstance(wait, (int, float)) and wait > 0:
            return STATUS.EXHAUSTED, min(max(float(wait), 1.0), 300.0)
        return STATUS.EXHAUSTED, 90.0          # rate limited: try again in a minute or two
    if type(e) is RuntimeError:
        return STATUS.TEMPORARILY_DOWN, 0.0    # an empty/odd answer: use the next model this once
    return STATUS.TEMPORARILY_DOWN, 15.0       # network trouble, 503 "high demand", ...




def _strictify(schema: dict) -> dict:
    """Make a JSON schema valid for strict structured outputs:
    every object gets additionalProperties=false and all properties required."""
    schema = copy.deepcopy(schema)

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" or "properties" in node:
            props = node.setdefault("properties", {})
            node["additionalProperties"] = False
            node["required"] = list(props.keys())
            for sub in props.values():
                walk(sub)
        walk(node.get("items"))
        for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
            for sub in node.get(key, []):
                walk(sub)
        for key in ("$defs", "definitions"):
            for sub in node.get(key, {}).values():
                walk(sub)

    walk(schema)
    return schema

class AllModelsFailedError(RuntimeError):
    def __init__(self, errors: list[tuple[str, BaseException]]):
        self.errors = errors
        detail = "; ".join(f"{name}: {type(e).__name__}: {e}" for name, e in errors)
        super().__init__(f"All {len(errors)} models failed. {detail}")

class DecisionModel[C](ABC):          # Python 3.12+ generic syntax
    def __init__(self, client: C, model: str):
        self.client = client
        self.model = model
        self._status = STATUS.AVAILABLE
        self._until = 0.0   # time.monotonic() when a cooldown ends

    @abstractmethod
    def request(self, content: ContentType) -> str: ...

    @abstractmethod
    def setSystemRules(self, prompt: str, schema: dict) -> None: ...

    def _inputifyContent(self, content: ContentType) -> str:
        match content:
            case str():
                return content
            case dict():
                return json.dumps(content, indent=2)
            case _:
                raise NotImplementedError(
                    f"Unhandled content type: {type(content).__name__}"
                )

    @property
    def status(self) -> STATUS:
        # a cooldown ends by itself, so a rate-limited model comes back automatically
        if self._status is not STATUS.AVAILABLE and time.monotonic() >= self._until:
            self._status = STATUS.AVAILABLE
        return self._status

    def setStatus(self, status: STATUS, cooldown: float = 0.0) -> None:
        self._status = status
        self._until = time.monotonic() + cooldown

    def seconds_left(self) -> float:
        """Seconds until a resting model is usable again (inf = never, e.g. a bad key)."""
        return 0.0 if self.status is STATUS.AVAILABLE else max(0.0, self._until - time.monotonic())

class UnifiedDecisionModel:
    def __init__(self, models: list[DecisionModel]):
        self.models = models

    def request(self, content: ContentType) -> str:
        # If every model is resting, wait for the first one to recover instead of giving up
        # (MODEL_MAX_WAIT seconds, default 120). Giving up used to switch the whole bot off.
        give_up_at = time.monotonic() + float(os.environ.get("MODEL_MAX_WAIT", "120") or 0)
        while True:
            errors: list[tuple[str, BaseException]] = []

            for mo in self.models:
                if mo.status is not STATUS.AVAILABLE:
                    errors.append((mo.model, RuntimeError("skipped: cooling down")))
                    continue

                try:
                    res = mo.request(content)
                except Exception as e:
                    errors.append((mo.model, e))
                    status, cooldown = _classify(e)
                    mo.setStatus(status, cooldown)
                    why = f"{type(e).__name__}: {str(e)[:110]}"
                    rest = ("disabled until you fix its key" if cooldown == float("inf")
                            else f"rests {cooldown:.0f}s" if cooldown else "")
                    print(f"WARN: {mo.model} failed ({why})" + (f"; {rest}" if rest else ""))
                    continue

                mo.setStatus(STATUS.AVAILABLE)  # recovered if it was down
                return res

            waits = [mo.seconds_left() for mo in self.models if mo.seconds_left() != float("inf")]
            if waits and time.monotonic() + min(waits) <= give_up_at:
                pause = max(1.0, min(waits))
                print(f"WARN: all models are resting; waiting {pause:.0f}s for one to recover")
                time.sleep(pause)
                continue
            raise AllModelsFailedError(errors)
                    

class GenAIModel(DecisionModel[GenAIClient]):
    def __init__(self, client: GenAIClient, model: str):
        super().__init__(client, model)
        self.config: types.GenerateContentConfig | None = None

    def setSystemRules(self, prompt: str, schema: dict) -> None:
        self.config = types.GenerateContentConfig(
            system_instruction=prompt,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0,
        )

    def request(self, content: ContentType) -> str:
        res = self.client.models.generate_content(
            model=self.model,
            contents=self._inputifyContent(content),
            config=self.config,
        )

        if res.prompt_feedback and res.prompt_feedback.block_reason:
            raise RuntimeError(f"Prompt blocked: {res.prompt_feedback.block_reason}")
        if not res.candidates:
            raise RuntimeError("No candidates in response")

        reason = res.candidates[0].finish_reason
        if reason != types.FinishReason.STOP:
            raise RuntimeError(f"Generation did not finish normally: {reason}")
        if not res.text:
            raise RuntimeError(f"Empty response from model: {reason}")
        return res.text


class OpenAIModel(DecisionModel[OpenAI]):
    def __init__(self, client: OpenAI, model: str):
        super().__init__(client, model)
        self._system_prompt: str | None = None
        self._response_format: dict | None = None

    def setSystemRules(self, prompt: str, schema: dict) -> None:
        self._system_prompt = prompt
        self._response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "schema": schema,
                "strict": True,
            },
        }

    def request(self, content: ContentType) -> str:
        messages: list[ChatCompletionMessageParam] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        messages.append({"role": "user", "content": self._inputifyContent(content)})

        res = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format=self._response_format,  # type: ignore[arg-type]
            temperature=0,
        )

        if not res.choices:
            raise RuntimeError("No choices in response")
        choice = res.choices[0]

        if choice.message.refusal:
            raise RuntimeError(f"Model refused: {choice.message.refusal}")
        if choice.finish_reason != "stop":
            raise RuntimeError(f"Generation did not finish normally: {choice.finish_reason}")
        if not choice.message.content:
            raise RuntimeError(f"Empty response from model: {choice.finish_reason}")
        return choice.message.content


class GroqModel(DecisionModel[GroqClient]):
    def __init__(self, client: GroqClient, model: str, strict: bool = True):
        super().__init__(client, model)
        self._system_prompt: str | None = None
        self._response_format: dict | None = None
        self._strict = strict

    def setSystemRules(self, prompt: str, schema: dict) -> None:
        self._system_prompt = prompt
        self._response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "schema": _strictify(schema) if self._strict else schema,
                "strict": self._strict,
            },
        }

    def request(self, content: ContentType) -> str:
        messages = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        messages.append({"role": "user", "content": self._inputifyContent(content)})

        kwargs = {}
        if self._response_format:
            kwargs["response_format"] = self._response_format

        res = self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=0,
            **kwargs,
        )

        if not res.choices:
            raise RuntimeError("No choices in response")
        choice = res.choices[0]

        if choice.finish_reason != "stop":
            raise RuntimeError(f"Generation did not finish normally: {choice.finish_reason}")
        if not choice.message.content:
            raise RuntimeError(f"Empty response from model: {choice.finish_reason}")
        return choice.message.content


class MistralHTTPError(Exception):
    """An error reply from Mistral. status_code lets _classify() decide how long to rest."""

    def __init__(self, status_code: int, body: str, headers: dict | None = None):
        headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        # the headers that say which limit was hit and when to retry
        self.rate_headers = {k: v for k, v in headers.items() if "limit" in k or "retry" in k or "remaining" in k or "reset" in k}
        extra = f" | headers: {self.rate_headers}" if self.rate_headers else ""
        super().__init__(f"HTTP {status_code}: {body[:200]}{extra}")
        self.status_code = status_code
        self.body = body
        try:
            self.retry_after = float(headers["retry-after"]) if "retry-after" in headers else None
        except ValueError:
            self.retry_after = None


_NOTES_INSTRUCTION = (
    '\n\nFor THIS reply only (this overrides the output rules above): the JSON object also has a "notes" key, '
    'listed first. In "notes", check each claim in one short sentence using the numbers you found '
    '(under 70 words in total), then give claim1, claim2 and claim3 as booleans.'
)


class MistralModel(DecisionModel[None]):
    """
    Mistral's chat API (https://api.mistral.ai/v1/chat/completions), called with the standard
    library only, so no extra package is needed.

    It asks for strict JSON-schema output. If Mistral rejects that request shape (HTTP 400/422)
    it falls back to plain "JSON mode", then to a plain request, and remembers what worked.
    With notes=True the model first writes a short check of each claim (a "notes" field) and then
    answers; that helps models that don't reason on their own, and the free allowance is huge.
    """

    URL = "https://api.mistral.ai/v1/chat/completions"

    def __init__(self, api_key: str, model: str = "mistral-small-latest", notes: bool = True, timeout: float = 45.0):
        super().__init__(None, model)
        self._key = api_key
        self._notes = notes
        self._timeout = timeout
        self._system: str | None = None
        self._schema: dict | None = None
        self._formats = ["json_schema", "json_object", "none"]  # tried in this order
        self.last_notes = ""
        self.last_headers: dict = {}   # rate-limit headers from the last good reply

    def setSystemRules(self, prompt: str, schema: dict) -> None:
        schema = copy.deepcopy(schema)
        if self._notes:
            props = {"notes": {"type": "string"}}
            props.update(schema.get("properties", {}))
            schema["properties"] = props
        self._schema = _strictify(schema)
        self._system = prompt + (_NOTES_INSTRUCTION if self._notes else "")

    def _post(self, body: dict) -> dict:
        req = urllib.request.Request(
            self.URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "ShogunsRyo/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                hdrs = getattr(resp, "headers", None)
                self.last_headers = {str(k).lower(): str(v) for k, v in (hdrs.items() if hdrs else [])
                                     if "limit" in str(k).lower() or "remaining" in str(k).lower()}
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise MistralHTTPError(e.code, e.read().decode("utf-8", "replace"), dict(e.headers.items()) if e.headers else {}) from None

    def request(self, content: ContentType) -> str:
        messages = []
        if self._system:
            messages.append({"role": "system", "content": self._system})
        messages.append({"role": "user", "content": self._inputifyContent(content)})

        data = None
        for fmt in list(self._formats):
            body: dict = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": 600}
            if fmt == "json_schema":
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": self._schema, "strict": True},
                }
            elif fmt == "json_object":
                body["response_format"] = {"type": "json_object"}
            try:
                data = self._post(body)
                break
            except MistralHTTPError as e:
                if e.status_code in (400, 422) and fmt != "none":
                    self._formats = self._formats[self._formats.index(fmt) + 1:]
                    print(f"WARN: Mistral did not accept '{fmt}' output ({e}); trying a simpler request")
                    continue
                raise
        if data is None:
            raise RuntimeError("Mistral gave no usable reply")

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("No choices in response")
        choice = choices[0]
        if choice.get("finish_reason") not in ("stop", None):
            raise RuntimeError(f"Generation did not finish normally: {choice.get('finish_reason')}")
        text = (choice.get("message") or {}).get("content")
        if isinstance(text, list):  # some models return chunks
            text = "".join(c.get("text", "") for c in text if isinstance(c, dict))
        text = (text or "").strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        if not text:
            raise RuntimeError("Empty response from model")
        try:
            obj = json.loads(text)
            claims = {k: obj[k] for k in ("claim1", "claim2", "claim3")}
        except (ValueError, KeyError, TypeError):
            raise RuntimeError(f"Reply was not the expected JSON: {text[:100]!r}") from None
        for k, v in claims.items():  # JSON mode can return "true" as text
            if isinstance(v, str):
                claims[k] = v.strip().lower() == "true"
        self.last_notes = str(obj.get("notes", ""))
        return json.dumps(claims)
