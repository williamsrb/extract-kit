# Diagrams (internal)

Public docs embed only the PNGs. `.excalidraw` files stay here; do not
link them from README, `docs/flow.md`, or the skill. Text uses
Excalifont (`fontFamily: 5`).

## Combined canvas (primary)

All three panels on one board.

- [extractkit-flow.excalidraw](extractkit-flow.excalidraw)
- [extractkit-flow.png](extractkit-flow.png)
- Open: <https://excalidraw.com/#json=HdG0QtExrbHqFzudyWc2W,ZakomTdCK53BknXacLfOBw>

## Individual

| Panel | Source | Preview | Open |
| --- | --- | --- | --- |
| Operator path | [operator-path.excalidraw](operator-path.excalidraw) | [operator-path.png](operator-path.png) | [excalidraw.com](https://excalidraw.com/#json=VRj9O1Kx8rbQ9gI03nDO7,ByEfpTzNTB_39NdHCgPGpA) |
| Phases | [phases.excalidraw](phases.excalidraw) | [phases.png](phases.png) | [excalidraw.com](https://excalidraw.com/#json=NRLOROenD9RN5s4QLz0tW,Dtsrb_MDsWYh1kx8-kid2g) |
| Sidecar lineage | [sidecar-lineage.excalidraw](sidecar-lineage.excalidraw) | [sidecar-lineage.png](sidecar-lineage.png) | [excalidraw.com](https://excalidraw.com/#json=Ws3smI7T3XBd9sySeZxFH,Ie0BSD-OhQeRdDseTAyqIQ) |

The excalidraw.com links above open the version of 1 Oct, which matches
the local `.excalidraw` and `.png` files: the eight-phase pipeline with the
`agent` phase, the optional slots, `inventory/templates.json`, `rules/` and
`business/BUSINESS.md`. After a rebuild, re-export them with
`excalidraw-cli export <file>.excalidraw`; that uploads the drawing.

`*.elements.json` is the CLI input used to rebuild a `.excalidraw` file
(`excalidraw-cli create <file>.elements.json -o <file>.excalidraw`).
