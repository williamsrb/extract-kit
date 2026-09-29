"""project-map v1 examples match the schema; Enonic details stay under stackRef."""

from __future__ import annotations

import unittest

from extractkit_cli.errors import ExtractkitError
from extractkit_cli.schema import validate

EXAMPLE = {
    "schema": "99x.extract.project-map/v1",
    "surfaces": [
        {
            "id": "com.example.mini:part:mini-part",
            "kind": "part",
            "entry": "xp/src/main/resources/site/parts/mini-part/mini-part.xml",
            "composition": [],
            "contentTypes": [],
            "states": [],
            "integrations": [],
            "evidence": [],
            "status": "unverified-live",
            "stackRef": {
                "enonic": {
                    "descriptor": (
                        "xp/src/main/resources/site/parts/mini-part/mini-part.xml"
                    )
                }
            },
        }
    ],
}


class SchemaTests(unittest.TestCase):
    def test_example_project_map_is_valid(self) -> None:
        validate(EXAMPLE, "project-map")

    def test_missing_id_fails(self) -> None:
        bad = {
            "schema": "99x.extract.project-map/v1",
            "surfaces": [{"kind": "part", "entry": "x", "status": "live"}],
        }
        with self.assertRaises(ExtractkitError):
            validate(bad, "project-map")

    def test_enonic_fields_are_not_top_level_required(self) -> None:
        generic = {
            "schema": "99x.extract.project-map/v1",
            "surfaces": [
                {
                    "id": "php:route:home",
                    "kind": "route",
                    "entry": "routes/web.php",
                    "status": "unverified-live",
                }
            ],
        }
        validate(generic, "project-map")

    def test_bounded_contexts_example_is_valid(self) -> None:
        validate(
            {
                "schema": "99x.extract.bounded-contexts/v1",
                "contexts": [
                    {
                        "id": "presentation",
                        "title": "Presentation",
                        "kinds": ["page"],
                        "surfaces": ["com.example.mini:page:mini-page"],
                    }
                ],
            },
            "bounded-contexts",
        )


if __name__ == "__main__":
    unittest.main()
