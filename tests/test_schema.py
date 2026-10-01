"""project-map v1 examples match the schema; Enonic details stay under stackRef."""

from __future__ import annotations

import unittest

from extractkit_cli.errors import ExtractkitError
from extractkit_cli.schema import load_schema, validate

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

    def test_enonic_content_survey_examples_are_valid(self) -> None:
        validate(
            {
                "schema": "99x.extract.content-survey/v1",
                "host": "http://localhost:8080",
                "branch": "draft",
                "samplePerType": 3,
                "types": [
                    {"type": "com.example.mini:mini-article", "totalCount": 0, "sampled": []}
                ],
                "component_edges": [],
                "empty_types": ["com.example.mini:mini-article"],
            },
            "content-survey",
        )
        validate(
            {
                "schema": "99x.extract.content-survey-resolved/v1",
                "samplePerType": 3,
                "templatesFolder": "/en/_templates",
                "rule": ["customized", "explicit", "implicit"],
                "templatesFolderOrder": [],
                "templates": [],
                "types": [{"type": "portal:site", "totalCount": 0, "sampled": []}],
            },
            "content-survey-resolved",
        )
        validate(
            {
                "schema": "99x.extract.page-templates/v1",
                "templatesFolder": "/en/_templates",
                "total": 0,
                "templates": [],
            },
            "page-templates",
        )

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

    def test_field_defs_are_identical_across_schemas(self) -> None:
        stems = (
            "inventory", "content-model", "component-map", "project-map",
            "route-map", "surface",
        )
        first = load_schema(stems[0])["$defs"]
        for stem in stems[1:]:
            defs = load_schema(stem)["$defs"]
            self.assertEqual(defs["field"], first["field"], stem)
            self.assertEqual(defs["occurrences"], first["occurrences"], stem)

    def test_unobserved_status_is_valid_in_every_map(self) -> None:
        surface = {
            "id": "a:part:p", "kind": "part", "entry": "x", "status": "unobserved",
        }
        validate({"schema": "99x.extract.project-map/v1", "surfaces": [surface]}, "project-map")
        validate({"schema": "99x.extract.component-map/v1", "components": [surface]}, "component-map")
        validate({"schema": "99x.extract.content-model/v1", "types": [surface]}, "content-model")
        validate({"schema": "99x.extract.route-map/v1", "routes": [surface]}, "route-map")

    def test_nested_field_validates_and_bad_field_fails(self) -> None:
        field = {
            "name": "opts", "type": "option-set",
            "occurrences": {"min": 0, "max": 1},
            "options": [{"name": "a", "items": [{"mixin": "app:m"}]}],
        }
        surface = {
            "id": "a:content-type:t", "kind": "content-type", "entry": "x",
            "status": "live", "fields": [field],
        }
        validate({"schema": "99x.extract.content-model/v1", "types": [surface]}, "content-model")
        surface["fields"] = [{"label": "no name or mixin"}]
        with self.assertRaises(ExtractkitError):
            validate({"schema": "99x.extract.content-model/v1", "types": [surface]}, "content-model")


if __name__ == "__main__":
    unittest.main()
