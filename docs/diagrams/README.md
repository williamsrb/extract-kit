# Diagrams (internal)

Public docs embed only the PNGs. `.excalidraw` files stay here; do not
link them from README, `docs/flow.md`, or the skill. Text uses
Excalifont (`fontFamily: 5`).

## Combined canvas (primary)

The three operator panels on one board. The README diagram (how it
works) is separate.

- [extractkit-flow.excalidraw](extractkit-flow.excalidraw)
- [extractkit-flow.png](extractkit-flow.png)
- Open: <https://excalidraw.com/#json=z5ERedSKICYHPJpD2kz1s,TGDd0RgMKkPK6LJ35nvSyg>

## Individual

| Panel | Source | Preview | Open |
| --- | --- | --- | --- |
| How it works (README) | [how-it-works.excalidraw](how-it-works.excalidraw) | [how-it-works.png](how-it-works.png) | [excalidraw.com](https://excalidraw.com/#json=YOYx5xxsGH4sCXVr_60dG,ftJ1lMLobKgKIBvTbubRig) |
| Operator path | [operator-path.excalidraw](operator-path.excalidraw) | [operator-path.png](operator-path.png) | [excalidraw.com](https://excalidraw.com/#json=wgM7IlNk94rTPeSScP48a,OkNnYG3bDm0NH95uf-Itew) |
| Phases | [phases.excalidraw](phases.excalidraw) | [phases.png](phases.png) | [excalidraw.com](https://excalidraw.com/#json=dylOuyIv5hbBYLR35NX58,XuJnf_Ubw76bj7sefLwPPQ) |
| Sidecar lineage | [sidecar-lineage.excalidraw](sidecar-lineage.excalidraw) | [sidecar-lineage.png](sidecar-lineage.png) | [excalidraw.com](https://excalidraw.com/#json=vodirsb4Bz7qhr-IzMZ_A,vi3SC-JeP707JmO7sO8i7w) |

The excalidraw.com links above open the version of 1 Oct, which matches
the local `.excalidraw` and `.png` files: the eight-phase pipeline with the
`agent` phase, the optional slots, `inventory/templates.json`, `rules/` and
`business/BUSINESS.md`. After a rebuild, re-export them with
`excalidraw-cli export <file>.excalidraw`; that uploads the drawing.

`*.elements.json` is the CLI input used to rebuild a `.excalidraw` file
(`excalidraw-cli create <file>.elements.json -o <file>.excalidraw`).
