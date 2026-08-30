#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "public-web" / "validate-surface-contract.py"
spec = importlib.util.spec_from_file_location("surface_validator", VALIDATOR)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class SurfaceConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.site = self.root / "site"
        (self.site / "use").mkdir(parents=True)
        self.contract_path = self.root / "contract.json"
        self.contract = {
            "schema": "public-surface-contract/1",
            "production_base_url": "https://example.org/project/",
            "entry_states": ["home"],
            "routes": [
                {"id": "home", "path": "/", "title": "Example Project", "indexable": True, "required": True, "terminal": False},
                {"id": "use", "path": "/use/", "title": "Use Example Project", "indexable": True, "required": True, "terminal": False},
            ],
            "transitions": [
                {"from": "home", "action": "view-use", "to": "use", "required_rendered": True}
            ],
            "navigation": [
                {"action": "nav-home", "class": "global", "to": "home"},
                {"action": "skip-main", "class": "utility", "to": "$self"},
            ],
            "resources": [
                {"action": "machine-project", "path": "/surface.json", "required_on": ["home"]}
            ],
            "handoffs": [
                {"action": "view-source", "handoff": "source", "url_prefix": "https://github.com/example/"}
            ],
            "discovery": {
                "sitemap": "sitemap.xml",
                "robots": {
                    "mode": "origin-external",
                    "url": "https://example.org/robots.txt",
                },
                "machine_description": "surface.json",
            },
        }
        self.write_contract()
        (self.site / "surface.json").write_text("{}\n", encoding="utf-8")
        (self.site / "index.html").write_text(
            """<!doctype html><html><head>
<title>Example Project</title>
<link rel="canonical" href="https://example.org/project/">
<link rel="describedby" href="surface.json">
</head><body>
<a data-surface-action="skip-main" href="#main">Skip</a>
<main id="main" data-surface-state="home">
<a data-surface-action="view-use" href="use/">Use</a>
<a data-surface-action="nav-home" href="./">Home</a>
<a data-surface-action="machine-project" href="surface.json">Machine</a>
<a data-surface-action="view-source" data-surface-handoff="source" href="https://github.com/example/repo">Source</a>
</main></body></html>\n""",
            encoding="utf-8",
        )
        (self.site / "use" / "index.html").write_text(
            """<!doctype html><html><head>
<title>Use Example Project</title>
<link rel="canonical" href="https://example.org/project/use/">
<link rel="describedby" href="../surface.json">
</head><body>
<a data-surface-action="skip-main" href="#main">Skip</a>
<main id="main" data-surface-state="use">
<a data-surface-action="nav-home" href="../">Home</a>
<a data-surface-action="view-source" data-surface-handoff="source" href="https://github.com/example/repo">Source</a>
</main></body></html>\n""",
            encoding="utf-8",
        )
        (self.site / "sitemap.xml").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.org/project/</loc></url>
  <url><loc>https://example.org/project/use/</loc></url>
</urlset>\n""",
            encoding="utf-8",
        )
        (self.site / "robots.txt").write_text(
            "User-agent: *\nAllow: /\n\nSitemap: https://example.org/project/sitemap.xml\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_contract(self) -> None:
        self.contract_path.write_text(json.dumps(self.contract), encoding="utf-8")

    def validate(self, navigation_base=None):
        return module.validate(self.contract_path, self.site, navigation_base)

    def test_valid_surface_passes(self) -> None:
        evidence = self.validate()
        self.assertEqual("pass", evidence["verdict"])
        self.assertEqual([], evidence["errors"])
        self.assertEqual(1, evidence["expected_transition_count"])
        self.assertEqual(1, evidence["observed_resource_count"])
        self.assertEqual("origin-external", evidence["robots"]["mode"])
        self.assertEqual("deferred-live", evidence["robots"]["verification"])

    def test_project_base_path_escape_fails(self) -> None:
        path = self.site / "index.html"
        path.write_text(path.read_text().replace('href="use/"', 'href="/outside/"'), encoding="utf-8")
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("escapes candidate project base path" in e for e in evidence["errors"]))

    def test_missing_sitemap_route_fails(self) -> None:
        path = self.site / "sitemap.xml"
        path.write_text(path.read_text().replace("  <url><loc>https://example.org/project/use/</loc></url>\n", ""), encoding="utf-8")
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("sitemap missing" in e for e in evidence["errors"]))

    def test_unclassified_link_fails(self) -> None:
        path = self.site / "index.html"
        path.write_text(path.read_text().replace('data-surface-action="view-use" ', ""), encoding="utf-8")
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("lacks data-surface-action" in e for e in evidence["errors"]))

    def test_accidental_noindex_fails(self) -> None:
        path = self.site / "index.html"
        path.write_text(path.read_text().replace("</head>", '<meta name="robots" content="noindex"></head>'), encoding="utf-8")
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("marked noindex" in e for e in evidence["errors"]))

    def test_undeclared_sitemap_lastmod_fails(self) -> None:
        path = self.site / "sitemap.xml"
        path.write_text(path.read_text().replace(
            "<url><loc>https://example.org/project/</loc></url>",
            "<url><loc>https://example.org/project/</loc><lastmod>2026-08-30</lastmod></url>"
        ), encoding="utf-8")
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("lastmod mismatch" in e for e in evidence["errors"]))

    def test_candidate_navigation_base_is_distinct_from_canonical_base(self) -> None:
        for path in [self.site / "index.html", self.site / "use" / "index.html"]:
            text = path.read_text(encoding="utf-8")
            text = text.replace('href="use/"', 'href="http://127.0.0.1:4173/use/"')
            text = text.replace('href="./"', 'href="http://127.0.0.1:4173/"')
            text = text.replace('href="../"', 'href="http://127.0.0.1:4173/"')
            text = text.replace('href="surface.json"', 'href="http://127.0.0.1:4173/surface.json"')
            path.write_text(text, encoding="utf-8")
        evidence = self.validate("http://127.0.0.1:4173/")
        self.assertEqual("pass", evidence["verdict"])
        self.assertEqual("https://example.org/project/", evidence["production_base_url"])
        self.assertEqual("http://127.0.0.1:4173/", evidence["navigation_base_url"])

    def test_rendered_dead_end_fails_even_with_skip_self_link(self) -> None:
        path = self.site / "use" / "index.html"
        path.write_text(path.read_text().replace('<a data-surface-action="nav-home" href="../">Home</a>\n', ""), encoding="utf-8")
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("rendered dead end" in e for e in evidence["errors"]))

    def test_machine_resource_wrong_path_fails(self) -> None:
        path = self.site / "index.html"
        path.write_text(path.read_text().replace('href="surface.json">Machine', 'href="wrong.json">Machine'), encoding="utf-8")
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("resource 'machine-project' path mismatch" in e for e in evidence["errors"]))

    def test_required_machine_resource_missing_fails(self) -> None:
        path = self.site / "index.html"
        line = '<a data-surface-action="machine-project" href="surface.json">Machine</a>\n'
        path.write_text(path.read_text().replace(line, ""), encoding="utf-8")
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("required rendered resource missing" in e for e in evidence["errors"]))

    def test_local_robots_is_rejected_for_subpath_surface(self) -> None:
        self.contract["discovery"]["robots"] = {"mode": "local", "path": "robots.txt"}
        self.write_contract()
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("local robots.txt is invalid for a subpath-hosted production surface" in e for e in evidence["errors"]))

    def test_origin_root_surface_can_validate_local_robots(self) -> None:
        self.contract["production_base_url"] = "https://example.org/"
        self.contract["discovery"]["robots"] = {"mode": "local", "path": "robots.txt"}
        self.write_contract()

        index = self.site / "index.html"
        index.write_text(index.read_text().replace("https://example.org/project/", "https://example.org/"), encoding="utf-8")
        use = self.site / "use" / "index.html"
        use.write_text(use.read_text().replace("https://example.org/project/use/", "https://example.org/use/"), encoding="utf-8")
        sitemap = self.site / "sitemap.xml"
        sitemap.write_text(sitemap.read_text().replace("https://example.org/project/", "https://example.org/"), encoding="utf-8")
        robots = self.site / "robots.txt"
        robots.write_text("User-agent: *\nAllow: /\n\nSitemap: https://example.org/sitemap.xml\n", encoding="utf-8")

        evidence = self.validate()
        self.assertEqual("pass", evidence["verdict"])
        self.assertEqual("local", evidence["robots"]["mode"])
        self.assertEqual("candidate", evidence["robots"]["verification"])


if __name__ == "__main__":
    unittest.main()
