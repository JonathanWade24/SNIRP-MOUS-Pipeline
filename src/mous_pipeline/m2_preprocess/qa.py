"""Module 2 QA helpers."""


def summarize_ica(ica) -> dict:
    return {"n_components": int(ica.n_components_), "excluded_components": list(ica.exclude)}
