import json
import uuid

from janitor import __main__ as cli


def test_execution_name_provides_stable_run_identity(monkeypatch, capsys, policy, cloud, store):
    monkeypatch.setattr(cli, "load_policy", lambda: policy)
    cloud.store = lambda: store
    monkeypatch.setattr(cli, "Azure", lambda policy: cloud)
    monkeypatch.setattr("sys.argv", ["azure-janitor", "--dry-run", "--max-actions", "1"])
    monkeypatch.setenv("CONTAINER_APP_JOB_EXECUTION_NAME", "janitor-unique-execution")
    assert cli.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["run_id"] == uuid.uuid5(uuid.NAMESPACE_URL, "janitor-unique-execution").hex
    assert report["dry_run"] and report["event"] == "janitor_run"
    assert report["report_uri"].startswith(policy.blob_url)
    assert not cloud.actions
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["duplicate"]


def test_failure_output_does_not_include_sensitive_exception_text(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["azure-janitor"])

    def fail():
        raise ValueError("private-token")

    monkeypatch.setattr(cli, "load_policy", fail)
    assert cli.main() == 1
    output = capsys.readouterr().out
    assert "private-token" not in output
    assert json.loads(output)["error"] == "ValueError"
