"""Sender Lambda (SQS trigger): deliver replies through the WhatsApp Cloud API."""

import json
import os

import httpx

GRAPH = f"https://graph.facebook.com/v21.0/{os.environ['PHONE_NUMBER_ID']}/messages"
TOKEN = os.environ["WHATSAPP_TOKEN"]


def handler(event, context):
    for record in event["Records"]:
        reply = json.loads(record["body"])
        resp = httpx.post(
            GRAPH,
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": reply["to"],
                "text": {"body": reply["text"]},
            },
            timeout=10,
        )
        if resp.status_code == 429:
            raise RuntimeError("WhatsApp throughput limit (130429); SQS will retry")
        resp.raise_for_status()
