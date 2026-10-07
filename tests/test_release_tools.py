"""Release tooling: next version, release notes, source version, build self test"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))


def run_git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_DATE": "2026-10-01T10:00:00", "GIT_COMMITTER_DATE": "2026-10-01T10:00:00"})


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """Empty repo with version file, as working directory"""
    repo = tmp_path / "repo"
    os.makedirs(repo / "tinypedal")
    (repo / "tinypedal" / "version.py").write_text('__version__ = "0.10.0"\n', encoding="utf-8")
    run_git(repo, "init", "-q", "-b", "master")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test")
    run_git(repo, "config", "tag.gpgsign", "false")
    run_git(repo, "config", "commit.gpgsign", "false")
    monkeypatch.chdir(repo)
    return repo


def commit(repo, title):
    with open(repo / "file.txt", "a", encoding="utf-8") as file:
        file.write(title + "\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", title)


def test_next_version_bumps(git_repo):
    from next_version import next_version, write_version

    commit(git_repo, "Fix first thing")
    assert next_version() == "0.10.0"  # first release: version file
    run_git(git_repo, "tag", "v0.10.0")
    assert next_version() == ""  # nothing since last release
    commit(git_repo, "Fix overlay text")
    assert next_version() == "0.10.1"
    commit(git_repo, "Add new overlay")
    assert next_version() == "0.11.0"
    assert next_version("major") == "1.0.0"
    assert next_version("patch") == "0.10.1"
    write_version("0.11.0")
    assert '__version__ = "0.11.0"' in (git_repo / "tinypedal" / "version.py").read_text(encoding="utf-8")


def test_release_tags_by_version_and_reachable(git_repo):
    from gen_release_notes import release_tags

    commit(git_repo, "Fix a")
    run_git(git_repo, "tag", "v0.9.0")
    commit(git_repo, "Fix b")
    run_git(git_repo, "tag", "v0.10.0")  # creator date equal to v0.9.0: version order decides
    run_git(git_repo, "checkout", "-q", "-b", "side", "v0.9.0")
    commit(git_repo, "Fix c")
    run_git(git_repo, "tag", "v0.9.1")
    run_git(git_repo, "checkout", "-q", "master")
    assert [name for name, _ in release_tags()] == ["v0.10.0", "v0.9.0"]  # v0.9.1 not reachable from master


def test_changelog_check_and_image_pin(git_repo, monkeypatch):
    import gen_release_notes

    (git_repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 0.11.0 (2026-10-05)\n\n![Shot](https://raw.githubusercontent.com/Keenny38/"
        "ModernTinyPedals/master/docs/changes/shot.png)\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["gen_release_notes.py", "--check-changelog", "0.11.0"])
    assert gen_release_notes.main() == 0
    monkeypatch.setattr(sys, "argv", ["gen_release_notes.py", "--check-changelog", "v0.12.0"])
    assert gen_release_notes.main() == 1
    pinned = gen_release_notes.pin_image_urls(gen_release_notes.changelog_section("0.11.0"), "abc123")
    assert "/ModernTinyPedals/abc123/docs/changes/shot.png" in pinned
    assert "/master/" not in pinned


def commit_file(repo, path, title):
    """Commit a change of one file (path relative to repo)"""
    target = repo / path
    os.makedirs(target.parent, exist_ok=True)
    with open(target, "a", encoding="utf-8") as file:
        file.write(title + "\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", title)


def test_documentation_commits_do_not_release(git_repo):
    from next_version import is_docs_only, next_version

    commit(git_repo, "Fix first thing")
    run_git(git_repo, "tag", "v0.10.0")
    commit_file(git_repo, "docs/wiki/Home.md", "Add wiki home page")
    commit_file(git_repo, "CONTRIBUTING.md", "Update CONTRIBUTING.md")
    commit_file(git_repo, "CHANGELOG.fr.md", "Fix French changelog")
    commit_file(git_repo, "docs/changes/shot.png", "Add before/after image")
    assert next_version() == ""  # documentation only: no release
    assert next_version("patch") == "0.10.1"  # asked by hand
    commit_file(git_repo, "tinypedal/version.py", "Fix overlay text")
    assert next_version() == "0.10.1"  # "Add wiki" does not make a minor release
    commit_file(git_repo, "docs/wiki/Usage.md", "Add usage page")
    assert not is_docs_only("HEAD~1") and is_docs_only("HEAD")


def test_documentation_paths():
    from next_version import DOCS_ONLY

    for path in ("docs/wiki/Home.md", "docs/wiki/_Sidebar.md", "README.md", "CHANGELOG.md", "CHANGELOG.fr.md",
                 "CONTRIBUTING.md", "SECURITY.md", "docs/ROADMAP.md", "docs/changelog/0.19.0-chat.png"):
        assert DOCS_ONLY.match(path), path
    for path in ("tinypedal/update.py", "docs/customization.md", "docs/contributors.md", "NOTICE.md",
                 ".github/workflows/build-release.yml", "tinypedal/README.md", "images/icon.png"):
        assert not DOCS_ONLY.match(path), path


def test_translated_changelog_check(git_repo, monkeypatch):
    import gen_release_notes

    (git_repo / "CHANGELOG.md").write_text("# Changelog\n\n## 0.11.0 (2026-10-05)\n\n- New.\n", encoding="utf-8")
    (git_repo / "CHANGELOG.fr.md").write_text("# Journal\n\n## 0.10.0 (2026-10-01)\n\n- Ancien.\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["gen_release_notes.py", "--check-changelog", "0.11.0"])
    assert gen_release_notes.main() == 0
    monkeypatch.setattr(sys, "argv", ["gen_release_notes.py", "--check-changelog", "0.11.0",
                                      "--changelog", "CHANGELOG.fr.md"])
    assert gen_release_notes.main() == 1  # French section missing: warned by release workflow


def test_source_version(monkeypatch, tmp_path):
    from tinypedal import version

    def fake_run(output):
        def run(*args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout=output)
        return run

    monkeypatch.setattr(version.subprocess, "run", fake_run("v0.19.1-3-g8a0f9f3\n"))
    assert version.source_version(("0.10.0", "")) == ("0.19.1", "+3.g8a0f9f3")
    monkeypatch.setattr(version.subprocess, "run", fake_run("v0.19.1-0-g8a0f9f3\n"))
    assert version.source_version(("0.10.0", "")) == ("0.19.1", "")
    monkeypatch.setattr(version.subprocess, "run", fake_run("garbage"))
    assert version.source_version(("0.10.0", "")) == ("0.10.0", "")

    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(version.subprocess, "run", missing_git)
    assert version.source_version(("0.10.0", "")) == ("0.10.0", "")


def test_local_build_after_release_is_not_outdated(monkeypatch):
    from tinypedal import version, version_check

    assert not version_check.is_new_version((0, 19, 1), (0, 19, 1), "+3.g8a0f9f3")
    assert version_check.is_new_version((0, 19, 1), (0, 19, 1), "beta")  # pre-release of that version
    assert version_check.is_new_version((0, 19, 2), (0, 19, 1), "+3.g8a0f9f3")
    monkeypatch.setattr(version, "__version__", "0.19.1")
    monkeypatch.setattr(version, "DEVELOPMENT", "+3.g8a0f9f3")
    assert version_check.tinypedal() == "0.19.1+3.g8a0f9f3"
    monkeypatch.setattr(version, "DEVELOPMENT", "")
    assert version_check.tinypedal() == "0.19.1"


def test_self_test_checks():
    from tinypedal import self_test

    assert "data files" in self_test.check_data_files()
    assert "QML pages compiled" in self_test.check_qml_pages()
    assert "modules imported" in self_test.check_modules()
    assert "skipped" in self_test.check_vr_overlay()  # not a frozen build


def test_self_test_worker_process():
    from tinypedal import self_test

    assert self_test.check_worker_process() == "worker process answered"


def test_self_test_report(monkeypatch, tmp_path):
    from tinypedal import self_test

    def broken():
        raise FileNotFoundError("fonts/*.ttf")

    monkeypatch.setattr(self_test, "CHECKS", (("Good", lambda: "fine"), ("Broken", broken)))
    report_file = tmp_path / "report.txt"
    assert self_test.run_self_test(str(report_file)) == 1
    report = report_file.read_text(encoding="utf-8")
    assert "PASS Good: fine" in report
    assert "FAIL Broken" in report and "fonts/*.ttf" in report
    assert "1/2 checks passed" in report
    monkeypatch.setattr(self_test, "CHECKS", (("Good", lambda: "fine"),))
    assert self_test.run_self_test() == 0
