import asyncio

import pytest

from external_sandbox_container.backend import AppleContainerBackend, Process, parse_mounts


def test_mount_modes_and_aliases(tmp_path):
    directory = tmp_path / 'a directory'
    directory.mkdir()
    mounts = parse_mounts([('project=' + str(directory), 'ro')], True)
    backend = AppleContainerBackend(mounts)
    command = backend.command()
    assert command[command.index('--network') + 1] == 'none'
    assert command[command.index('--cap-drop') + 1] == 'ALL'
    assert f'type=bind,source={directory},target=/mnt/project,readonly' in command
    assert f'type=bind,source={directory},target={directory},readonly' in command
    assert '--tty' not in command
    assert backend.info()['network'] is False


def test_overlapping_ro_rw_mounts_rejected(tmp_path):
    (tmp_path / 'child').mkdir()
    with pytest.raises(ValueError, match='overlap'):
        parse_mounts([(f'parent={tmp_path}', 'rw'), (f'child={tmp_path}/child', 'ro')])
    alias = tmp_path / 'alias'
    alias.symlink_to(tmp_path / 'child')
    with pytest.raises(ValueError, match='overlap'):
        parse_mounts([(f'a={alias}', 'rw'), (f'b={tmp_path}/child', 'ro')])


def test_reserved_aliases_and_mount_injection_rejected(tmp_path):
    with pytest.raises(ValueError, match='system path'):
        parse_mounts([('project=/tmp', 'rw')], True)
    directory = tmp_path / 'x,readonly'
    directory.mkdir()
    with pytest.raises(ValueError, match='commas'):
        parse_mounts([('project=' + str(directory), 'rw')])


async def test_slow_process_consumer_is_bounded_and_killed():
    class Backend:
        def __init__(self):
            self.killed = []
        async def _terminate_quietly(self, ident):
            self.killed.append(ident)
    backend = Backend()
    process = Process(backend, '1')
    for _ in range(65):
        process.feed({'type': 'stdout', 'data': 'YQ=='})
    await asyncio.sleep(0)
    assert process.events.qsize() == 1
    assert (await process.events.get())['type'] == 'error'
    assert backend.killed == ['1']
