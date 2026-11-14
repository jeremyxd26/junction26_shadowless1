"""The answer pipeline behind POST /api/ask: plan, run tools, compose, validate, stream, audit.

Design: docs/design/agent-core.md sections 6 to 9 and 11; contract: contracts/api.md section 7.
The pipeline takes its tools from a registry (registry.py, toolset.py) and never names a tool.
The AI model sits behind the two-call interface in model.py (plan, compose).
"""
