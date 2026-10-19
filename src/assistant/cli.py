"""Terminal-first client for the always-on assistant; HTTP is the application boundary."""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx


HELP = """/help                         查看命令
/files [关键词]               列出或搜索资料
/read 文件路径 | 主题         提交全文阅读（可用资料 ID）
/tasks                        查看任务，退出终端不影响任务
/model [服务商 模型名]        查看或配置主机模型
/rules                        查看阅读规则
/rule 内容                    追加并启用阅读规则
/job 任务ID                   查看结果、章节 ID
/ask 任务ID 章节ID 问题       针对原文小节提问
/notes 任务ID                 保存阅读笔记到独立 Git
/web [literature|files|tasks]  输出可打开的网页工作区地址
/new                          新建对话
/quit                         退出（主机继续工作）
其他输入会发送给云端模型。"""


def load_config(filename):
    path = Path(filename).resolve()
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    for field in ("library", "database"):
        if field in value and not Path(value[field]).is_absolute():
            value[field] = str(path.parent.parent / value[field])
    records = value.get("literature", {}).get("records_root")
    if records and not Path(records).is_absolute():
        value["literature"]["records_root"] = str(path.parent.parent / records)
    return value


class Client:
    def __init__(self, base, token, transport=None):
        parsed = urlparse(base)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("服务地址必须是 HTTP(S) 主机地址，不能包含凭据、查询或片段")
        self.base = base.rstrip("/")
        self.http = httpx.Client(
            timeout=180,
            transport=transport,
            headers={"Authorization": "Bearer " + token},
            follow_redirects=False,
        )

    def close(self):
        self.http.close()

    def request(self, route, method="GET", body=None):
        try:
            response = self.http.request(method, self.base + "/api/" + route, json=body)
        except httpx.HTTPError:
            raise ValueError("无法连接助手主机；请先启动服务，检查 --url 或网络。") from None
        if response.is_error:
            try:
                detail = response.json().get("detail", "请求失败")
            except ValueError:
                detail = "请求失败"
            raise ValueError(str(detail))
        if response.is_redirect:
            raise ValueError("服务返回重定向，未转发访问密钥；请核对 --url")
        return response.json()

    def read(self, reference, topic):
        documents = self.request("documents")
        matches = [doc for doc in documents if reference in {doc["id"], doc["path"]}]
        if not matches:
            matches = [doc for doc in documents if Path(doc["path"]).name == reference]
        if len(matches) != 1:
            raise ValueError("资料不存在或名称重名，请用 /files 查看完整路径或 ID")
        return self.request(
            "literature/jobs",
            "POST",
            {"document_id": matches[0]["id"], "topic": topic, "purpose": "全文阅读"},
        )


def describe_job(job):
    lines = [
        f"{job['id']}  {job['status']}  {job.get('topic', '')}",
        job.get("error") or job.get("progress", ""),
    ]
    result = job.get("result")
    if result and job["kind"] == "read":
        lines.append(result["metadata"]["title"])
        for section in result["sections"]:
            lines.append(f"  {section['id']}  {section['title']}")
        lines.append("使用 /ask 任务ID 章节ID 问题 继续阅读，/notes 任务ID 保存笔记。")
    elif result and job["kind"] == "question":
        for answer in result["answers"]:
            lines.append(answer["answer"])
            lines.extend(f"  [{e['block_id']}] {e['quote']}" for e in answer["evidence"])
    return "\n".join(filter(None, lines))


def handle_command(client, line, session_id, write=print):
    command, _, argument = line.partition(" ")
    argument = argument.strip()
    if command in {"/help", "/h"}:
        write(HELP)
    elif command in {"/quit", "/exit"}:
        return None
    elif command == "/new":
        session_id = client.request("conversations", "POST")["id"]
        write("新对话：" + session_id)
    elif command == "/files":
        docs = client.request("documents")
        for doc in docs:
            if not argument or argument.casefold() in doc["path"].casefold():
                write(doc["id"] + "  " + doc["path"])
    elif command == "/model":
        current = client.request("literature/settings")
        if argument:
            parts = argument.split(maxsplit=1)
            if len(parts) != 2 or parts[0] not in current["providers"]:
                raise ValueError("用法：/model openai|deepseek|kimi 模型名称")
            provider, model = parts
            profile = current["providers"][provider]
            current = client.request(
                "literature/settings",
                "PUT",
                {
                    "provider": provider,
                    "model": model,
                    "base_url": profile["base_url"],
                    "api_mode": profile["api_mode"],
                    "json_mode": True,
                    "max_output_tokens": current["settings"]["max_output_tokens"],
                },
            )
        write(
            current["settings"]["provider"] + " / " + (current["settings"]["model"] or "未配置模型")
        )
        write(
            "已就绪"
            if current["model_status"]["ready"]
            else "主机缺少：" + "、".join(current["model_status"]["missing"])
        )
    elif command in {"/rules", "/rule"}:
        capability = client.request("literature/settings")["capability"]
        if command == "/rule":
            if not argument:
                raise ValueError("用法：/rule 新的阅读规则")
            capability = client.request(
                "literature/rules",
                "PUT",
                {
                    "text": (capability["rules"] + "\n" + argument).strip(),
                    "expected_version": capability["version"],
                },
            )
        write("阅读规则 v" + str(capability["version"]) + "\n" + capability["rules"])
    elif command == "/tasks":
        for job in client.request("literature/jobs"):
            write(
                f"{job['id']}  {job['status']}  {job['topic']}  {job.get('error') or job.get('progress', '')}"
            )
    elif command == "/read":
        reference, _, topic = argument.partition("|")
        reference = reference.strip().strip('"')
        if not reference:
            raise ValueError("用法：/read 文件路径 | 主题")
        write(describe_job(client.read(reference, topic.strip() or "文献阅读")))
    elif command == "/job":
        if not argument:
            raise ValueError("用法：/job 任务ID")
        write(describe_job(client.request("literature/jobs/" + argument)))
    elif command == "/ask":
        parts = argument.split(maxsplit=2)
        if len(parts) != 3:
            raise ValueError("用法：/ask 任务ID 章节ID 问题")
        job, section, text = parts
        write(
            describe_job(
                client.request(
                    f"literature/jobs/{job}/questions/new",
                    "POST",
                    {"section_id": section, "text": text},
                )
            )
        )
    elif command == "/notes":
        if not argument:
            raise ValueError("用法：/notes 任务ID")
        result = client.request(f"literature/jobs/{argument}/notes/save", "POST", {})
        write("已保存：" + result["note_path"])
        write(
            "Git 待处理：" + result["error"]
            if result["version_pending"]
            else "Git：" + result["commit"]
        )
    elif command == "/web":
        workspace = argument or "literature"
        if workspace not in {"literature", "files", "tasks"}:
            raise ValueError("可用工作区：literature、files、tasks")
        write(client.base + "/#" + workspace)
    elif command.startswith("/"):
        raise ValueError("未知命令，使用 /help 查看")
    else:
        reply = client.request(
            f"conversations/{session_id}/messages",
            "POST",
            {"text": line, "request_id": uuid.uuid4().hex},
        )
        write(reply["text"])
        if reply.get("workspace", "none") != "none":
            write("工作区：" + client.base + "/#" + reply["workspace"])
            if reply["workspace"] == "literature":
                write("终端：/files 查看原文；/read 文件路径 | 主题 提交阅读。")
    return session_id


def run_chat(client, session_id=None, message=None, read=input, write=print):
    session = (
        client.request("conversations/" + session_id)
        if session_id
        else client.request("conversations", "POST")
    )
    session_id = session["id"]
    if message:
        handle_command(client, message, session_id, write)
        return
    write("沈轻媞 · /help 查看命令 · 对话 " + session_id)
    for entry in session["messages"][-10:]:
        write(("你：" if entry["role"] == "user" else "沈轻媞：") + entry["text"])
    while True:
        try:
            line = read("你> ").strip()
            if not line:
                continue
            session_id = handle_command(client, line, session_id, write)
            if session_id is None:
                return
        except (EOFError, KeyboardInterrupt):
            write("已退出；主机上的任务继续执行。")
            return
        except ValueError as exc:
            write("错误：" + str(exc))


def main(argv=None):
    parser = argparse.ArgumentParser(description="沈轻媞：serve 启动主机，chat 进入命令行")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["serve", "chat", "read", "tasks", "sessions"],
        default="serve",
    )
    parser.add_argument("reference", nargs="?", help="read 的文件路径或资料 ID")
    parser.add_argument("--config", default="config/local.json")
    parser.add_argument("--url", help="常开助手地址，默认使用本机配置")
    parser.add_argument("--session", help="恢复已有对话 ID")
    parser.add_argument("--message", "-m", help="单次对话消息或斜杠命令")
    parser.add_argument("--topic", default="文献阅读")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config) if Path(args.config).exists() else {}
        if args.command == "serve":
            if not all(field in config for field in ("library", "database", "token")):
                raise ValueError("请先创建 --config 指向的本机配置")
            import uvicorn
            from .app import create_app

            uvicorn.run(
                create_app(config),
                host=config.get("host", "127.0.0.1"),
                port=config.get("port", 8765),
            )
            return
        token = os.environ.get("ASSISTANT_TOKEN") or config.get("token")
        if not token:
            raise ValueError("请在本机环境变量 ASSISTANT_TOKEN 或私人配置中设置访问密钥")
        host = config.get("host", "127.0.0.1")
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        base = args.url or f"http://{host}:{config.get('port', 8765)}"
        client = Client(base, token)
        try:
            if args.command == "chat":
                run_chat(client, args.session, args.message)
            elif args.command == "read":
                if not args.reference:
                    raise ValueError("read 需要文件路径或资料 ID")
                print(describe_job(client.read(args.reference, args.topic)))
            elif args.command == "tasks":
                handle_command(client, "/tasks", "")
            else:
                for session in client.request("conversations"):
                    print(session["id"], session["title"])
        finally:
            client.close()
    except (ValueError, OSError) as exc:
        print("错误：" + str(exc), file=sys.stderr)
        return 1
    return 0
