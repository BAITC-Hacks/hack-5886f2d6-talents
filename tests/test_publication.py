import errno
import hashlib
import json
from types import SimpleNamespace

import pytest

import pipeline


class Clock:
    def __init__(self):
        self.elapsed = 0.0
        self.sleeps = []
        self.wall_shift = 0.0

    def monotonic(self):
        return self.elapsed

    def time(self):
        return 1000.0 + self.elapsed + self.wall_shift

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.elapsed += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(pipeline, 'time', clock)
    return clock


@pytest.fixture
def bundle(tmp_path):
    stage, out = tmp_path/'stage', tmp_path/'out'
    stage.mkdir()
    out.mkdir()
    for directory, version in ((stage, 'new'), (out, 'old')):
        for name in ('a.csv', 'z.json'):
            (directory/name).write_text(f'{version} {name}', encoding='utf-8')
        manifest = {
            'status': 'complete',
            'artifact_sha256': {
                name: hashlib.sha256((directory/name).read_bytes()).hexdigest()
                for name in ('a.csv', 'z.json')
            },
        }
        (directory/'run_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return stage, out


def windows_error(code):
    error = OSError(errno.EACCES, 'simulated Windows replace error')
    error.winerror = code
    return error


@pytest.mark.parametrize('winerror', [5, 32, 33])
def test_temporary_lock_succeeds_and_manifest_is_last(bundle, clock, monkeypatch, winerror):
    stage, out = bundle
    expected = {path.name: path.read_bytes() for path in stage.iterdir()}
    previous_manifest = (out/'run_manifest.json').read_bytes()
    replace = pipeline.os.replace
    attempts = []

    def temporary_lock(source, destination):
        attempts.append(source.name)
        if len(attempts) <= 2:
            raise windows_error(winerror)
        if source.name != 'run_manifest.json':
            assert (out/'run_manifest.json').read_bytes() == previous_manifest
        else:
            assert all((out/name).read_bytes() == expected[name] for name in ('a.csv', 'z.json'))
        replace(source, destination)

    monkeypatch.setattr(pipeline.os, 'replace', temporary_lock)
    pipeline.publish_outputs(stage, out, clock.time() + 30)
    assert attempts == ['a.csv', 'a.csv', 'a.csv', 'z.json', 'run_manifest.json']
    assert clock.sleeps == [0.05, 0.05]
    assert {path.name: path.read_bytes() for path in out.iterdir()} == expected
    assert not list(stage.iterdir())


def test_permanent_lock_returns_nonzero_without_committing_partial_bundle(bundle, clock, monkeypatch, capsys):
    stage, out = bundle
    previous_manifest = (out/'run_manifest.json').read_bytes()
    replace = pipeline.os.replace
    attempts = []

    def permanent_lock(source, destination):
        attempts.append((source.name, clock.monotonic()))
        if source.name == 'z.json':
            raise windows_error(32)
        replace(source, destination)

    monkeypatch.setattr(pipeline.os, 'replace', permanent_lock)
    monkeypatch.setattr(pipeline, 'parse_args', lambda: SimpleNamespace(worker=True))
    monkeypatch.setattr(pipeline, 'worker', lambda args: pipeline.publish_outputs(stage, out, clock.time() + 30))
    assert pipeline.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'publication time budget exhausted' in captured.err
    assert clock.elapsed == pytest.approx(3.0)
    assert all(at < 3.0 for _, at in attempts)
    assert all(name != 'run_manifest.json' for name, _ in attempts)
    assert (stage/'run_manifest.json').is_file()
    assert (out/'run_manifest.json').read_bytes() == previous_manifest
    # The old manifest cannot authenticate the partially replaced bundle.
    old_hash = json.loads(previous_manifest)['artifact_sha256']['a.csv']
    assert hashlib.sha256((out/'a.csv').read_bytes()).hexdigest() != old_hash


@pytest.mark.parametrize('error', [
    OSError(errno.EIO, 'I/O error'),
    PermissionError(errno.EACCES, 'permission denied without Windows error code'),
    windows_error(112),  # Disk full is not a sharing/access lock.
])
def test_other_io_errors_fail_immediately(bundle, clock, monkeypatch, error):
    stage, out = bundle
    calls = []

    def fail(source, destination):
        calls.append(source.name)
        raise error

    monkeypatch.setattr(pipeline.os, 'replace', fail)
    with pytest.raises(OSError) as raised:
        pipeline.publish_outputs(stage, out, clock.time() + 30)
    assert raised.value is error
    assert calls == ['a.csv']
    assert clock.sleeps == []
    assert clock.elapsed == 0


def test_retries_use_only_remaining_supervisor_time(bundle, clock, monkeypatch):
    stage, out = bundle
    deadline = clock.time() + 0.12
    calls = []

    def locked(source, destination):
        assert clock.time() < deadline
        calls.append(source.name)
        raise windows_error(33)

    monkeypatch.setattr(pipeline.os, 'replace', locked)
    with pytest.raises(TimeoutError, match='publication time budget exhausted'):
        pipeline.publish_outputs(stage, out, deadline)
    assert len(calls) == 3
    assert clock.sleeps == pytest.approx([0.05, 0.05, 0.02])
    assert clock.elapsed == pytest.approx(0.12)


@pytest.mark.parametrize('remaining', [0, -1])
def test_expired_supervisor_deadline_prevents_any_publication(bundle, clock, monkeypatch, remaining):
    stage, out = bundle
    calls = []
    monkeypatch.setattr(pipeline.os, 'replace', lambda *args: calls.append(args))
    with pytest.raises(TimeoutError):
        pipeline.publish_outputs(stage, out, clock.time() + remaining)
    assert calls == []
    assert clock.sleeps == []


def test_budget_is_shared_across_files_and_includes_replace_time(bundle, clock, monkeypatch):
    stage, out = bundle
    replace = pipeline.os.replace
    calls = []

    def slow_then_locked(source, destination):
        calls.append((source.name, clock.monotonic()))
        if source.name == 'a.csv':
            clock.elapsed += 2.9
            replace(source, destination)
        else:
            raise windows_error(5)

    monkeypatch.setattr(pipeline.os, 'replace', slow_then_locked)
    with pytest.raises(TimeoutError):
        pipeline.publish_outputs(stage, out, clock.time() + 30)
    assert clock.elapsed == pytest.approx(3.0)
    assert sum(clock.sleeps) == pytest.approx(0.1)
    assert calls[0][0] == 'a.csv'
    assert all(name == 'z.json' and at < 3 for name, at in calls[1:])
    assert (stage/'run_manifest.json').is_file()


def test_successful_replace_cannot_start_next_file_after_budget(bundle, clock, monkeypatch):
    stage, out = bundle
    calls = []
    replace = pipeline.os.replace

    def slow(source, destination):
        calls.append(source.name)
        clock.elapsed += 3.0
        replace(source, destination)

    monkeypatch.setattr(pipeline.os, 'replace', slow)
    with pytest.raises(TimeoutError):
        pipeline.publish_outputs(stage, out, clock.time() + 30)
    assert calls == ['a.csv']
    assert clock.sleeps == []


def test_supervisor_deadline_is_rechecked_after_clock_advance(bundle, clock, monkeypatch):
    stage, out = bundle
    calls = []

    def locked(source, destination):
        calls.append(source.name)
        clock.wall_shift += 30
        raise windows_error(32)

    monkeypatch.setattr(pipeline.os, 'replace', locked)
    with pytest.raises(TimeoutError):
        pipeline.publish_outputs(stage, out, clock.time() + 10)
    assert calls == ['a.csv']
    assert clock.sleeps == []


def test_slow_final_manifest_returns_nonzero_without_claiming_success(bundle, clock, monkeypatch, capsys):
    stage, out = bundle
    expected = {path.name: path.read_bytes() for path in stage.iterdir()}
    replace = pipeline.os.replace
    calls = []

    def slow_manifest(source, destination):
        calls.append(source.name)
        if source.name == 'run_manifest.json':
            clock.elapsed += 3.1
        replace(source, destination)

    def publish_and_report(args):
        pipeline.publish_outputs(stage, out, clock.time() + 30)
        print(json.dumps({'status': 'complete'}))

    monkeypatch.setattr(pipeline.os, 'replace', slow_manifest)
    monkeypatch.setattr(pipeline, 'parse_args', lambda: SimpleNamespace(worker=True))
    monkeypatch.setattr(pipeline, 'worker', publish_and_report)
    assert pipeline.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'publication time budget exhausted at run_manifest.json' in captured.err
    assert calls == ['a.csv', 'z.json', 'run_manifest.json']
    assert clock.elapsed == pytest.approx(3.1)
    assert clock.sleeps == []
    # The completed OS call may already have committed a coherent new bundle.
    assert {path.name: path.read_bytes() for path in out.iterdir()} == expected
    assert not list(stage.iterdir())
