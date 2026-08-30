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
                {
                    "id": "home",
                    "path": "/",
                    "title": "Example Project",
                    "indexable": True,
                    "required": True,
                    "terminal": False,
                },
                {
                    "id": "use",
                    "path": "/use/",
                    "title": "Use Example Project",
                    "indexable": True,
                    "required": True,
                    "terminal": False,
                },
            ],
            "transitions": [
                {
                    "from": "home",
                    "action": "view-use",
                    "to": "use",
                    "required_rendered": True,
                }
            ],
            "navigation": [
                {"action": "nav-home", "class": "global", "to": "home"}
            ],
            "handoffs": [
                {
                    "action": "view-source",
                    "handoff": "source",
                    "url_prefix": "https://github.com/example/",
                }
            ],
            "discovery": {
                "sitemap": "sitemap.xml",
                "robots": "robots.txt",
                "machine_description": "surface.json",
            },
        }
        self.contract_path.write_text(json.dumps(self.contract), encoding="utf-8")
        (self.site / "surface.json").write_text("{}\n", encoding="utf-8")
        (self.site / "index.html").write_text(
            """<!doctype html>
<html><head>
<title>Example Project</title>
<link rel="canonical" href="https://example.org/project/">
<link rel="describedby" href="surface.json">
</head><body>
<main data-surface-state="home">
<a data-surface-action="view-use" href="use/">Use</a>
<a data-surface-action="nav-home" href="./">Home</a>
<a data-surface-action="view-source" data-surface-handoff="source"
   href="https://github.com/example/repo">Source</a>
</main></body></html>
""",
            encoding="utf-8",
        )
        (self.site / "use" / "index.html").write_text(
            """<!doctype html>
<html><head>
<title>Use Example Project</title>
<link rel="canonical" href="https://example.org/project/use/">
<link rel="describedby" href="../surface.json">
</head><body>
<main data-surface-state="use">
<a data-surface-action="nav-home" href="../">Home</a>
<a data-surface-action="view-source" data-surface-handoff="source"
   href="https://github.com/example/repo">Source</a>
</main></body></html>
""",
            encoding="utf-8",
        )
        (self.site / "sitemap.xml").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.org/project/</loc></url>
  <url><loc>https://example.org/project/use/</loc></url>
</urlset>
""",
            encoding="utf-8",
        )
        (self.site / "robots.txt").write_text(
            """User-agent: *
Allow: /

Sitemap: https://example.org/project/sitemap.xml
""",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def validate(self):
        return module.validate(self.contract_path, self.site)

    def test_valid_surface_passes(self) -> None:
        evidence = self.validate()
        self.assertEqual("pass", evidence["verdict"])
        self.assertEqual([], evidence["errors"])
        self.assertEqual(1, evidence["expected_transition_count"])

    def test_project_base_path_escape_fails(self) -> None:
        path = self.site / "index.html"
        path.write_text(
            path.read_text(encoding="utf-8").replace('href="use/"', 'href="/outside/"'),
            encoding="utf-8",
        )
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("escapes project base path" in e for e in evidence["errors"]))

    def test_missing_sitemap_route_fails(self) -> None:
        path = self.site / "sitemap.xml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "  <url><loc>https://example.org/project/use/</loc></url>\n", ""
            ),
            encoding="utf-8",
        )
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("sitemap missing" in e for e in evidence["errors"]))

    def test_unclassified_link_fails(self) -> None:
        path = self.site / "index.html"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                '<a data-surface-action="view-use" href="use/">',
                '<a href="use/">',
            ),
            encoding="utf-8",
        )
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("lacks data-surface-action" in e for e in evidence["errors"]))

    def test_accidental_noindex_fails(self) -> None:
        path = self.site / "index.html"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "</head>", '<meta name="robots" content="noindex"></head>'
            ),
            encoding="utf-8",
        )
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("marked noindex" in e for e in evidence["errors"]))

    def test_undeclared_sitemap_lastmod_fails(self) -> None:
        path = self.site / "sitemap.xml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "<url><loc>https://example.org/project/</loc></url>",
                "<url><loc>https://example.org/project/</loc><lastmod>2026-08-30</lastmod></url>",
            ),
            encoding="utf-8",
        )
        evidence = self.validate()
        self.assertEqual("fail", evidence["verdict"])
        self.assertTrue(any("lastmod mismatch" in e for e in evidence["errors"]))


if __name__ == "__main__":
    unittest.main()
