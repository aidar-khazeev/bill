from typing import Any
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import JSON


class Base(AsyncAttrs, DeclarativeBase):
    type_annotation_map = {
        dict[str, Any]: JSON
    }
