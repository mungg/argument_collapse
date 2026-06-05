# Argument Collapse — companion site

Static HTML site for the paper *Argument Collapse: LLMs Flatten Long-Form Public Debate* (Kim, Chang, Pham, Iyyer, 2026).

## Structure

- `index.html` — landing page with the debate catalog
- `main_argument.html` — flat browse of all main-argument clusters across debates
- `sub_argument.html` — flat browse of every sub-argument with its parent cluster
- `cleanliness.html`, `silicon_valley.html`, `boston_review_civil_liberties.html` — per-debate matrix pages (humans × 5 LLM families × vanilla/diversified)
- `<debate>_arg_<N>.html` — per-cluster detail pages showing every essay (human or LLM) with its sub-arguments

Only three debates are fully built out as the visible toy slice; placeholder cards on `index.html` are marked **Preview only · detail page coming**.

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
