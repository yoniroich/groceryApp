from pydantic import BaseModel, Field


class NewMasterProduct(BaseModel):
    name: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)


class ListItemIn(BaseModel):
    product_name: str
    category: str
    quantity: str = "1"


class AddItemsRequest(BaseModel):
    items: list[ListItemIn]


class UpdateListItemRequest(BaseModel):
    quantity: str | None = None
    is_bought: bool | None = None


class MergeRecipeSessionRequest(BaseModel):
    # indices (or names) of items the user left checked, with possibly
    # edited quantities — the web UI sends back the final edited list
    items: list[ListItemIn]
