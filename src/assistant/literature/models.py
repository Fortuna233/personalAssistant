"""Model gateway: Responses for OpenAI, Chat Completions for compatible providers."""

import hashlib
import json
import os
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_mode": "responses",
        "key_env": "OPENAI_API_KEY",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_mode": "chat",
        "key_env": "DEEPSEEK_API_KEY",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "api_mode": "chat",
        "key_env": "MOONSHOT_API_KEY",
    },
    "compatible": {"base_url": "", "api_mode": "chat", "key_env": "LITERATURE_API_KEY"},
}


def model_settings(value):
    provider = value.get("provider", "openai")
    if provider not in PROVIDERS:
        raise ValueError("不支持的模型服务")
    defaults = PROVIDERS[provider]
    result = {
        "provider": provider,
        "model": value.get("model", "").strip(),
        "base_url": value.get("base_url") or defaults["base_url"],
        "api_mode": value.get("api_mode") or defaults["api_mode"],
        "key_env": defaults["key_env"],
        "json_mode": bool(value.get("json_mode", True)),
        "max_output_tokens": int(value.get("max_output_tokens", 6000)),
    }
    if result["api_mode"] not in {"responses", "chat"}:
        raise ValueError("接口类型需为 responses 或 chat")
    if not 1000 <= result["max_output_tokens"] <= 16000:
        raise ValueError("输出上限须在 1000–16000 tokens 之间")
    if result["base_url"]:
        url = urlparse(result["base_url"])
        if (
            (
                url.scheme != "https"
                and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"})
            )
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("服务地址必须为 HTTPS（本机测试除外），且不能含凭据、查询或片段")
        result["base_url"] = result["base_url"].rstrip("/")
    return result


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class ModelGateway:
    def __init__(self, transport=None):
        self.transport = transport

    def readiness(self, settings):
        missing = []
        if not settings["model"]:
            missing.append("模型名称")
        if not settings["base_url"]:
            missing.append("服务地址")
        if not os.environ.get(settings["key_env"]):
            missing.append(settings["key_env"] + " 环境变量")
        return {"ready": not missing, "missing": missing}

    def generate(self, settings, instructions, payload, contract):
        readiness = self.readiness(settings)
        if not readiness["ready"]:
            raise ValueError("请配置：" + "、".join(readiness["missing"]))
        user = json.dumps(payload, ensure_ascii=False)
        schema_note = (
            "\n只返回 JSON，不加 Markdown 围栏。JSON 必须符合以下 schema：\n"
            + json.dumps(contract.model_json_schema(), ensure_ascii=False)
        )
        if settings["api_mode"] == "responses":
            route = "/responses"
            body = {
                "model": settings["model"],
                "instructions": instructions + schema_note,
                "input": user,
                "max_output_tokens": settings["max_output_tokens"],
                "store": False,
            }
            if settings["json_mode"]:
                body["text"] = {"format": {"type": "json_object"}}
        else:
            route = "/chat/completions"
            body = {
                "model": settings["model"],
                "messages": [
                    {"role": "system", "content": instructions + schema_note},
                    {"role": "user", "content": user},
                ],
                "max_tokens": settings["max_output_tokens"],
            }
            if settings["json_mode"]:
                body["response_format"] = {"type": "json_object"}
        try:
            with httpx.Client(
                timeout=180, follow_redirects=False, transport=self.transport
            ) as client:
                response = client.post(
                    settings["base_url"] + route,
                    json=body,
                    headers={"Authorization": "Bearer " + os.environ[settings["key_env"]]},
                )
                if response.status_code >= 300:
                    # Never persist response bodies/headers, which may echo credentials or private text.
                    raise ValueError(
                        f"模型服务返回 HTTP {response.status_code}；请检查配置或额度后重试"
                    )
                result = response.json()
            if settings["api_mode"] == "responses":
                if result.get("status") not in {None, "completed"}:
                    raise ValueError("模型输出不完整，未接受本步骤结果")
                text = "".join(
                    part.get("text", "")
                    for item in result.get("output", [])
                    for part in item.get("content", [])
                    if part.get("type") == "output_text"
                )
            else:
                choice = result["choices"][0]
                if choice.get("finish_reason") not in {None, "stop"}:
                    raise ValueError("模型输出被截断或拒绝，未接受本步骤结果")
                text = choice["message"]["content"]
            usage = result.get("usage", {})
            return contract.model_validate_json(text), usage
        except (httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError, ValidationError):
            raise ValueError("模型连接或响应格式异常，未接受本步骤结果；可重试") from None
