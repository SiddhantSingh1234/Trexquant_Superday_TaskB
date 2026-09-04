"""Shared library for the Alpha Factory dashboard.

Pages import from ``dashboard.lib.*`` only — never from ``src.*`` directly.
The one exception is ``dashboard.lib.engine`` (the compute bridge); two narrow
metadata-only exceptions are ``dashboard.lib.fixtures`` (``src.contracts``) and
``dashboard.lib.flow`` (``src.config``).  See DASHBOARD_PLAN.md Section 0.4.
"""
