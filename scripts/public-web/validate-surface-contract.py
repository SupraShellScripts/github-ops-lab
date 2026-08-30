#!/usr/bin/env python3
"""
Validate a generated static public surface against a project-owned machine contract.

This validator is intentionally dependency-free and read-only. It covers cheap,
deterministic checks that do not require browser execution:
- contract/model structural validity and required-state reachability;
- rendered link/action classification against the expected graph;
- project-base-path containment;
- canonical/title/noindex consistency;
- sitemap/robots/discovery consistency.

Browser execution of JS-only transitions remains a consumer-owned Playwright concern.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
import xml.etree.ElementTree as ET


SCHEMA = "public-surface-contract/1"


class ValidationError(Exception):
    pass


@dataclass(frozen=True)
class Route:
    id: str
    path: str
    title: str
    indexable: bool
    required: bool
    terminal: bool
    lastmod: str | None


class SurfaceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self._in_title = False
        self.states: list[str] = []
        self.canonicals: list[str] = []
        self.describedby: list[str] = []
        self.meta_robots: list[str] = []
        self.actions: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): v for k, v in attrs}
        if tag.lower() == "title":
            self._in_title = True
        state = a.get("data-surface-state")
        if state:
            self.states.append(state)
        if tag.lower() == "link":
            rel = set((a.get("rel") or "").lower().split())
            href = a.get("href")
            if href and "canonical" in rel:
                self.canonicals.append(href)
            if href and "describedby" in rel:
                self.describedby.append(href)
        if tag.lower() == "meta" and (a.get("name") or "").lower() in {"robots", "googlebot"}:
            if a.get("content"):
                self.meta_robots.append(a["content"] or "")
        if tag.lower() in {"a", "button"}:
            action = a.get("data-surface-action")
            href = a.get("href") if tag.lower() == "a" else None
            self.actions.append(
                {
                    "tag": tag.lower(),
                    "action": action,
                    "href": href,
                    "handoff": a.get("data-surface-handoff"),
                }
            )

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def normalize_route_path(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValidationError(f"route path must start with '/': {value!r}")
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValidationError(f"route path must be a path only: {value!r}")
    raw = re.sub(r"/+", "/", parsed.path)
    norm = posixpath.normpath(raw)
    if not norm.startswith("/"):
        norm = "/" + norm
    if raw.endswith("/") and norm != "/":
        norm += "/"
    if ".." in Path(norm).parts:
        raise ValidationError(f"route path may not contain '..': {value!r}")
    return norm


def normalize_base_url(value: str) -> str:
    p = urlparse(value)
    if p.scheme not in {"http", "https"} or not p.netloc:
        raise ValidationError("production_base_url must be an absolute http(s) URL")
    if p.query or p.fragment:
        raise ValidationError("production_base_url may not contain query/fragment")
    path = p.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urlunparse((p.scheme, p.netloc, path, "", "", ""))


def route_url(base_url: str, route_path: str) -> str:
    rel = route_path.lstrip("/")
    return urljoin(base_url, rel)


def local_file_for_route(site_dir: Path, route_path: str) -> Path:
    rel = route_path.lstrip("/")
    if not rel:
        return site_dir / "index.html"
    if route_path.endswith("/"):
        return site_dir / rel / "index.html"
    suffix = Path(rel).suffix.lower()
    if suffix in {".html", ".htm"}:
        return site_dir / rel
    return site_dir / rel / "index.html"


def parse_html(path: Path) -> SurfaceHTMLParser:
    parser = SurfaceHTMLParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser


def load_contract(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError("contract root must be an object")
    if value.get("schema") != SCHEMA:
        raise ValidationError(f"contract schema must be {SCHEMA!r}")
    return value


def build_routes(contract: dict[str, Any]) -> tuple[list[Route], dict[str, Route], dict[str, Route]]:
    raw_routes = contract.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValidationError("routes must be a non-empty array")
    routes: list[Route] = []
    by_id: dict[str, Route] = {}
    by_path: dict[str, Route] = {}
    for raw in raw_routes:
        if not isinstance(raw, dict):
            raise ValidationError("each route must be an object")
        rid = raw.get("id")
        title = raw.get("title")
        if not isinstance(rid, str) or not rid:
            raise ValidationError("each route requires non-empty string id")
        if not isinstance(title, str) or not title.strip():
            raise ValidationError(f"route {rid!r} requires a non-empty expected title")
        path = normalize_route_path(raw.get("path"))
        if rid in by_id:
            raise ValidationError(f"duplicate route id: {rid}")
        if path in by_path:
            raise ValidationError(f"duplicate route path: {path}")
        route = Route(
            id=rid,
            path=path,
            title=title.strip(),
            indexable=bool(raw.get("indexable", True)),
            required=bool(raw.get("required", True)),
            terminal=bool(raw.get("terminal", False)),
            lastmod=raw.get("lastmod"),
        )
        if route.lastmod is not None and not isinstance(route.lastmod, str):
            raise ValidationError(f"route {rid!r} lastmod must be a string when present")
        routes.append(route)
        by_id[rid] = route
        by_path[path] = route
    return routes, by_id, by_path


def load_actions(contract: dict[str, Any], route_by_id: dict[str, Route]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    nav: dict[str, dict[str, Any]] = {}
    handoffs: dict[str, dict[str, Any]] = {}
    exceptions: dict[str, dict[str, Any]] = {}

    for edge in contract.get("transitions", []):
        if not isinstance(edge, dict):
            raise ValidationError("transition must be object")
        src, action, target = edge.get("from"), edge.get("action"), edge.get("to")
        if src not in route_by_id or target not in route_by_id or not isinstance(action, str) or not action:
            raise ValidationError(f"invalid transition: {edge!r}")
        key = (src, action)
        if key in edges:
            raise ValidationError(f"duplicate transition action {action!r} from {src!r}")
        edges[key] = edge

    for item in contract.get("navigation", []):
        if not isinstance(item, dict):
            raise ValidationError("navigation item must be object")
        action, target, cls = item.get("action"), item.get("to"), item.get("class")
        if not isinstance(action, str) or not action or target not in route_by_id or cls not in {"global", "utility"}:
            raise ValidationError(f"invalid navigation item: {item!r}")
        if action in nav:
            raise ValidationError(f"duplicate navigation action: {action}")
        nav[action] = item

    for item in contract.get("handoffs", []):
        if not isinstance(item, dict):
            raise ValidationError("handoff must be object")
        action = item.get("action")
        if not isinstance(action, str) or not action:
            raise ValidationError(f"invalid handoff action: {item!r}")
        if not any(isinstance(item.get(k), str) and item.get(k) for k in ("url", "url_prefix")):
            raise ValidationError(f"handoff {action!r} requires url or url_prefix")
        if action in handoffs:
            raise ValidationError(f"duplicate handoff action: {action}")
        handoffs[action] = item

    for item in contract.get("exceptions", []):
        if not isinstance(item, dict):
            raise ValidationError("exception must be object")
        action = item.get("action")
        if not isinstance(action, str) or not action or not isinstance(item.get("reason"), str):
            raise ValidationError(f"invalid exception: {item!r}")
        if action in exceptions:
            raise ValidationError(f"duplicate exception action: {action}")
        exceptions[action] = item

    namespaces = defaultdict(list)
    for label, mapping in [("navigation", nav), ("handoff", handoffs), ("exception", exceptions)]:
        for action in mapping:
            namespaces[action].append(label)
    for action, kinds in namespaces.items():
        if len(kinds) > 1:
            raise ValidationError(f"action {action!r} is ambiguously declared in {kinds}")
    return edges, nav, handoffs, exceptions


def check_reachability(
    contract: dict[str, Any],
    routes: list[Route],
    route_by_id: dict[str, Route],
    edges: dict[tuple[str, str], dict[str, Any]],
    nav: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    entries = contract.get("entry_states")
    if not isinstance(entries, list) or not entries or any(e not in route_by_id for e in entries):
        fail(errors, "entry_states must be a non-empty array of declared route ids")
        return

    graph: dict[str, set[str]] = defaultdict(set)
    for (src, _), edge in edges.items():
        graph[src].add(edge["to"])
    for src in route_by_id:
        for item in nav.values():
            graph[src].add(item["to"])

    seen: set[str] = set()
    queue = deque(entries)
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(sorted(graph[current] - seen))
    for route in routes:
        if route.required and route.id not in seen:
            fail(errors, f"required route/state {route.id!r} is unreachable from entry_states")

    outgoing = defaultdict(int)
    for (src, _), edge in edges.items():
        outgoing[src] += 1
    for route in routes:
        if route.required and not route.terminal and outgoing[route.id] == 0 and not nav:
            fail(errors, f"required non-terminal route/state {route.id!r} has no declared continuation/recovery path")


def parse_sitemap(path: Path) -> dict[str, str | None]:
    if not path.exists():
        raise ValidationError(f"missing sitemap: {path}")
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError) as exc:
        raise ValidationError(f"invalid sitemap {path}: {exc}") from exc
    result: dict[str, str | None] = {}
    for url in root.findall(".//{*}url"):
        loc_el = url.find("{*}loc")
        lastmod_el = url.find("{*}lastmod")
        if loc_el is None or not (loc_el.text or "").strip():
            raise ValidationError("sitemap url entry missing loc")
        loc = (loc_el.text or "").strip()
        if loc in result:
            raise ValidationError(f"duplicate sitemap URL: {loc}")
        result[loc] = (lastmod_el.text or "").strip() if lastmod_el is not None and (lastmod_el.text or "").strip() else None
    return result


def parse_robots(path: Path) -> tuple[list[str], list[tuple[str, str]]]:
    if not path.exists():
        raise ValidationError(f"missing robots.txt: {path}")
    sitemaps: list[str] = []
    directives: list[tuple[str, str]] = []
    current_agents: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = [x.strip() for x in line.split(":", 1)]
        key_l = key.lower()
        if key_l == "user-agent":
            current_agents = [value.lower()]
        elif key_l == "sitemap":
            sitemaps.append(value)
        elif key_l in {"allow", "disallow"}:
            for agent in current_agents or ["*"]:
                directives.append((agent, f"{key_l}:{value}"))
    return sitemaps, directives


def is_same_site(url: str, base_url: str) -> tuple[bool, bool]:
    u, b = urlparse(url), urlparse(base_url)
    same_origin = (u.scheme, u.netloc) == (b.scheme, b.netloc)
    base_path = b.path if b.path.endswith("/") else b.path + "/"
    in_base = same_origin and (u.path == base_path[:-1] or u.path.startswith(base_path))
    return same_origin, in_base


def route_id_for_absolute(url: str, base_url: str, route_by_path: dict[str, Route]) -> str | None:
    p = urlparse(url)
    b = urlparse(base_url)
    base_path = b.path if b.path.endswith("/") else b.path + "/"
    if not p.path.startswith(base_path):
        return None
    rel = p.path[len(base_path):]
    project_path = "/" + rel
    if project_path == "/":
        project_path = "/"
    elif p.path.endswith("/") and not project_path.endswith("/"):
        project_path += "/"
    try:
        project_path = normalize_route_path(project_path)
    except ValidationError:
        return None
    route = route_by_path.get(project_path)
    return route.id if route else None


def validate(contract_path: Path, site_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    contract = load_contract(contract_path)
    base_url = normalize_base_url(contract.get("production_base_url", ""))
    routes, route_by_id, route_by_path = build_routes(contract)
    edges, nav, handoffs, exceptions = load_actions(contract, route_by_id)
    check_reachability(contract, routes, route_by_id, edges, nav, errors)

    observed_edges: list[dict[str, Any]] = []
    observed_handoffs: list[dict[str, Any]] = []
    browser_required: list[dict[str, Any]] = []
    seen_required_edges: set[tuple[str, str]] = set()

    discovery = contract.get("discovery") or {}
    if not isinstance(discovery, dict):
        raise ValidationError("discovery must be an object")
    sitemap_rel = discovery.get("sitemap", "sitemap.xml")
    robots_rel = discovery.get("robots", "robots.txt")
    describedby_rel = discovery.get("machine_description")
    sitemap_url = urljoin(base_url, sitemap_rel)

    expected_sitemap: dict[str, str | None] = {}
    for route in routes:
        if route.indexable:
            expected_sitemap[route_url(base_url, route.path)] = route.lastmod

    actual_sitemap = parse_sitemap(site_dir / sitemap_rel)
    if set(actual_sitemap) != set(expected_sitemap):
        missing = sorted(set(expected_sitemap) - set(actual_sitemap))
        unexpected = sorted(set(actual_sitemap) - set(expected_sitemap))
        if missing:
            fail(errors, f"sitemap missing indexable canonical routes: {missing}")
        if unexpected:
            fail(errors, f"sitemap contains undeclared/non-indexable routes: {unexpected}")
    for loc in sorted(set(actual_sitemap) & set(expected_sitemap)):
        expected_lastmod = expected_sitemap[loc]
        actual_lastmod = actual_sitemap[loc]
        if expected_lastmod != actual_lastmod:
            fail(errors, f"sitemap lastmod mismatch for {loc}: expected {expected_lastmod!r}, got {actual_lastmod!r}")

    robot_sitemaps, robot_directives = parse_robots(site_dir / robots_rel)
    if sitemap_url not in robot_sitemaps:
        fail(errors, f"robots.txt must advertise canonical sitemap URL {sitemap_url}")
    base_path = urlparse(base_url).path
    for agent, directive in robot_directives:
        if agent == "*" and directive.lower().startswith("disallow:"):
            disallow = directive.split(":", 1)[1].strip()
            if disallow in {"/", base_path, base_path.rstrip("/")}:
                fail(errors, f"robots.txt blocks the production site for User-agent *: {directive}")

    for route in routes:
        file_path = local_file_for_route(site_dir, route.path)
        if not file_path.exists():
            if route.required:
                fail(errors, f"missing required rendered route {route.id!r}: {file_path}")
            continue
        parser = parse_html(file_path)
        if parser.states != [route.id]:
            fail(errors, f"{route.id}: expected exactly data-surface-state={route.id!r}, observed {parser.states!r}")
        if parser.title != route.title:
            fail(errors, f"{route.id}: title mismatch: expected {route.title!r}, got {parser.title!r}")

        canonical = route_url(base_url, route.path)
        if parser.canonicals != [canonical]:
            fail(errors, f"{route.id}: expected exactly canonical {canonical!r}, observed {parser.canonicals!r}")
        noindex = any("noindex" in {t.strip().lower() for t in content.split(",")} for content in parser.meta_robots)
        if route.indexable and noindex:
            fail(errors, f"{route.id}: indexable route is marked noindex")
        if not route.indexable and not noindex:
            warnings.append(f"{route.id}: route is non-indexable by contract but page does not explicitly declare noindex")

        if describedby_rel:
            describedby_abs = urljoin(base_url, describedby_rel)
            resolved = {urljoin(canonical, href) for href in parser.describedby}
            if describedby_abs not in resolved:
                fail(errors, f"{route.id}: missing rel=describedby discovery link to {describedby_abs}")

        for item in parser.actions:
            action = item["action"]
            href = item["href"]
            tag = item["tag"]
            if not action:
                if tag == "a" and href:
                    fail(errors, f"{route.id}: rendered link {href!r} lacks data-surface-action classification")
                elif tag == "button":
                    fail(errors, f"{route.id}: rendered button lacks data-surface-action classification")
                continue

            edge = edges.get((route.id, action))
            nav_item = nav.get(action)
            handoff = handoffs.get(action)
            exception = exceptions.get(action)
            matched = sum(x is not None for x in (edge, nav_item, handoff, exception))
            if matched == 0:
                fail(errors, f"{route.id}: rendered action {action!r} is undeclared")
                continue
            if matched > 1:
                fail(errors, f"{route.id}: rendered action {action!r} matches multiple classifications")
                continue
            if exception:
                continue

            if href is None:
                if edge and bool(edge.get("browser_required", False)):
                    browser_required.append({"from": route.id, "action": action, "to": edge["to"]})
                    seen_required_edges.add((route.id, action))
                elif nav_item and bool(nav_item.get("browser_required", False)):
                    browser_required.append({"from": route.id, "action": action, "to": nav_item["to"]})
                else:
                    fail(errors, f"{route.id}: action {action!r} has no href and is not declared browser_required")
                continue

            absolute = urljoin(canonical, href)
            same_origin, in_base = is_same_site(absolute, base_url)

            if edge or nav_item:
                target_id = edge["to"] if edge else nav_item["to"]
                if same_origin and not in_base:
                    fail(errors, f"{route.id}: internal action {action!r} escapes project base path: {absolute}")
                    continue
                if not same_origin:
                    fail(errors, f"{route.id}: internal action {action!r} unexpectedly exits site: {absolute}")
                    continue
                observed_target = route_id_for_absolute(absolute, base_url, route_by_path)
                if observed_target != target_id:
                    fail(errors, f"{route.id}: action {action!r} targets {observed_target!r}/{absolute}, expected {target_id!r}")
                    continue
                observed_edges.append({"from": route.id, "action": action, "to": target_id, "class": "flow" if edge else nav_item["class"]})
                if edge:
                    seen_required_edges.add((route.id, action))
                continue

            if handoff:
                if same_origin:
                    fail(errors, f"{route.id}: external handoff {action!r} unexpectedly stays on same origin: {absolute}")
                    continue
                exact = handoff.get("url")
                prefix = handoff.get("url_prefix")
                if exact and absolute != exact:
                    fail(errors, f"{route.id}: handoff {action!r} URL mismatch: {absolute!r} != {exact!r}")
                    continue
                if prefix and not absolute.startswith(prefix):
                    fail(errors, f"{route.id}: handoff {action!r} URL {absolute!r} does not match prefix {prefix!r}")
                    continue
                declared_handoff = handoff.get("handoff")
                observed_handoff = item.get("handoff")
                if declared_handoff and observed_handoff != declared_handoff:
                    fail(errors, f"{route.id}: handoff {action!r} requires data-surface-handoff={declared_handoff!r}, got {observed_handoff!r}")
                    continue
                observed_handoffs.append({"from": route.id, "action": action, "url": absolute})

    for key, edge in edges.items():
        if bool(edge.get("required_rendered", True)) and key not in seen_required_edges:
            fail(errors, f"required rendered transition missing: {key[0]} --{key[1]}--> {edge['to']}")

    evidence = {
        "schema": "public-surface-conformance-evidence/1",
        "contract_schema": SCHEMA,
        "production_base_url": base_url,
        "route_count": len(routes),
        "expected_transition_count": len(edges),
        "observed_edge_count": len(observed_edges),
        "observed_handoff_count": len(observed_handoffs),
        "browser_required_actions": sorted(browser_required, key=lambda x: (x["from"], x["action"], x["to"])),
        "observed_edges": sorted(observed_edges, key=lambda x: (x["from"], x["action"], x["to"])),
        "external_handoffs": sorted(observed_handoffs, key=lambda x: (x["from"], x["action"], x["url"])),
        "sitemap_routes": sorted(actual_sitemap),
        "warnings": sorted(warnings),
        "errors": sorted(errors),
        "verdict": "pass" if not errors else "fail",
    }
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--site-dir", required=True, type=Path)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()

    try:
        evidence = validate(args.contract, args.site_dir)
    except ValidationError as exc:
        evidence = {
            "schema": "public-surface-conformance-evidence/1",
            "contract_schema": SCHEMA,
            "verdict": "fail",
            "errors": [str(exc)],
            "warnings": [],
        }

    encoded = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0 if evidence["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
