"""Argument Collapse — analysis pipeline for LLM convergence on public debate.

Public submodules:
    annotate    LLM judge and extraction pipelines
                (main argument, sub argument, Toulmin, stance).
    cluster     Union-find argument clustering primitives.
    metric      Within-group unique rate U_m and recovery rates.
    data        Cohort and essay loaders.
    inference   Provider-side LLM clients (OpenAI, Anthropic, Vertex,
                OpenRouter). Imported lazily so installs without a given
                client still work for unrelated calls.
"""

__version__ = "0.1.0"
