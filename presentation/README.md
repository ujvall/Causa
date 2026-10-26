# CAUSA final-review presentation

| File | Purpose |
|---|---|
| `CAUSA_Final_Presentation.pptx` | Editable deck: 20 slides (18 main + related-work slide + reference appendix), speaker notes on every slide, native shapes, table and chart |
| `CAUSA_Final_Presentation.pdf` | PDF export (LibreOffice render) |
| `build_deck.js` | Generator for the deck (pptxgenjs) |
| `capture_studio.py` | Captures real CAUSA Studio screenshots by driving the actual window |
| `make_crops.py` | Cuts the detail views used on the Studio slide |
| `assets/` | Screenshots and crops |

## Open and edit

Open the `.pptx` in PowerPoint (or LibreOffice Impress). Slide 1 has editable placeholders for student name, registration number, school and guide: they are not filled in because they cannot be verified from the repository. Speaker notes (with likely questions) are in the notes pane.

## Regenerate

```bash
npm install pptxgenjs            # node 18+
node presentation/build_deck.js  # writes presentation/CAUSA_Final_Presentation.pptx
```

Optional: set `PPTX_APPLY_THEME` to a script that exports `applyTheme(deckPath, THEME)` to write theme colours into the deck. The deck renders correctly without it.

PDF: `soffice --headless --convert-to pdf --outdir presentation presentation/CAUSA_Final_Presentation.pptx`

Screenshots (needs Python 3.11+ with Tk, a C compiler, ImageMagick `import`, and a real or virtual display):

```bash
xvfb-run -a -s "-screen 0 2400x1350x24" python3 presentation/capture_studio.py
python3 presentation/make_crops.py
```

## Provenance of the numbers

- Outputs on the explain, impact and what-if slides are real runtime output from `examples/pricing.cau`, identical to `docs/demonstration.md`.
- Benchmark numbers are the recorded Windows 11 results in `docs/evaluation.md`; they were not re-run for the deck.
- Test counts: 205 passing (recorded Windows / MSYS2 UCRT64 GCC 16.1 run). The current suite has 257 tests: those 205 plus 52 Studio tests (counted from `tests/`).
- Studio screenshots were captured on Linux (Xvfb, Python 3.12, Tk, GCC 13.3), the environment available when the deck was built. Replace them with Windows captures if preferred.
- References were checked against publisher, library or official pages; see the appendix slide notes.

## Design and fonts

Matte black canvas (`09090A`), neutral grey text, cyan as the one chrome accent; graph and code colours are unchanged. Type is Inter (headings and body) with Consolas for code. Install Inter (free, rsms.me/inter) before presenting; without it PowerPoint substitutes another sans font and some text may wrap differently. The bundled PDF is rendered with Inter.
