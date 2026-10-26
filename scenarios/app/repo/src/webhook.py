"""WhatsApp Cloud API webhook (API Gateway -> Lambda): verify, then enqueue to SQS."""

import hashlib
import hmac
import json
import os

import boto3

sqs = boto3.client("sqs")
QUEUE_URL = os.environ["INBOUND_QUEUE_URL"]
APP_SECRET = os.environ["META_APP_SECRET"].encode()


def handler(event, context):
    body = event["body"]
    sig = event["headers"].get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(APP_SECRET, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return {"statusCode": 401}
    for entry in json.loads(body)["entry"]:
        for change in entry["changes"]:
            for msg in change["value"].get("messages", []):
                sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(msg))
            for status in change["value"].get("statuses", []):
                print(f"status {status['status']} for {status['id']}")
    return {"statusCode": 200}
