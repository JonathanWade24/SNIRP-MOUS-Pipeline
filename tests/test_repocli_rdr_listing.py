from mous_pipeline.m0_intake.repocli_rdr import build_repocli_ls_command, parse_repocli_ls_subjects


def test_parse_repocli_ls_subjects_extracts_unique_subject_ids() -> None:
    output = """
    drwxr-xr-x  user  group  sub-A2002
    drwxr-xr-x  user  group  sub-A2003
    drwxr-xr-x  user  group  sub-A2002
    """
    subjects = parse_repocli_ls_subjects(output)
    assert subjects == ["A2002", "A2003"]


def test_build_repocli_ls_command_normalizes_path() -> None:
    cmd = build_repocli_ls_command("/dccn/DSC_3011020.09_236_v1/")
    assert cmd == ["repocli", "ls", "dccn/DSC_3011020.09_236_v1"]
