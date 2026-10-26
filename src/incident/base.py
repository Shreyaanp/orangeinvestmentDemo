"""Model bases shared by every contract: strict by default, null-tolerant for inputs."""

from pydantic import BaseModel, ConfigDict, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NullTolerant(Strict):
    """Tool arguments: an explicit null means 'not provided'. Unknown fields stay an error, so a
    misnamed argument is reported instead of silently returning the wrong data."""

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data: object) -> object:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


class Lenient(NullTolerant):
    """LLM answers: also ignore fields we did not ask for, rather than discarding the answer."""

    model_config = ConfigDict(extra="ignore")
