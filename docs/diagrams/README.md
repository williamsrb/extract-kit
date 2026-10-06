# Diagrams (internal)

Public docs embed only the PNGs. `.excalidraw` files stay here; do not
link them from README, `docs/flow.md`, or the skill. Text uses
Excalifont (`fontFamily: 5`).

## Combined canvas (primary)

The five panels on one board: install, operator path, headless pipeline,
phases and sidecar lineage. The README diagram (how it works) is separate.

- [extractkit-flow.excalidraw](extractkit-flow.excalidraw)
- [extractkit-flow.png](extractkit-flow.png)
- Open: <https://excalidraw.com/#json=godyjfyegTD-tHJ2ce9hx,sjA2-mke61vnSfixBn14KQ>

## Individual

| Panel | Source | Preview | Open |
| --- | --- | --- | --- |
| How it works (README) | [how-it-works.excalidraw](how-it-works.excalidraw) | [how-it-works.png](how-it-works.png) | [excalidraw.com](https://excalidraw.com/#json=CgbajXnyzM7-CHPKY6VNP,FXaohl_SOOt34Qp99684Zw) |
| Install and where to run | [install-layout.excalidraw](install-layout.excalidraw) | [install-layout.png](install-layout.png) | [excalidraw.com](https://excalidraw.com/#json=A54UdRnExYtH8yUY_5Gwr,xhsHN4ksTQgTkkteitFZyA) |
| Operator path | [operator-path.excalidraw](operator-path.excalidraw) | [operator-path.png](operator-path.png) | [excalidraw.com](https://excalidraw.com/#json=jdPyvKFgw96D-qEDHCCNw,lYai_UblZcwkcVdencu5Nw) |
| Headless pipeline | [headless-pipeline.excalidraw](headless-pipeline.excalidraw) | [headless-pipeline.png](headless-pipeline.png) | [excalidraw.com](https://excalidraw.com/#json=vU-66wik4PIZ3-kfIpMhB,xDjmNsADB7Ci3gMCB3eIvw) |
| Phases | [phases.excalidraw](phases.excalidraw) | [phases.png](phases.png) | [excalidraw.com](https://excalidraw.com/#json=75q1UyfrmmlQ9hUQE092V,6IHLa5VQArfFq3jxwX9Auw) |
| Sidecar lineage | [sidecar-lineage.excalidraw](sidecar-lineage.excalidraw) | [sidecar-lineage.png](sidecar-lineage.png) | [excalidraw.com](https://excalidraw.com/#json=UZgDhl2KG8Kkdha2bzID3,EduNWGcD_lwBxxiY3LAtNQ) |

The local `.excalidraw` and `.png` files show the detached install, the
kit-repo guard and the headless pipeline (2 Oct), on top of the nine-phase
pipeline: the `context` phase, the `context.exclude` and
`context.live_config` AI steps in the operator path, the Phases panel as a
grid of required input, optional input and expected output per phase, and
the overlay `context/profile.yaml` with `live-config-candidates` in the
lineage. Since 6 Oct they also show the `constitution` agent task, the
`spec.enrich` run in the headless agent stage, and the headless sidecar under
`<source>/extract/`. Every excalidraw.com link opens the 6 Oct version.
After a rebuild, re-export with
`excalidraw-cli export <file>.excalidraw` (that uploads the drawing) and
replace the links.

The combined canvas holds the same panels as the individual files, shifted
into containers with a title, a subtitle and a divider (element ids carry a
panel prefix). A change to a panel has to be made in both.

`*.elements.json` is the CLI input used to rebuild a `.excalidraw` file
(`excalidraw-cli create <file>.elements.json -o <file>.excalidraw`).
