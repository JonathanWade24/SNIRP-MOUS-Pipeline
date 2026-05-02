from pathlib import Path

from mous_pipeline.m0_intake.repocli_rdr import (
    build_repocli_get_command,
    is_valid_mous_subject_id,
    parse_subjects_arg,
    remote_subject_path,
)


def test_remote_subject_path():
    assert remote_subject_path("dccn/DSC_3011020.09_236_v1", "A2002") == "dccn/DSC_3011020.09_236_v1/sub-A2002"
    assert remote_subject_path("dccn/DSC_3011020.09_236_v1/", "sub-A2003") == "dccn/DSC_3011020.09_236_v1/sub-A2003"


def test_build_repocli_get_command():
    cmd = build_repocli_get_command(remote_path="dccn/DSC_3011020.09_236_v1/sub-A2002", local_dir="/tmp/mous")
    assert cmd[0] == "repocli"
    assert cmd[1] == "get"
    assert cmd[2] == "dccn/DSC_3011020.09_236_v1/sub-A2002"
    assert Path(cmd[3]) == Path("/tmp/mous").resolve()


def test_subject_arg_helpers_normalize_and_validate():
    assert parse_subjects_arg("A2002, sub-A2003\nA2004") == ["A2002", "A2003", "A2004"]
    assert is_valid_mous_subject_id("sub-A2002")
    assert not is_valid_mous_subject_id("sub-not-a-subject")
