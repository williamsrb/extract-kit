# Diagrams (internal)

Public docs embed only the PNGs. `.excalidraw` files stay here; do not
link them from README, `docs/flow.md`, or the skill. Text uses
Excalifont (`fontFamily: 5`).

## Combined canvas (primary)

All three panels on one board.

- [extractkit-flow.excalidraw](extractkit-flow.excalidraw)
- [extractkit-flow.png](extractkit-flow.png)
- Open: <https://excalidraw.com/#json=79R1U12tn5I2A0icEZbs5,SHpOOWQLDT61gnWzzVZAgg>

## Individual

| Panel | Source | Preview | Open |
| --- | --- | --- | --- |
| Operator path | [operator-path.excalidraw](operator-path.excalidraw) | [operator-path.png](operator-path.png) | [excalidraw.com](https://excalidraw.com/#json=nhNPoCuk2FLDzwu7eaI3c,io38t6jmI9EtUVsKkuWf5w) |
| Phases | [phases.excalidraw](phases.excalidraw) | [phases.png](phases.png) | [excalidraw.com](https://excalidraw.com/#json=j5J82TCjXLe_Uo6PmGLnz,AKNMOM7bhLmjDci48WC36g) |
| Sidecar lineage | [sidecar-lineage.excalidraw](sidecar-lineage.excalidraw) | [sidecar-lineage.png](sidecar-lineage.png) | [excalidraw.com](https://excalidraw.com/#json=kKbFm8pV1lJ6UdesJsZFA,T6FzGi0gW1NQF-RM2WCbDg) |

The excalidraw.com links above open the version of 30 Sep. The local
`.excalidraw` and `.png` files were rebuilt for the optional slots and the
`unobserved` status. Sidecar lineage also shows `controllers.json`,
`baseline/` and `reports/xp8-compat.md` (1 Oct). On 1 Oct they were
rebuilt again for the `inventory.templates` and `rules.view` slots,
`inventory/templates.json` and `rules/`, and then for the eight-phase
pipeline (the `agent` phase) and `business/BUSINESS.md`. Re-export the links with
`excalidraw-cli export` when you want them current; that uploads the
drawing, so it is not done here.

`*.elements.json` is the CLI input used to rebuild a `.excalidraw` file
(`excalidraw-cli create <file>.elements.json -o <file>.excalidraw`).
