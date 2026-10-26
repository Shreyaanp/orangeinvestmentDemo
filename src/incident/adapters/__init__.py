"""Adapters that pull real infrastructure data into the same typed Dataset the simulator makes.

Runtime agents never import this package; ingestion is a separate step.
Every item an adapter returns carries `source` and `url` so a human can verify it in one click.
"""
