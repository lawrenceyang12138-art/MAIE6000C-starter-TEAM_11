"""Search-owned multi-vector AI wire contract; shared dense schemas stay unchanged."""

from typing import Literal

from pydantic import BaseModel, Field

from services.search.text import TOKEN_DIMENSIONS


class TokenEmbeddingResponse(BaseModel):
    model: str
    dimensions: int = Field(gt=0)
    representation: Literal["token_multivector"]
    scoring: Literal["maxsim_mean"]
    vectors: list[list[list[float]]]

    @classmethod
    def encoded(cls, model: str, vectors: list[list[list[float]]]) -> "TokenEmbeddingResponse":
        return cls(model=model, dimensions=TOKEN_DIMENSIONS, representation="token_multivector",
                   scoring="maxsim_mean", vectors=vectors)
