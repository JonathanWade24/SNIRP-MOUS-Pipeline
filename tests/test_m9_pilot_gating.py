from mous_pipeline.pilot_gating import evaluate_pilot_gate


def test_pilot_gating_marginal():
    metrics = {
        "n_zinnen": 110,
        "dci_zinnen": 0.0185,
        "dci_rest": 0.0183,
        "p_task_vs_rest": 0.4542,
        "p_rayleigh_zinnen": 0.32836,
    }
    gate = evaluate_pilot_gate(metrics)
    assert gate["verdict"] == "MARGINAL"
    assert gate["n_pass"] == 2
