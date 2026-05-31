# Argument Collapse

Code for the paper *Argument Collapse: LLMs Flatten Long-Form Public Debate*.

This repository contains the analysis pipeline used to measure how LLM-generated
argumentative essays collapse onto a narrower range of main arguments,
supporting reasons, and paragraph-level structures than comparable human
essays.

## Installation

```bash
git clone https://github.com/mungg/argument_collapse.git
cd argument_collapse
pip install -e .
```

The package targets Python ≥ 3.10. LLM providers (OpenAI, Anthropic, Google
Vertex, OpenRouter) are pulled in as optional clients; install only the ones
you plan to call.

## Repository structure

```
src/argument_collapse/   # main package
├── annotate/            # LLM judge / extraction pipelines
│   ├── main_arg.py      # main-argument pairwise judge
│   ├── sub_arg.py       # sub-argument pairwise judge
│   ├── toulmin.py       # main/sub-argument extraction
│   └── stance.py        # stance labeling
├── cluster.py           # union-find argument clustering
├── metric.py            # within-group unique rate U_m, recovery rates
├── data.py              # cohort / essay loaders
└── inference/           # LLM provider wrappers
prompts/                 # judge & extraction prompts (Markdown)
configs/                 # paper run configurations (YAML)
scripts/                 # CLI entry points
```

## Reproducing paper numbers

The dataset (annotations, LLM-generated essays, cohort metadata) is released
separately. Once it is downloaded under `data/`, the paper's main numbers can
be regenerated via:

```bash
python -m argument_collapse.metric --config configs/paper_nyt.yaml
python -m argument_collapse.metric --config configs/paper_br.yaml
```

A coordinated entrypoint is provided at `scripts/reproduce_paper.sh`.

## Data release

Original human essays from *NYT Room for Debate* and *Boston Review* are not
redistributed here because the publishers retain copyright. We release URLs,
parsed metadata, and our derived annotations (extracted main and sub
arguments, pairwise overlap labels, stance labels, cluster assignments)
alongside the LLM-generated essays produced under each provider's research
terms. See the data release note (forthcoming) for a download link.

## License

Code is released under the [MIT License](LICENSE). Derived annotations and
LLM-generated essays released with this project follow the same MIT terms;
the original NYT and BR essays remain under their respective publishers'
copyright.

## Citation

```bibtex
@inproceedings{argument_collapse_2026,
  title = {Argument Collapse: LLMs Flatten Long-Form Public Debate},
  author = {{TBD}},
  booktitle = {Proceedings of the Annual Meeting of the Association for Computational Linguistics},
  year = {2026},
}
```
