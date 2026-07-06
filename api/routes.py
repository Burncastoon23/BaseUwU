"""Route matching helper for the agent registry API server."""

from __future__ import annotations

from typing import Callable


def match_route(
    method: str, path: str, routes: dict
) -> tuple[Callable, dict]:
    """Match method+path against routes dict.

    Routes are strings like "GET /agents", "GET /agents/{id}", "POST /agents/merge".
    Returns (handler_fn, path_params_dict) or raises KeyError if no match.
    Exact matches take priority over parametric matches.
    """
    # Strip trailing slash (except bare "/")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # 1. Exact match first
    exact_key = f"{method} {path}"
    if exact_key in routes:
        return routes[exact_key], {}

    # 2. Parametric match — iterate all route patterns
    path_parts = path.split("/")
    candidates: list[tuple[str, dict]] = []

    for route_key, handler in routes.items():
        route_method, _, route_path = route_key.partition(" ")
        if route_method != method:
            continue
        route_parts = route_path.split("/")
        if len(route_parts) != len(path_parts):
            continue

        params: dict[str, str] = {}
        matched = True
        for rp, pp in zip(route_parts, path_parts):
            if rp.startswith("{") and rp.endswith("}"):
                param_name = rp[1:-1]
                params[param_name] = pp
            elif rp != pp:
                matched = False
                break
        if matched:
            candidates.append((route_key, params))

    if not candidates:
        raise KeyError(f"No route matched: {method} {path}")

    # Prefer routes with fewer parameters (more specific)
    candidates.sort(key=lambda c: sum(
        1 for part in c[0].split("/") if part.startswith("{")
    ))
    best_key, best_params = candidates[0]
    return routes[best_key], best_params
