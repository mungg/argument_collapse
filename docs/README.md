# Argument Collapse — companion site

Static HTML site for the paper *Argument Collapse: LLMs Flatten Long-Form Public Debate* (Kim, Chang, Pham, Iyyer, 2026).

## Structure

- `index.html` — catalog of all 256 debates (195 NYT + 61 Boston Review) with venue/question-type/topic filters and search
- `main_argument.html` — flat browse of main-argument clusters (currently 3 toy debates with full cluster annotation)
- `sub_argument.html` — flat browse of every sub-argument with its parent cluster (3 toy debates)
- `cleanliness.html`, `silicon_valley.html`, `boston_review_civil_liberties.html` — three fully-built debate matrix pages with cluster annotations
- `cleanliness_arg_<N>.html`, `silicon_valley_arg_<N>.html`, `boston_review_civil_liberties_arg_<N>.html` — 24 cluster detail pages (8 per toy debate)
- `debate_nyt_<id>.html`, `debate_br_<id>.html` — 253 thin debate-detail pages for all remaining debates (title, question, source counts). Cluster matrix is being built in a follow-up pass.

## Generation

`_gen_full_site.py` reads `data/nyt/debates.jsonl.gz` and `data/br/debates.jsonl.gz`, generates `index.html` and all 253 thin detail pages. Re-run after data updates.

## Local preview

```
python3 -m http.server 8765 --directory docs
# then visit http://localhost:8765/
```

## Hosting on GitHub Pages

1. Push this folder to the `main` branch.
2. On GitHub: **Settings → Pages → Build and deployment**
   - Source: **Deploy from a branch**
   - Branch: **main**, folder **/docs**
   - Save
3. The site goes live at `https://<your-github-username>.github.io/argument_collapse/`

The empty `.nojekyll` file disables Jekyll preprocessing so the raw HTML is served as-is.

## Hosting alternatives

- **Netlify** — drag-and-drop the `docs/` folder onto netlify.com/drop
- **Vercel** — `vercel docs/` from CLI
- **Cloudflare Pages** — connect this repo, set build output to `docs/`
