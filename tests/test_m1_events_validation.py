import pandas as pd
import pytest

from mous_pipeline.m1_events.parse import parse_events


def test_parse_events_requires_columns(tmp_path):
    path = tmp_path / "events.tsv"
    pd.DataFrame({"onset": [0.1], "type": ["Nothing"], "value": ["1 Audio onset"]}).to_csv(path, sep="\t", index=False)
    with pytest.raises(ValueError, match="missing required columns"):
        parse_events(str(path))


def test_parse_events_requires_both_conditions(tmp_path):
    path = tmp_path / "events.tsv"
    df = pd.DataFrame(
        {
            "onset": [1.0, 2.0],
            "sample": [100, 200],
            "type": ["Picture", "Nothing"],
            "value": ["ZINNEN", "1 Audio onset"],
        }
    )
    df.to_csv(path, sep="\t", index=False)
    with pytest.raises(ValueError, match="Did not observe both required condition block markers"):
        parse_events(str(path), strict=True)
