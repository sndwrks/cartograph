from fastapi import APIRouter, FastAPI

from cartograph.api.routers import agents, graph, ingest, kb, messages, search


def create_app() -> FastAPI:
    app = FastAPI(title="Cartograph API")

    router = APIRouter(prefix="/api/v1")

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    router.include_router(graph.router)
    router.include_router(search.router)
    router.include_router(kb.router)
    router.include_router(agents.router)
    router.include_router(messages.router)
    router.include_router(ingest.router)

    app.include_router(router)
    return app


app = create_app()
