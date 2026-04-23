from mous_pipeline.m1_events.parse import parse_events


def test_parse_events_counts(events_tsv_path):
    trials = parse_events(str(events_tsv_path))
    assert len(trials) == 220
    assert int((trials["condition"] == "ZINNEN").sum()) == 110
    assert int((trials["condition"] == "WOORDEN").sum()) == 110
    assert abs(float(trials.iloc[0]["onset"]) - 12.3641666666667) < 1e-6
    assert {"block_id", "pos_in_block"}.issubset(trials.columns)
    assert int(trials["block_id"].min()) == 0
    assert int(trials["pos_in_block"].min()) == 0
