# orange-assistant

WhatsApp AI banker. API Gateway -> `webhook` Lambda -> SQS `inbound` -> `worker` Lambda
(Redis session, LLM gateway, tools: portfolio/RDS, broker, AA) -> SQS `outbound` -> `sender`
Lambda -> WhatsApp Cloud API. Deployed by GitHub Actions (`.github/workflows/deploy.yml`) with SAM.
