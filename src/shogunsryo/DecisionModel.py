from abc import ABC, abstractmethod
from enum import Enum
import json
import copy

from openai import OpenAI
from google.genai import Client as GenAIClient
from google.genai import types
from openai.types.chat import ChatCompletionMessageParam
from groq import Groq as GroqClient

type ContentType = str | dict


class STATUS(Enum):
    AVAILABLE = 0
    EXHAUSTED = 1
    TEMPORARILY_DOWN = 2




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
        return self._status

    def setStatus(self, status: STATUS) -> None:
        self._status = status

class UnifiedDecisionModel:
    def __init__(self, models: list[DecisionModel]):
        self.models = models

    def request(self, content: ContentType) -> str:
        errors: list[tuple[str, BaseException]] = []

        for mo in self.models:
            if mo.status is STATUS.EXHAUSTED:
                errors.append((mo.model, RuntimeError("skipped: exhausted")))
                continue

            try:
                res = mo.request(content)
            except Exception as e:
                errors.append((mo.model, e))
                # TODO: classify temporarily down vs exhausted.
                # rn it sets it to exhausted, disabling model for the sesh
                if mo.status is STATUS.AVAILABLE:
                    mo.setStatus(STATUS.EXHAUSTED)
                continue

            mo.setStatus(STATUS.AVAILABLE)  # recovered if it was down
            return res

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
