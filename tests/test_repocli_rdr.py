from pathlib import Path

from mous_pipeline.m0_intake.repocli_rdr import build_repocli_get_command, remote_subject_path


def test_remote_subject_path():
    assert remote_subject_path("dccn/DSC_3011020.09_236_v1", "A2002") == "dccn/DSC_3011020.09_236_v1/sub-A2002"
    assert remote_subject_path("dccn/DSC_3011020.09_236_v1/", "sub-A2003") == "dccn/DSC_3011020.09_236_v1/sub-A2003"


def test_build_repocli_get_command():
    cmd = build_repocli_get_command(remote_path="dccn/DSC_3011020.09_236_v1/sub-A2002", local_dir="/tmp/mous")
    assert cmd[0] == "repocli"
    assert cmd[1] == "get"
    assert cmd[2] == "dccn/DSC_3011020.09_236_v1/sub-A2002"
    assert Path(cmd[3]) == Path("/tmp/mous").resolve()
