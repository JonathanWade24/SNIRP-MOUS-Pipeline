from mous_pipeline.m0_intake.cyberduck import build_duck_download_command


def test_build_duck_download_command():
    cmd = build_duck_download_command(
        protocol="sftp",
        host="example.org",
        remote_root="/mous",
        subject="A2003",
        local_root=".",
        username="alice",
    )
    assert cmd[0] == "duck"
    assert "--download" in cmd
    assert "sftp://example.org/mous/sub-A2003.tar.gz" in cmd
