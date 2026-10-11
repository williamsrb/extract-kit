# Diagrams (internal)

Public docs embed only the PNGs. `.excalidraw` files stay here; do not
link them from README, `docs/flow.md`, or the skill. Text uses
Excalifont (`fontFamily: 5`).

## Combined canvas (primary)

The five panels on one board: install, operator path, headless pipeline,
phases and sidecar lineage. The README diagram (how it works) is separate.

- [extractkit-flow.excalidraw](extractkit-flow.excalidraw)
- [extractkit-flow.png](extractkit-flow.png)
- Open: <https://excalidraw.com/#json=IBLcsmCPlmpWWmRILzJ0g,1zNVD4W5VdpoFJZK4MW_EA>

## Individual

| Panel | Source | Preview | Open |
| --- | --- | --- | --- |
| How it works (README) | [how-it-works.excalidraw](how-it-works.excalidraw) | [how-it-works.png](how-it-works.png) | [excalidraw.com](https://excalidraw.com/#json=1-6DIeWyd2eQx74Shu-9t,HQvL8ONoUdMYYvEBzoW1_Q) |
| Install and where to run | [install-layout.excalidraw](install-layout.excalidraw) | [install-layout.png](install-layout.png) | [excalidraw.com](https://excalidraw.com/#json=9Dk7QZDtitrYmc3ilCcnN,dYvpLG2ZC1ZgkqCdDnwxVA) |
| Operator path | [operator-path.excalidraw](operator-path.excalidraw) | [operator-path.png](operator-path.png) | [excalidraw.com](https://excalidraw.com/#json=fXtHJiJyBDf68ug2fCrw_,_TQ4U1RT3bvkU7ui17FUFw) |
| Headless pipeline | [headless-pipeline.excalidraw](headless-pipeline.excalidraw) | [headless-pipeline.png](headless-pipeline.png) | [excalidraw.com](https://excalidraw.com/#json=8P5xm-r-bPkaFe7Knz4MA,554qMhqsvSPVS30e6WM_fA) |
| Phases | [phases.excalidraw](phases.excalidraw) | [phases.png](phases.png) | [excalidraw.com](https://excalidraw.com/#json=Pa04noZrhvMeTdmZQyAA0,Kh5a0iBbraTTPbexJFsZfg) |
| Sidecar lineage | [sidecar-lineage.excalidraw](sidecar-lineage.excalidraw) | [sidecar-lineage.png](sidecar-lineage.png) | [excalidraw.com](https://excalidraw.com/#json=gExpUIIHk30Esv8wERH7U,uGOrwq9HcFucXVsa9Zxv2Q) |

The local `.excalidraw` and `.png` files show the detached install, the
kit-repo guard and the headless pipeline (2 Oct), on top of the nine-phase
pipeline: the `context` phase, the `context.exclude` and
`context.live_config` AI steps in the operator path, the Phases panel as a
grid of required input, optional input and expected output per phase, and
the overlay `context/profile.yaml` with `live-config-candidates` in the
lineage. Since 6 Oct they also show the `constitution` agent task and the
headless sidecar under `<source>/extract/`. Since 7 Oct the headless pipeline and the combined
canvas also show the `assets` stage (twelve stages) and the rule that a
missing attachment skips stages instead of failing the run. Their
excalidraw.com links were re-exported that day; the other four open the
6 Oct version. Since 9 Oct the install panel shows devkit as a
prerequisite, the Phases panel lists it in the preflight input, and the
headless agent loop names the devkit wrapper (`claude-extract`). Since
10 Oct `spec.enrich` is gone: the agent stage, the operator path and the
Phases panel list `domain.behavior`, `donotport` and `spec.capabilities`;
synthesis writes `spec-kit/evidence/` and `domain/packet/`; the lineage shows
`business/capabilities.json`, `domain/`, `reports/do-not-port.md` and the
capability specs that promote copies; `check` names its spec and secret
gates. Every drawing but the install panel was re-exported that day; the
install panel opens the 9 Oct version. On 11 Oct the devkit text in the install panel and the combined canvas
reads "dev-kit"; their PNGs were re-rendered and the excalidraw.com links
stay as they were. After a rebuild, re-export with
`excalidraw-cli export <file>.excalidraw` (that uploads the drawing) and
replace the links.

The combined canvas holds the same panels as the individual files, shifted
into containers with a title, a subtitle and a divider (element ids carry a
panel prefix). A change to a panel has to be made in both.

`*.elements.json` is the CLI input used to rebuild a `.excalidraw` file
(`excalidraw-cli create <file>.elements.json -o <file>.excalidraw`).
