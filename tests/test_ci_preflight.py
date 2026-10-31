"""CI preflight & dev lock (release 0.28.0 post-mortem): same tool versions as Checks, Checks before a release"""

import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import check
import ci_preflight


def read(name: str) -> str:
    with open(os.path.join(ROOT, name), encoding="utf-8") as file:
        return file.read()


def pins(text: str) -> dict[str, str]:
    found = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", line)
        if match:
            found[match.group(1).lower().replace("_", "-")] = match.group(2)
    return found


def names(text: str) -> set[str]:
    return {re.split(r"[<>=;\s\[]", line, maxsplit=1)[0].lower().replace("_", "-")
            for line in text.splitlines() if line.strip() and not line.startswith(("#", "-"))}


def run_git(repo, *args) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Repo with one commit, as ROOT of check.py & ci_preflight.py"""
    path = tmp_path / "repo"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    run_git(path, "config", "user.email", "test@example.com")
    run_git(path, "config", "user.name", "Test")
    run_git(path, "config", "commit.gpgsign", "false")
    (path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (path / "code.py").write_text("a = 1\n", encoding="utf-8")
    (path / "CHANGELOG.md").write_text("# Changelog\n\n## 0.1.0\n\n- first\n", encoding="utf-8")
    run_git(path, "add", "-A")
    run_git(path, "commit", "-q", "-m", "first")
    monkeypatch.setattr(check, "ROOT", str(path))
    monkeypatch.setattr(ci_preflight, "ROOT", str(path))
    return path


def test_dev_lock_pins_every_requirement_at_release_versions():
    lock = pins(read("requirements-dev-lock.txt"))
    assert names(read("requirements-dev.txt")) <= set(lock)
    assert names(read("requirements.txt")) <= set(lock)
    for name, version in pins(read("requirements-lock.txt")).items():
        assert lock.get(name, version) == version, f"requirements-dev-lock.txt: {name} not {version}, regenerate it"


def test_lock_mismatches_only_for_this_platform(tmp_path):
    from importlib import metadata

    lock = tmp_path / "lock.txt"
    lock.write_text(f"# comment\npytest=={metadata.version('pytest')}\npluggy==0.0.1\n"
                    "colorama==0.0.1 ; sys_platform == 'nowhere'\nnot-a-package-np==1.0\n", encoding="utf-8")
    assert check.lock_mismatches(str(lock)) == [
        f"pluggy {metadata.version('pluggy')} (Checks: 0.0.1)", "not-a-package-np not installed (Checks: 1.0)"]


def test_snapshot_takes_working_tree_without_touching_it(repo):
    (repo / "code.py").write_text("a = 2\n", encoding="utf-8")
    (repo / "new.py").write_text("b = 1\n", encoding="utf-8")
    (repo / "debug.log").write_text("ignored\n", encoding="utf-8")
    run_git(repo, "add", "new.py")  # staged file stays staged
    (repo / "other.py").write_text("c = 1\n", encoding="utf-8")
    head = run_git(repo, "rev-parse", "HEAD")
    status = run_git(repo, "status", "--porcelain")

    sha, untracked = ci_preflight.snapshot()
    assert run_git(repo, "status", "--porcelain") == status
    assert run_git(repo, "rev-parse", "HEAD") == head
    assert run_git(repo, "rev-parse", f"{sha}^") == head
    assert run_git(repo, "show", f"{sha}:code.py") == "a = 2"
    assert set(run_git(repo, "ls-tree", "--name-only", sha).splitlines()) == {
        ".gitignore", "CHANGELOG.md", "code.py", "new.py", "other.py"}
    assert untracked == ["other.py"]  # new.py is in the index already
    assert not os.path.exists(os.path.join(repo, run_git(repo, "rev-parse", "--git-path", "preflight-index")))


def test_doc_only_paths():
    assert ci_preflight.doc_only(["CHANGELOG.md", "CHANGELOG.fr.md", "README.md", "docs/changes/a.png",
                                  "docs/wiki/Home.md", "docs/wiki/sub/page.md"])
    assert ci_preflight.doc_only([])
    assert not ci_preflight.doc_only(["CHANGELOG.md", "neopedal/app.py"])
    assert not ci_preflight.doc_only(["docs/customization.md"])  # option help generated from it


def test_release_push_needs_passed_checks(repo, monkeypatch):
    base = run_git(repo, "rev-parse", "HEAD")
    run_git(repo, "update-ref", "refs/remotes/origin/master", base)
    (repo / "code.py").write_text("a = 3\n", encoding="utf-8")
    run_git(repo, "commit", "-q", "-am", "work")
    monkeypatch.delenv("NEOPEDAL_SKIP_PREFLIGHT", raising=False)
    monkeypatch.setattr(ci_preflight, "passed_base", lambda sha: None)
    assert check.release_without_checks() == ""  # no release section: any push

    with open(repo / "CHANGELOG.md", "a", encoding="utf-8") as file:
        file.write("\n## 0.2.0\n\n- second\n")
    run_git(repo, "commit", "-q", "-am", "Release 0.2.0")
    assert check.new_release_versions(base, "HEAD") == ["0.2.0"]
    assert "0.2.0: Checks never passed" in check.release_without_checks()

    monkeypatch.setattr(ci_preflight, "passed_base", lambda sha: base)
    assert check.release_without_checks() == ""
    monkeypatch.setattr(ci_preflight, "passed_base", lambda sha: None)
    monkeypatch.setenv("NEOPEDAL_SKIP_PREFLIGHT", "1")
    assert check.release_without_checks() == ""

    def offline(sha):
        raise SystemExit("gh: not logged in")

    monkeypatch.delenv("NEOPEDAL_SKIP_PREFLIGHT")
    monkeypatch.setattr(ci_preflight, "passed_base", offline)
    assert "Checks state not read (gh: not logged in)" in check.release_without_checks()


def test_passed_base_accepts_documentation_changes_only(repo, monkeypatch):
    base = run_git(repo, "rev-parse", "HEAD")
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## 0.2.0\n", encoding="utf-8")
    run_git(repo, "commit", "-q", "-am", "doc")
    doc = run_git(repo, "rev-parse", "HEAD")
    (repo / "code.py").write_text("a = 4\n", encoding="utf-8")
    run_git(repo, "commit", "-q", "-am", "code")
    code = run_git(repo, "rev-parse", "HEAD")
    runs = [{"headSha": "0" * 40, "event": "push"}, {"headSha": base, "event": "pull_request"},
            {"headSha": base, "event": "workflow_dispatch"}]
    monkeypatch.setattr(ci_preflight, "gh_json", lambda *args: runs)
    monkeypatch.setattr(ci_preflight, "git", lambda *args, **kwargs: "")  # no fetch of the unknown commit
    assert ci_preflight.passed_base(doc) == base
    assert ci_preflight.passed_base(code) is None
