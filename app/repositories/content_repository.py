"""Data access for posts (published, draft and proposed)."""
from __future__ import annotations

from app.data.storage import get_store
from app.schemas.analytics import Post


def list_posts() -> list[Post]:
    return [Post.model_validate(p) for p in get_store().read()["posts"]]


def get_post(post_id: str) -> Post | None:
    for p in get_store().read()["posts"]:
        if p["id"] == post_id:
            return Post.model_validate(p)
    return None


def next_post_id() -> str:
    posts = get_store().read()["posts"]
    nums = [int(p["id"].split("_")[1]) for p in posts if p["id"].startswith("post_")]
    return f"post_{(max(nums) + 1) if nums else 1:03d}"


def add_post(post: Post) -> Post:
    get_store().update(lambda s: s["posts"].append(post.model_dump(mode="json", exclude={"engagements", "engagement_rate"})))
    return post


def update_post(post_id: str, **changes) -> Post | None:
    def _apply(state: dict):
        for p in state["posts"]:
            if p["id"] == post_id:
                p.update(changes)
                return p
        return None
    row = get_store().update(_apply)
    return Post.model_validate(row) if row else None


def delete_post(post_id: str) -> bool:
    def _apply(state: dict) -> bool:
        before = len(state["posts"])
        state["posts"] = [p for p in state["posts"] if p["id"] != post_id]
        return len(state["posts"]) < before
    return get_store().update(_apply)
