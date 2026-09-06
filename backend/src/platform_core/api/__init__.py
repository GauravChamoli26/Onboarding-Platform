"""
HTTP layer.

    app.py           application factory and lifespan
    middleware.py    correlation IDs and tenant resolution
    dependencies.py  session and tenant dependencies for route handlers
    errors.py        exception handlers that never leak internals or PII
    routes.py        health checks and the feature-flag endpoint

Domain routes live with their modules under src/modules/ from Phase 2 onward.
"""
