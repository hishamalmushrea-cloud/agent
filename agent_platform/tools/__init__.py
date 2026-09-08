"""Built-in tool providers.

Each module exports ``ALL_TOOLS`` — a list of Tool subclasses — which
``ToolRegistry.register_all`` registers idempotently.
"""
from __future__ import annotations
