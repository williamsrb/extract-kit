# Diagrams (internal)

Public docs embed only the PNGs. `.excalidraw` files stay here; do not
link them from README, `docs/flow.md`, or the skill. Text uses
Excalifont (`fontFamily: 5`).

## Combined canvas (primary)

The five panels on one board: install, operator path, headless pipeline,
phases and sidecar lineage. The README diagram (how it works) is separate.

- [extractkit-flow.excalidraw](extractkit-flow.excalidraw)
- [extractkit-flow.png](extractkit-flow.png)
- Open: <https://excalidraw.com/#json=6-TLkVHFtcFsOdu2SnPAv,1OAU_2Y7QgzlPyzxMz5YLg>
  (older version: three panels, no install or headless)

## Individual

| Panel | Source | Preview | Open |
| --- | --- | --- | --- |
| How it works (README) | [how-it-works.excalidraw](how-it-works.excalidraw) | [how-it-works.png](how-it-works.png) | [excalidraw.com](https://excalidraw.com/#json=o9zG0zTSVg-NamGCX9Tz_,6FSR0oZx0VYtFEf3x-aB6g) (older) |
| Install and where to run | [install-layout.excalidraw](install-layout.excalidraw) | [install-layout.png](install-layout.png) | not uploaded |
| Operator path | [operator-path.excalidraw](operator-path.excalidraw) | [operator-path.png](operator-path.png) | [excalidraw.com](https://excalidraw.com/#json=qIn2T2V-OfcKpRX4tqu3H,V5haRMT4Ev5ye3eF-H_qCA) (older) |
| Headless pipeline | [headless-pipeline.excalidraw](headless-pipeline.excalidraw) | [headless-pipeline.png](headless-pipeline.png) | not uploaded |
| Phases | [phases.excalidraw](phases.excalidraw) | [phases.png](phases.png) | [excalidraw.com](https://excalidraw.com/#json=eRGwNtfQ5sY0UAYzBYS_V,HJNbLSp8UhIlst2aI_etRA) |
| Sidecar lineage | [sidecar-lineage.excalidraw](sidecar-lineage.excalidraw) | [sidecar-lineage.png](sidecar-lineage.png) | [excalidraw.com](https://excalidraw.com/#json=UvvF83s1VV1I9kTmPCUF6,AxqM3oRh5s2dEBqi8WFOFg) |

The local `.excalidraw` and `.png` files show the detached install, the
kit-repo guard and the headless pipeline (2 Oct), on top of the nine-phase
pipeline: the `context` phase, the `context.exclude` and
`context.live_config` AI steps in the operator path, the Phases panel as a
grid of required input, optional input and expected output per phase, and
the overlay `context/profile.yaml` with `live-config-candidates` in the
lineage. The excalidraw.com links marked older open the previous version;
the new panels have none. After a rebuild, re-export with
`excalidraw-cli export <file>.excalidraw` (that uploads the drawing) and
replace the links.

The combined canvas holds the same panels as the individual files, shifted
into containers with a title, a subtitle and a divider (element ids carry a
panel prefix). A change to a panel has to be made in both.

`*.elements.json` is the CLI input used to rebuild a `.excalidraw` file
(`excalidraw-cli create <file>.elements.json -o <file>.excalidraw`).
