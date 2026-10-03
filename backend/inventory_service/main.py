from fastapi import FastAPI
from strawberry.fastapi import GraphQLRouter
from .schema import schema

app = FastAPI(title="Inventory Service", version="1.0.0")

graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")


@app.get("/health")
def health():
    return {"status": "ok", "service": "inventory-service"}
