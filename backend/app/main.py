from fastapi import FastAPI

app = FastAPI(title="Ragidy")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
