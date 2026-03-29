# Backend Structure

This backend is organized by responsibility to keep the CV pipeline, API, and realtime updates cleanly separated.

## Folders
- api: FastAPI routes and request/response schemas
- models: data models and domain objects
- services: CV pipeline, Claude integration, business logic
- ws: WebSocket handlers and realtime broadcast
- config: environment and config templates
- scripts: dev helpers (seed, run, smoke tests)

