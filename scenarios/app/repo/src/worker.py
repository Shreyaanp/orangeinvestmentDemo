"""Worker Lambda (SQS trigger): one user message -> session -> LLM with tools -> reply."""

import json
import os

import boto3

from src import llm, session
from src.tools import aa, broker, portfolio

CONFIG = json.load(open("config/app.json"))
sqs = boto3.client("sqs")
OUTBOUND_URL = os.environ["OUTBOUND_QUEUE_URL"]
TOOLS = {"portfolio": portfolio.fetch, "broker": broker.order_status, "aa": aa.refresh}


def parse_message(msg):
    if msg["type"] == "text":
        return msg["text"]["body"]
    if msg["type"] == "interactive":
        return msg["interactive"]["button_reply"]["title"]
    return "[unsupported message type]"


def handle(msg):
    text = parse_message(msg)
    ctx = session.load(msg["from"], ttl_s=CONFIG["session"]["ttl_s"])
    plan = llm.plan(text, ctx, tools=list(TOOLS))
    results = {}
    for name in plan.tools:
        timeout = CONFIG["tools"][name]["timeout_s"]
        try:
            results[name] = TOOLS[name](msg["from"], timeout=timeout)
        except Exception as exc:  # the model is told about the failure, see prompts/answer.txt
            print(f"tool {name} failed for {msg['id']}: {exc}")
            results[name] = {"error": str(exc)}
    answer = llm.answer(text, ctx, results, prompt=CONFIG["llm"]["prompt_version"])
    session.save(msg["from"], ctx, results)
    sqs.send_message(
        QueueUrl=OUTBOUND_URL, MessageBody=json.dumps({"to": msg["from"], "text": answer})
    )


def handler(event, context):
    for record in event["Records"]:  # batch size 1: a failure returns only this message to SQS
        handle(json.loads(record["body"]))
