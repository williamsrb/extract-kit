# Diagrams (internal)

Public docs embed only the PNGs. `.excalidraw` files stay here; do not
link them from README, `docs/flow.md`, or the skill. Text uses
Excalifont (`fontFamily: 5`).

## Combined canvas (primary)

The three operator panels on one board. The README diagram (how it
works) is separate.

- [extractkit-flow.excalidraw](extractkit-flow.excalidraw)
- [extractkit-flow.png](extractkit-flow.png)
- Open: <https://excalidraw.com/#json=oK0DVjLYk2phcLutujaPl,KAE14loHojvfXm2FEvC4lw>

## Individual

| Panel | Source | Preview | Open |
| --- | --- | --- | --- |
| How it works (README) | [how-it-works.excalidraw](how-it-works.excalidraw) | [how-it-works.png](how-it-works.png) | [excalidraw.com](https://excalidraw.com/#json=YOYx5xxsGH4sCXVr_60dG,ftJ1lMLobKgKIBvTbubRig) |
| Operator path | [operator-path.excalidraw](operator-path.excalidraw) | [operator-path.png](operator-path.png) | [excalidraw.com](https://excalidraw.com/#json=wgM7IlNk94rTPeSScP48a,OkNnYG3bDm0NH95uf-Itew) |
| Phases | [phases.excalidraw](phases.excalidraw) | [phases.png](phases.png) | [excalidraw.com](https://excalidraw.com/#json=a_poeddoORZxRZhJWM4ty,xRDrzYeL5nj8upjuWxRq0w) |
| Sidecar lineage | [sidecar-lineage.excalidraw](sidecar-lineage.excalidraw) | [sidecar-lineage.png](sidecar-lineage.png) | [excalidraw.com](https://excalidraw.com/#json=RhQ0pidCfr0mNlHqTqS1V,YjdnU-m2wg8GKwTm53qpzQ) |

The excalidraw.com links for Phases, Sidecar lineage and the combined
canvas open the 1 Oct version with `spec.review`. It matches the local
`.excalidraw` and `.png` files: the eight-phase pipeline with the `agent`
phase and its optional tasks (`spec.enrich`, `spec.review`), the optional
slots, `inventory/templates.json`, `rules/`, `business/BUSINESS.md` and the
optional, never-promoted `reports/spec-review.md`. The How it works and
Operator path links are unchanged. After a rebuild, re-export with
`excalidraw-cli export <file>.excalidraw`; that uploads the drawing.

`*.elements.json` is the CLI input used to rebuild a `.excalidraw` file
(`excalidraw-cli create <file>.elements.json -o <file>.excalidraw`).
