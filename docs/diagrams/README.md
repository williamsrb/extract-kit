# Diagrams (internal)

Public docs embed only the PNGs. `.excalidraw` files stay here; do not
link them from README, `docs/flow.md`, or the skill. Text uses
Excalifont (`fontFamily: 5`).

## Combined canvas (primary)

The three operator panels on one board. The README diagram (how it
works) is separate.

- [extractkit-flow.excalidraw](extractkit-flow.excalidraw)
- [extractkit-flow.png](extractkit-flow.png)
- Open: <https://excalidraw.com/#json=6-TLkVHFtcFsOdu2SnPAv,1OAU_2Y7QgzlPyzxMz5YLg>

## Individual

| Panel | Source | Preview | Open |
| --- | --- | --- | --- |
| How it works (README) | [how-it-works.excalidraw](how-it-works.excalidraw) | [how-it-works.png](how-it-works.png) | [excalidraw.com](https://excalidraw.com/#json=o9zG0zTSVg-NamGCX9Tz_,6FSR0oZx0VYtFEf3x-aB6g) |
| Operator path | [operator-path.excalidraw](operator-path.excalidraw) | [operator-path.png](operator-path.png) | [excalidraw.com](https://excalidraw.com/#json=qIn2T2V-OfcKpRX4tqu3H,V5haRMT4Ev5ye3eF-H_qCA) |
| Phases | [phases.excalidraw](phases.excalidraw) | [phases.png](phases.png) | [excalidraw.com](https://excalidraw.com/#json=eRGwNtfQ5sY0UAYzBYS_V,HJNbLSp8UhIlst2aI_etRA) |
| Sidecar lineage | [sidecar-lineage.excalidraw](sidecar-lineage.excalidraw) | [sidecar-lineage.png](sidecar-lineage.png) | [excalidraw.com](https://excalidraw.com/#json=UvvF83s1VV1I9kTmPCUF6,AxqM3oRh5s2dEBqi8WFOFg) |

The local `.excalidraw` and `.png` files show the nine-phase pipeline (2 Oct):
the `context` phase, the `context.exclude` and `context.live_config` AI
steps in the operator path, the Phases panel as a grid of required input,
optional input and expected output per phase, and the overlay
`context/profile.yaml` with `live-config-candidates` in the lineage. The
excalidraw.com links above open this version. After a rebuild, re-export
with `excalidraw-cli export <file>.excalidraw` (that uploads the drawing)
and replace the links.

`*.elements.json` is the CLI input used to rebuild a `.excalidraw` file
(`excalidraw-cli create <file>.elements.json -o <file>.excalidraw`).
