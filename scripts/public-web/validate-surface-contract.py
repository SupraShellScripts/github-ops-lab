#!/usr/bin/env python3
"""Read-only deterministic public-surface model/discovery conformance validator."""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

CONTRACT_SCHEMA = "public-surface-contract/1"
EVIDENCE_SCHEMA = "public-surface-conformance-evidence/1"
SELF = "$self"


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


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._title: list[str] = []
        self.states: list[str] = []
        self.canonicals: list[str] = []
        self.describedby: list[str] = []
        self.robots: list[str] = []
        self.actions: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        a = {k.lower(): v for k, v in attrs}
        if tag == "title":
            self._in_title = True
        if a.get("data-surface-state"):
            self.states.append(a["data-surface-state"] or "")
        if tag == "link":
            rel = set((a.get("rel") or "").lower().split())
            if a.get("href") and "canonical" in rel:
                self.canonicals.append(a["href"] or "")
            if a.get("href") and "describedby" in rel:
                self.describedby.append(a["href"] or "")
        if tag == "meta" and (a.get("name") or "").lower() in {"robots", "googlebot"}:
            if a.get("content"):
                self.robots.append(a["content"] or "")
        if tag in {"a", "button"}:
            self.actions.append({
                "tag": tag,
                "action": a.get("data-surface-action"),
                "href": a.get("href") if tag == "a" else None,
                "handoff": a.get("data-surface-handoff"),
            })

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self._title).split())


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def norm_base(value: str, field: str) -> str:
    p = urlparse(value)
    if p.scheme not in {"http", "https"} or not p.netloc or p.query or p.fragment:
        raise ValidationError(f"{field} must be an absolute http(s) URL without query/fragment")
    path = p.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urlunparse((p.scheme, p.netloc, path, "", "", ""))


def norm_project_path(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValidationError(f"project path must start with '/': {value!r}")
    p = urlparse(value)
    if p.scheme or p.netloc or p.query or p.fragment:
        raise ValidationError(f"project path must be path-only: {value!r}")
    raw = re.sub(r"/+", "/", p.path)
    norm = posixpath.normpath(raw)
    if not norm.startswith("/"):
        norm = "/" + norm
    if raw.endswith("/") and norm != "/":
        norm += "/"
    return norm


def project_url(base: str, project_path: str) -> str:
    return urljoin(base, project_path.lstrip("/"))


def route_file(site_dir: Path, path: str) -> Path:
    rel = path.lstrip("/")
    if not rel:
        return site_dir / "index.html"
    if path.endswith("/"):
        return site_dir / rel / "index.html"
    if Path(rel).suffix.lower() in {".html", ".htm"}:
        return site_dir / rel
    return site_dir / rel / "index.html"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must contain a JSON object")
    return value


def parse_page(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser


def load_routes(contract: dict[str, Any]) -> tuple[list[Route], dict[str, Route], dict[str, Route]]:
    raw_routes = contract.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValidationError("routes must be a non-empty array")
    routes: list[Route] = []
    by_id: dict[str, Route] = {}
    by_path: dict[str, Route] = {}
    for raw in raw_routes:
        if not isinstance(raw, dict):
            raise ValidationError("route entries must be objects")
        rid, title = raw.get("id"), raw.get("title")
        if not isinstance(rid, str) or not rid:
            raise ValidationError("route id must be a non-empty string")
        if not isinstance(title, str) or not title.strip():
            raise ValidationError(f"route {rid!r} requires an exact expected title")
        path = norm_project_path(raw.get("path"))
        if rid in by_id or path in by_path:
            raise ValidationError(f"duplicate route id/path: {rid!r} {path!r}")
        lastmod = raw.get("lastmod")
        if lastmod is not None and not isinstance(lastmod, str):
            raise ValidationError(f"route {rid!r} lastmod must be a string")
        route = Route(
            rid, path, title.strip(),
            bool(raw.get("indexable", True)),
            bool(raw.get("required", True)),
            bool(raw.get("terminal", False)),
            lastmod,
        )
        routes.append(route)
        by_id[rid] = route
        by_path[path] = route
    return routes, by_id, by_path


def load_action_contract(
    contract: dict[str, Any], by_id: dict[str, Route]
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    transitions: dict[tuple[str, str], dict[str, Any]] = {}
    navigation: dict[str, dict[str, Any]] = {}
    resources: dict[str, dict[str, Any]] = {}
    handoffs: dict[str, dict[str, Any]] = {}
    exceptions: dict[str, dict[str, Any]] = {}

    for item in contract.get("transitions", []):
        if not isinstance(item, dict):
            raise ValidationError("transition entries must be objects")
        src, action, target = item.get("from"), item.get("action"), item.get("to")
        if src not in by_id or target not in by_id or not isinstance(action, str) or not action:
            raise ValidationError(f"invalid transition: {item!r}")
        key = (src, action)
        if key in transitions:
            raise ValidationError(f"duplicate transition: {key!r}")
        transitions[key] = item

    for item in contract.get("navigation", []):
        if not isinstance(item, dict):
            raise ValidationError("navigation entries must be objects")
        action, target, cls = item.get("action"), item.get("to"), item.get("class")
        if (
            not isinstance(action, str) or not action
            or (target != SELF and target not in by_id)
            or cls not in {"global", "utility"}
        ):
            raise ValidationError(f"invalid navigation: {item!r}")
        if action in navigation:
            raise ValidationError(f"duplicate navigation action {action!r}")
        navigation[action] = item

    for item in contract.get("resources", []):
        if not isinstance(item, dict):
            raise ValidationError("resource entries must be objects")
        action = item.get("action")
        exact, prefix = item.get("path"), item.get("path_prefix")
        if not isinstance(action, str) or not action:
            raise ValidationError(f"invalid resource action: {item!r}")
        if bool(exact) == bool(prefix):
            raise ValidationError(f"resource {action!r} requires exactly one of path/path_prefix")
        if exact:
            item = dict(item)
            item["path"] = norm_project_path(exact)
        if prefix:
            item = dict(item)
            item["path_prefix"] = norm_project_path(prefix)
        if action in resources:
            raise ValidationError(f"duplicate resource action {action!r}")
        resources[action] = item

    for item in contract.get("handoffs", []):
        if not isinstance(item, dict):
            raise ValidationError("handoff entries must be objects")
        action = item.get("action")
        if not isinstance(action, str) or not action:
            raise ValidationError(f"invalid handoff action: {item!r}")
        if not any(isinstance(item.get(k), str) and item.get(k) for k in ("url", "url_prefix")):
            raise ValidationError(f"handoff {action!r} requires url or url_prefix")
        if action in handoffs:
            raise ValidationError(f"duplicate handoff action {action!r}")
        handoffs[action] = item

    for item in contract.get("exceptions", []):
        if not isinstance(item, dict):
            raise ValidationError("exception entries must be objects")
        action, reason = item.get("action"), item.get("reason")
        if not isinstance(action, str) or not action or not isinstance(reason, str) or not reason:
            raise ValidationError(f"invalid exception: {item!r}")
        if action in exceptions:
            raise ValidationError(f"duplicate exception action {action!r}")
        exceptions[action] = item

    seen: dict[str, str] = {}
    for kind, mapping in [
        ("navigation", navigation),
        ("resource", resources),
        ("handoff", handoffs),
        ("exception", exceptions),
    ]:
        for action in mapping:
            if action in seen:
                raise ValidationError(f"action {action!r} appears in both {seen[action]} and {kind}")
            seen[action] = kind
    return transitions, navigation, resources, handoffs, exceptions


def check_model(
    contract: dict[str, Any],
    routes: list[Route],
    by_id: dict[str, Route],
    transitions: dict[tuple[str, str], dict[str, Any]],
    navigation: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    entries = contract.get("entry_states")
    if not isinstance(entries, list) or not entries or any(e not in by_id for e in entries):
        add_error(errors, "entry_states must be a non-empty list of declared route ids")
        return
    graph: dict[str, set[str]] = defaultdict(set)
    for (src, _), item in transitions.items():
        graph[src].add(item["to"])
    for src in by_id:
        for item in navigation.values():
            target = src if item["to"] == SELF else item["to"]
            graph[src].add(target)
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
            add_error(errors, f"required route/state {route.id!r} is unreachable from entry_states")


def parse_sitemap(path: Path) -> dict[str, str | None]:
    if not path.exists():
        raise ValidationError(f"missing sitemap: {path}")
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError) as exc:
        raise ValidationError(f"invalid sitemap {path}: {exc}") from exc
    result: dict[str, str | None] = {}
    for node in root.findall(".//{*}url"):
        loc_node, last_node = node.find("{*}loc"), node.find("{*}lastmod")
        loc = (loc_node.text or "").strip() if loc_node is not None else ""
        if not loc:
            raise ValidationError("sitemap URL entry is missing loc")
        if loc in result:
            raise ValidationError(f"duplicate sitemap URL {loc!r}")
        result[loc] = (last_node.text or "").strip() if last_node is not None and (last_node.text or "").strip() else None
    return result


def parse_robots(path: Path) -> tuple[list[str], list[tuple[str, str, str]]]:
    if not path.exists():
        raise ValidationError(f"missing robots.txt: {path}")
    sitemaps: list[str] = []
    directives: list[tuple[str, str, str]] = []
    agents: list[str] = []
    previous_was_agent = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            previous_was_agent = False if not line else previous_was_agent
            continue
        key, value = [v.strip() for v in line.split(":", 1)]
        key = key.lower()
        if key == "user-agent":
            if not previous_was_agent:
                agents = []
            agents.append(value.lower())
            previous_was_agent = True
        elif key == "sitemap":
            sitemaps.append(value)
            previous_was_agent = False
        elif key in {"allow", "disallow"}:
            for agent in agents or ["*"]:
                directives.append((agent, key, value))
            previous_was_agent = False
        else:
            previous_was_agent = False
    return sitemaps, directives


def same_origin_and_base(url: str, base: str) -> tuple[bool, bool]:
    u, b = urlparse(url), urlparse(base)
    same_origin = (u.scheme, u.netloc) == (b.scheme, b.netloc)
    base_path = b.path if b.path.endswith("/") else b.path + "/"
    return same_origin, same_origin and (u.path == base_path[:-1] or u.path.startswith(base_path))


def project_path_for_url(url: str, base: str) -> str | None:
    u, b = urlparse(url), urlparse(base)
    base_path = b.path if b.path.endswith("/") else b.path + "/"
    if u.path == base_path[:-1]:
        return "/"
    if not u.path.startswith(base_path):
        return None
    return norm_project_path("/" + u.path[len(base_path):])


def target_route(url: str, navigation_base: str, by_path: dict[str, Route]) -> str | None:
    path = project_path_for_url(url, navigation_base)
    if path is None:
        return None
    route = by_path.get(path)
    return route.id if route else None


def required_sources(item: dict[str, Any], routes: list[Route], default_all: bool) -> set[str]:
    raw = item.get("required_on")
    if raw is None:
        return {route.id for route in routes if route.required} if default_all else set()
    if raw is False:
        return set()
    if not isinstance(raw, list) or any(not isinstance(v, str) for v in raw):
        raise ValidationError("required_on must be false or a list of route ids")
    return set(raw)


def validate(contract_path: Path, site_dir: Path, navigation_base_url: str | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    contract = read_json(contract_path)
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise ValidationError(f"contract schema must be {CONTRACT_SCHEMA!r}")

    production_base = norm_base(contract.get("production_base_url", ""), "production_base_url")
    navigation_base = norm_base(navigation_base_url or production_base, "navigation_base_url")
    routes, by_id, by_path = load_routes(contract)
    transitions, navigation, resources, handoffs, exceptions = load_action_contract(contract, by_id)
    check_model(contract, routes, by_id, transitions, navigation, errors)

    discovery = contract.get("discovery") or {}
    if not isinstance(discovery, dict):
        raise ValidationError("discovery must be an object")
    sitemap_rel = discovery.get("sitemap", "sitemap.xml")
    robots_rel = discovery.get("robots", "robots.txt")
    machine_rel = discovery.get("machine_description")

    expected_sitemap = {
        project_url(production_base, route.path): route.lastmod
        for route in routes if route.indexable
    }
    actual_sitemap = parse_sitemap(site_dir / sitemap_rel)
    missing = sorted(set(expected_sitemap) - set(actual_sitemap))
    unexpected = sorted(set(actual_sitemap) - set(expected_sitemap))
    if missing:
        add_error(errors, f"sitemap missing indexable canonical routes: {missing}")
    if unexpected:
        add_error(errors, f"sitemap contains undeclared/non-indexable routes: {unexpected}")
    for loc in sorted(set(expected_sitemap) & set(actual_sitemap)):
        if expected_sitemap[loc] != actual_sitemap[loc]:
            add_error(errors, f"sitemap lastmod mismatch for {loc}: expected {expected_sitemap[loc]!r}, got {actual_sitemap[loc]!r}")

    sitemap_url = urljoin(production_base, sitemap_rel)
    robot_sitemaps, robot_directives = parse_robots(site_dir / robots_rel)
    if sitemap_url not in robot_sitemaps:
        add_error(errors, f"robots.txt must advertise canonical sitemap URL {sitemap_url}")
    production_path = urlparse(production_base).path
    for agent, kind, value in robot_directives:
        if agent == "*" and kind == "disallow" and value in {"/", production_path, production_path.rstrip("/")}:
            add_error(errors, f"robots.txt blocks production site for User-agent *: Disallow: {value}")

    if machine_rel and not urlparse(machine_rel).scheme:
        machine_path = site_dir / machine_rel.lstrip("/")
        if not machine_path.exists():
            add_error(errors, f"declared machine description does not exist in candidate bytes: {machine_path}")

    observed_edges: list[dict[str, str]] = []
    observed_resources: list[dict[str, str]] = []
    observed_handoffs: list[dict[str, str]] = []
    browser_required: list[dict[str, str]] = []
    seen_transitions: set[tuple[str, str]] = set()
    seen_navigation: set[tuple[str, str]] = set()
    seen_resources: set[tuple[str, str]] = set()
    recovery_edges: dict[str, int] = defaultdict(int)

    for route in routes:
        page_path = route_file(site_dir, route.path)
        if not page_path.exists():
            if route.required:
                add_error(errors, f"missing required rendered route {route.id!r}: {page_path}")
            continue
        page = parse_page(page_path)
        canonical = project_url(production_base, route.path)
        candidate_page = project_url(navigation_base, route.path)

        if page.states != [route.id]:
            add_error(errors, f"{route.id}: expected exactly data-surface-state={route.id!r}, observed {page.states!r}")
        if page.title != route.title:
            add_error(errors, f"{route.id}: title mismatch: expected {route.title!r}, got {page.title!r}")
        if page.canonicals != [canonical]:
            add_error(errors, f"{route.id}: expected exactly canonical {canonical!r}, observed {page.canonicals!r}")
        noindex = any(
            "noindex" in {token.strip().lower() for token in value.split(",")}
            for value in page.robots
        )
        if route.indexable and noindex:
            add_error(errors, f"{route.id}: indexable route is marked noindex")
        if not route.indexable and not noindex:
            warnings.append(f"{route.id}: non-indexable route does not explicitly declare noindex")

        if machine_rel:
            parsed_machine = urlparse(machine_rel)
            expected_machine = (
                machine_rel
                if parsed_machine.scheme
                else urljoin(navigation_base, machine_rel.lstrip("/"))
            )
            resolved = {urljoin(candidate_page, href) for href in page.describedby}
            if expected_machine not in resolved:
                add_error(errors, f"{route.id}: missing rel=describedby link to candidate machine description {expected_machine}")

        for rendered in page.actions:
            action, href, tag = rendered["action"], rendered["href"], rendered["tag"]
            if not action:
                if (tag == "a" and href) or tag == "button":
                    add_error(errors, f"{route.id}: rendered {tag} lacks data-surface-action classification")
                continue

            transition = transitions.get((route.id, action))
            nav = navigation.get(action)
            resource = resources.get(action)
            handoff = handoffs.get(action)
            exception = exceptions.get(action)
            matches = sum(v is not None for v in (transition, nav, resource, handoff, exception))
            if matches != 1:
                add_error(errors, f"{route.id}: rendered action {action!r} has {matches} declared classifications")
                continue
            if exception:
                continue

            if href is None:
                declared = transition or nav
                if declared and bool(declared.get("browser_required", False)):
                    raw_target = declared["to"]
                    target = route.id if raw_target == SELF else raw_target
                    browser_required.append({"from": route.id, "action": action, "to": target})
                    if target != route.id:
                        recovery_edges[route.id] += 1
                    if transition:
                        seen_transitions.add((route.id, action))
                    if nav:
                        seen_navigation.add((route.id, action))
                else:
                    add_error(errors, f"{route.id}: action {action!r} has no href and is not browser_required")
                continue

            absolute = urljoin(candidate_page, href)
            same_origin, in_base = same_origin_and_base(absolute, navigation_base)

            if transition or nav:
                raw_target = (transition or nav)["to"]
                target = route.id if raw_target == SELF else raw_target
                if same_origin and not in_base:
                    add_error(errors, f"{route.id}: internal action {action!r} escapes candidate project base path: {absolute}")
                    continue
                if not same_origin:
                    add_error(errors, f"{route.id}: internal action {action!r} unexpectedly exits candidate site: {absolute}")
                    continue
                observed_target = target_route(absolute, navigation_base, by_path)
                if observed_target != target:
                    add_error(errors, f"{route.id}: action {action!r} targets {observed_target!r}/{absolute}, expected {target!r}")
                    continue
                cls = "flow" if transition else (transition or nav)["class"]
                observed_edges.append({"from": route.id, "action": action, "to": target, "class": cls})
                if target != route.id:
                    recovery_edges[route.id] += 1
                if transition:
                    seen_transitions.add((route.id, action))
                if nav:
                    seen_navigation.add((route.id, action))
                continue

            if resource:
                if same_origin and not in_base:
                    add_error(errors, f"{route.id}: resource action {action!r} escapes candidate project base path: {absolute}")
                    continue
                if not same_origin:
                    add_error(errors, f"{route.id}: internal resource action {action!r} unexpectedly exits candidate site: {absolute}")
                    continue
                observed_path = project_path_for_url(absolute, navigation_base)
                exact, prefix = resource.get("path"), resource.get("path_prefix")
                if exact and observed_path != exact:
                    add_error(errors, f"{route.id}: resource {action!r} path mismatch: {observed_path!r} != {exact!r}")
                    continue
                if prefix and (observed_path is None or not observed_path.startswith(prefix)):
                    add_error(errors, f"{route.id}: resource {action!r} path {observed_path!r} does not match prefix {prefix!r}")
                    continue
                observed_resources.append({"from": route.id, "action": action, "path": observed_path or ""})
                seen_resources.add((route.id, action))
                continue

            if handoff:
                if same_origin:
                    add_error(errors, f"{route.id}: external handoff {action!r} unexpectedly stays on candidate origin: {absolute}")
                    continue
                exact, prefix = handoff.get("url"), handoff.get("url_prefix")
                if exact and absolute != exact:
                    add_error(errors, f"{route.id}: handoff {action!r} URL mismatch: {absolute!r} != {exact!r}")
                    continue
                if prefix and not absolute.startswith(prefix):
                    add_error(errors, f"{route.id}: handoff {action!r} URL {absolute!r} does not match prefix {prefix!r}")
                    continue
                if handoff.get("handoff") and rendered.get("handoff") != handoff["handoff"]:
                    add_error(errors, f"{route.id}: handoff {action!r} requires data-surface-handoff={handoff['handoff']!r}")
                    continue
                observed_handoffs.append({"from": route.id, "action": action, "url": absolute})

    for key, item in transitions.items():
        if bool(item.get("required_rendered", True)) and key not in seen_transitions:
            add_error(errors, f"required rendered transition missing: {key[0]} --{key[1]}--> {item['to']}")

    for action, item in navigation.items():
        for source in required_sources(item, routes, default_all=True):
            if source not in by_id:
                raise ValidationError(f"navigation {action!r} required_on references unknown route {source!r}")
            if (source, action) not in seen_navigation:
                add_error(errors, f"required rendered {item['class']} navigation missing on {source!r}: {action!r}")

    for action, item in resources.items():
        for source in required_sources(item, routes, default_all=False):
            if source not in by_id:
                raise ValidationError(f"resource {action!r} required_on references unknown route {source!r}")
            if (source, action) not in seen_resources:
                add_error(errors, f"required rendered resource missing on {source!r}: {action!r}")

    for route in routes:
        if route.required and not route.terminal and recovery_edges[route.id] == 0:
            add_error(errors, f"required non-terminal route/state {route.id!r} is a rendered dead end")

    return {
        "schema": EVIDENCE_SCHEMA,
        "contract_schema": CONTRACT_SCHEMA,
        "production_base_url": production_base,
        "navigation_base_url": navigation_base,
        "route_count": len(routes),
        "expected_transition_count": len(transitions),
        "observed_edge_count": len(observed_edges),
        "observed_resource_count": len(observed_resources),
        "observed_handoff_count": len(observed_handoffs),
        "browser_required_actions": sorted(browser_required, key=lambda v: (v["from"], v["action"], v["to"])),
        "observed_edges": sorted(observed_edges, key=lambda v: (v["from"], v["action"], v["to"])),
        "internal_resources": sorted(observed_resources, key=lambda v: (v["from"], v["action"], v["path"])),
        "external_handoffs": sorted(observed_handoffs, key=lambda v: (v["from"], v["action"], v["url"])),
        "sitemap_routes": sorted(actual_sitemap),
        "warnings": sorted(warnings),
        "errors": sorted(errors),
        "verdict": "pass" if not errors else "fail",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--site-dir", required=True, type=Path)
    parser.add_argument("--navigation-base")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    try:
        evidence = validate(args.contract, args.site_dir, args.navigation_base)
    except ValidationError as exc:
        evidence = {
            "schema": EVIDENCE_SCHEMA,
            "contract_schema": CONTRACT_SCHEMA,
            "verdict": "fail",
            "errors": [str(exc)],
            "warnings": [],
        }
    text = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0 if evidence["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
