from mous_pipeline.m5_source.forward import resolve_trans_path


def test_resolve_trans_path_keeps_fsaverage():
    assert resolve_trans_path("fsaverage", "A2002") == "fsaverage"


def test_resolve_trans_path_expands_subject_placeholder():
    assert (
        resolve_trans_path("derivatives/coreg/sub-{subject}-trans.fif", "A2002")
        == "derivatives/coreg/sub-A2002-trans.fif"
    )


def test_resolve_trans_path_expands_bids_subject_placeholder():
    assert (
        resolve_trans_path("derivatives/coreg/{subject_bids}-trans.fif", "sub-A2002")
        == "derivatives/coreg/sub-A2002-trans.fif"
    )
