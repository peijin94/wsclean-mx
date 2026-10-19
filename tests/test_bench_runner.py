# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Runner harness fixtures only: no science binaries, data, or results."""
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(os.environ.get('BENCH_SCRIPT_ROOT', Path(__file__).resolve().parents[1]))


class BenchRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='bench-runner-', dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'bench').mkdir()
        for name in ('run.sh', 'ab.sh', 'aa.sh', 'snapshot.sh', 'common.sh', 'profile.sh'):
            if (SOURCE / 'bench' / name).exists():
                shutil.copy2(SOURCE / 'bench' / name, self.root / 'bench' / name)
        self.env = dict(os.environ, REPS='1', COOL='0', CONTAINER_CPUS='1')
        self.env['HARNESS_CALLS'] = str(self.root / 'calls')
        self.fake = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
with open(os.environ['HARNESS_CALLS'], 'a') as f:
    f.write(json.dumps({'binary': sys.argv[0], 'args': sys.argv[1:], 'cwd': os.getcwd()}) + '\\n')
if os.environ.get('HARNESS_REMOVE_LOG'):
    (Path(sys.argv[sys.argv.index('-name') + 1]).parent / 'wsclean.log').unlink()
if 'HARNESS_TIME_TEXT' in os.environ:
    output = Path(sys.argv[sys.argv.index('-name') + 1]).parent / 'time.txt'
    output.unlink()
    output.write_text(os.environ['HARNESS_TIME_TEXT'])
if 'HARNESS_TIME_MAP' in os.environ:
    mapping = json.loads(os.environ['HARNESS_TIME_MAP'])
    name = Path(sys.argv[0]).parent.name
    if name in mapping:
        entry = mapping[name]
        if isinstance(entry, list):
            state = Path(os.environ['HARNESS_CALLS'] + '.' + name)
            index = int(state.read_text()) if state.exists() else 0
            state.write_text(str(index + 1))
            entry = entry[index % len(entry)]
        output = Path(sys.argv[sys.argv.index('-name') + 1]).parent / 'time.txt'
        output.unlink()
        output.write_text(entry)
if '-version' in sys.argv:
    print('WSClean version HARNESS FIXTURE')
print(os.environ.get('HARNESS_TIMING', 'Inversion: 00:00:01.250, prediction: 00:00:00.500, deconvolution: 00:00:00.125'))
'''
        for v in ('one', 'two', 'three', 'V_1-a.b'):
            self.binary(self.root / 'bench' / 'bin' / v / 'wsclean')

    def binary(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.fake)
        path.chmod(0o755)

    def run_script(self, script, *args, **env):
        return subprocess.run(['bash', str(self.root / 'bench' / script), *args],
                              env=dict(self.env, **env), text=True, capture_output=True, timeout=15)

    def wall_time_fixture(self):
        # The macOS sandbox denies time -l's sysctl; Linux time lacks -l.
        # Adapt only the sandbox copy to real /usr/bin/time -p. No fake time
        # or invented measurements: these are harness fixtures, never science.
        script = self.root / 'bench/run.sh'
        script.write_text(script.read_text().replace('/usr/bin/time -lp', '/usr/bin/time -p'))

    def calls(self):
        return [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]

    def rejected(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr.lower())

    def test_existing_run_preserves_sentinel(self):
        out = self.root / 'bench/out/keep/one'
        out.mkdir(parents=True)
        sentinel = out / 'sentinel'
        sentinel.write_text('keep me')
        result = self.run_script('run.sh', 'one', 'keep')
        self.assertTrue(sentinel.exists(), 'existing run sentinel was deleted')
        self.assertEqual(sentinel.read_text(), 'keep me')
        self.rejected(result, 'exist')
        self.assertFalse((self.root / 'calls').exists())

    def test_existing_snapshot_preserves_sentinel(self):
        build = self.root / 'fixture-build'
        self.binary(build / 'wsclean')
        (build / 'libschaapthreading.dylib').write_text('fixture library')
        out = self.root / 'bench/bin/frozen'
        out.mkdir()
        sentinel = out / 'sentinel'
        sentinel.write_text('keep snapshot')
        result = self.run_script('snapshot.sh', str(build), 'frozen')
        self.assertTrue(sentinel.exists(), 'existing snapshot sentinel was deleted')
        self.rejected(result, 'exist')

    def test_required_arguments_and_slugs(self):
        for script in ('run.sh', 'ab.sh', 'snapshot.sh'):
            for args in ((), ('one',)):
                with self.subTest(script=script, args=args):
                    self.rejected(self.run_script(script, *args), 'usage:')
        for slug in ('', '.', '..', '.hidden', '../escape', 'a/b', 'a b', 'é', 'a\\b'):
            for script, args in (
                ('run.sh', (slug, 'tag')), ('run.sh', ('one', slug)),
                ('ab.sh', (slug, 'one')), ('ab.sh', ('tag', slug)),
                ('snapshot.sh', (str(self.root), slug)),
            ):
                with self.subTest(script=script, args=args):
                    self.rejected(self.run_script(script, *args), 'invalid')
        self.assertFalse((self.root / 'bench/out').exists())

    def test_unavailable_variants_have_no_output_side_effects(self):
        for v in ('unknown', 'mx', 'upstream'):
            for script, args in (('run.sh', (v, 'unavailable')), ('ab.sh', ('unavailable', 'one,' + v))):
                with self.subTest(script=script, v=v):
                    self.rejected(self.run_script(script, *args), 'variant')
                    self.assertFalse((self.root / 'bench/out').exists())
                    self.assertFalse((self.root / 'calls').exists())

    def test_unsafe_wsclean_options_rejected_before_output(self):
        for option in ('predict', 'update-model-required', 'name', 'temp-dir', 'store-imaging-weights'):
            for prefix in ('-', '--'):
                for script, args in (('run.sh', ('one', 'unsafe')), ('ab.sh', ('unsafe', 'one'))):
                    with self.subTest(script=script, option=prefix + option):
                        result = self.run_script(script, *args, prefix + option, 'fixture')
                        self.rejected(result, 'forbidden')
                        self.assertFalse((self.root / 'bench/out').exists())
                        self.assertFalse((self.root / 'calls').exists())

    def test_no_reorder_rejected_before_output_or_binary_call(self):
        for option in ('-no-reorder', '--no-reorder'):
            for script in ('run.sh', 'ab.sh'):
                tag = f'direct-{script}-{len(option)}'
                args = ('one', tag) if script == 'run.sh' else (tag, 'one')
                with self.subTest(script=script, option=option):
                    result = self.run_script(
                        script, *args, '-no-update-model-required', option,
                        '-niter', '1', '-mgain', '0.8', 'fixture.ms')
                    self.rejected(result, 'forbidden')
                    self.assertIn(option, result.stderr)
                    self.assertFalse((self.root / 'bench/out').exists())
                    self.assertFalse((self.root / 'calls').exists())

    def test_symlinked_output_ancestors_refused(self):
        target = self.root / 'escape'
        target.mkdir()
        (target / 'sentinel').write_text('untouched')
        link = self.root / 'bench/out'
        link.symlink_to(target, target_is_directory=True)
        for script, args in (('run.sh', ('one', 'escape')), ('ab.sh', ('escape', 'one'))):
            with self.subTest(script=script):
                self.rejected(self.run_script(script, *args), 'symlink')
                self.assertEqual(sorted(p.name for p in target.iterdir()), ['sentinel'])
        link.unlink()
        bin_dir = self.root / 'bench/bin'
        bin_dir.rename(self.root / 'saved-bin')
        bin_dir.symlink_to(target, target_is_directory=True)
        self.rejected(self.run_script('snapshot.sh', str(self.root), 'frozen'), 'symlink')
        self.assertEqual(sorted(p.name for p in target.iterdir()), ['sentinel'])

    def test_ab_rejects_invalid_counts_cooldown_and_variant_list(self):
        cases = [({'REPS': x}, 'one', 'reps') for x in ('', '0', '-1', '1.5', 'nan', 'abc')]
        cases += [({'COOL': x}, 'one', 'cool') for x in ('', '-0.1', 'nan', 'inf', '-inf', 'abc')]
        cases += [({}, x, 'variant') for x in ('', ',one', 'one,', 'one,,two', 'one,one')]
        for env, variants, error in cases:
            with self.subTest(env=env, variants=variants):
                self.rejected(self.run_script('ab.sh', 'invalid', variants, **env), error)
                self.assertFalse((self.root / 'bench/out').exists())
                self.assertFalse((self.root / 'calls').exists())

    def test_ab_alternates_forward_reverse_order(self):
        self.wall_time_fixture()
        result = self.run_script('ab.sh', 'order', 'one,two,three', 'fixture.ms', REPS='3')
        self.assertEqual(result.returncode, 0, result.stderr)
        order = [Path(call['binary']).parent.name for call in self.calls()]
        self.assertEqual(order, ['one', 'two', 'three', 'three', 'two', 'one', 'one', 'two', 'three'])
        with (self.root / 'bench/out/order-ab.tsv').open() as f:
            rows = list(csv.DictReader(f, delimiter='\t'))
        self.assertEqual(list(rows[0]), ['variant', 'rep', 'wall', 'inversion', 'prediction', 'deconvolution',
                                         'instructions_G', 'cycles_G'])
        self.assertEqual([row['variant'] for row in rows], order)
        self.assertEqual([row['rep'] for row in rows], ['1'] * 3 + ['2'] * 3 + ['3'] * 3)
        self.assertEqual([row['inversion'] for row in rows], ['1.250'] * 9)

    def test_ab_rejects_missing_or_malformed_stage_timing(self):
        self.wall_time_fixture()
        for i, line in enumerate((
            'No stage timing here',
            'Inversion: 00:00:01.000, prediction: 00:00:00.500',
            'Inversion: nonsense, prediction: 00:00:00.500, deconvolution: 00:00:00.125',
            'Inversion: 00:99:01, prediction: 00:00:00.500, deconvolution: 00:00:00.125',
        )):
            with self.subTest(line=line):
                result = self.run_script('ab.sh', 'missing' + str(i), 'one', HARNESS_TIMING=line)
                self.rejected(result, 'timing')
                tsv = self.root / ('bench/out/missing' + str(i) + '-ab.tsv')
                self.assertEqual(len(tsv.read_text().splitlines()), 1)

    def test_missing_or_invalid_wall_timing_fails_clearly(self):
        self.wall_time_fixture()
        for i, text in enumerate(('', 'real nan', 'real -1', 'real 1\nreal 2', 'real garbage')):
            for script, args in (('run.sh', ('one', 'wall' + str(i))), ('ab.sh', ('abwall' + str(i), 'one'))):
                with self.subTest(script=script, text=text):
                    self.rejected(self.run_script(script, *args, HARNESS_TIME_TEXT=text), 'timing')
        for tsv in (self.root / 'bench/out').glob('*-ab.tsv'):
            self.assertEqual(len(tsv.read_text().splitlines()), 1)

    def test_ab_preflights_future_run_collisions(self):
        self.wall_time_fixture()
        out = self.root / 'bench/out/planned-r2/two'
        out.mkdir(parents=True)
        (out / 'sentinel').write_text('keep future run')
        result = self.run_script('ab.sh', 'planned', 'one,two', REPS='2')
        self.rejected(result, 'exist')
        self.assertEqual((out / 'sentinel').read_text(), 'keep future run')
        self.assertFalse((self.root / 'bench/out/planned-ab.tsv').exists())
        self.assertFalse((self.root / 'calls').exists())

    def test_multiline_variant_list_rejected_before_output(self):
        for variants in ('one\ntwo', 'one\n', 'one\rtwo'):
            with self.subTest(variants=variants):
                self.rejected(self.run_script('ab.sh', 'multiline', variants), 'invalid')
                self.assertFalse((self.root / 'bench/out').exists())

    def test_run_refuses_collision_created_during_directory_creation(self):
        self.wall_time_fixture()
        out = self.root / 'bench/out/race/one'
        tools = self.root / 'fixture-tools'
        tools.mkdir()
        mkdir = tools / 'mkdir'
        mkdir.write_text('#!/usr/bin/env python3\nimport os, sys\nfrom pathlib import Path\np = Path(os.environ["HARNESS_COLLISION_PATH"])\np.mkdir(parents=True, exist_ok=True)\n(p / "sentinel").write_text("competing run")\nos.execv("/bin/mkdir", ["/bin/mkdir", *sys.argv[1:]])\n')
        mkdir.chmod(0o755)
        result = self.run_script('run.sh', 'one', 'race',
                                 PATH=str(tools) + os.pathsep + self.env['PATH'], HARNESS_COLLISION_PATH=str(out))
        self.rejected(result, 'exist')
        self.assertEqual((out / 'sentinel').read_text(), 'competing run')
        self.assertFalse((self.root / 'calls').exists())

    def test_ab_refuses_tsv_created_after_preflight(self):
        self.wall_time_fixture()
        tsv = self.root / 'bench/out/race-ab.tsv'
        tools = self.root / 'fixture-tools'
        tools.mkdir()
        mkdir = tools / 'mkdir'
        mkdir.write_text('#!/usr/bin/env python3\nimport os, sys\nfrom pathlib import Path\np = Path(os.environ["HARNESS_COLLISION_PATH"])\np.parent.mkdir(parents=True, exist_ok=True)\np.write_text("competing results")\nos.execv("/bin/mkdir", ["/bin/mkdir", *sys.argv[1:]])\n')
        mkdir.chmod(0o755)
        result = self.run_script('ab.sh', 'race', 'one',
                                 PATH=str(tools) + os.pathsep + self.env['PATH'], HARNESS_COLLISION_PATH=str(tsv))
        self.rejected(result, 'exist')
        self.assertEqual(tsv.read_text(), 'competing results')
        self.assertFalse((self.root / 'calls').exists())

    def test_ab_accepts_positive_reps_and_finite_zero_cooldown_forms(self):
        self.wall_time_fixture()
        for i, cool in enumerate(('0', '+0', '-0', '0e0', '.0')):
            with self.subTest(cool=cool):
                result = self.run_script('ab.sh', 'numeric' + str(i), 'one', REPS='01', COOL=cool)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_valid_run_uses_real_time_and_preserves_cli(self):
        self.wall_time_fixture()
        result = self.run_script('run.sh', 'V_1-a.b', 'Tag_1-a.b', '-size', '16', '16', '-save-weights', '--save-uv', 'fixture.ms')
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.root / 'bench/out/Tag_1-a.b/V_1-a.b'
        self.assertRegex((out / 'time.txt').read_text(), r'(?m)^real [0-9]+\.[0-9]+$')
        call, = self.calls()
        self.assertEqual(call['cwd'], str(self.root))
        self.assertEqual(call['args'], ['-no-update-model-required', '-temp-dir', str(out / 'tmp'), '-name', str(out / 'img'), '-size', '16', '16', '-save-weights', '--save-uv', 'fixture.ms'])
        self.assertIn('wall=', result.stdout)
        self.assertTrue((out / 'cmd.txt').is_file())
        self.assertTrue((out / 'wsclean.log').is_file())
        self.assertFalse((out / 'tmp').exists())

    def test_existing_tsv_and_output_symlinks_are_preserved(self):
        target = self.root / 'external'
        target.mkdir()
        sentinel = target / 'sentinel'
        sentinel.write_text('keep target')
        build = self.root / 'fixture-build'
        self.binary(build / 'wsclean')
        (build / 'libschaapthreading.dylib').write_text('fixture library')
        for script, args, output in (
            ('run.sh', ('one', 'leaf'), 'bench/out/leaf/one'),
            ('ab.sh', ('leaf', 'one'), 'bench/out/leaf-ab.tsv'),
            ('snapshot.sh', (str(build), 'leaf'), 'bench/bin/leaf'),
        ):
            out = self.root / output
            out.parent.mkdir(parents=True, exist_ok=True)
            for kind in ('file', 'symlink', 'dangling'):
                with self.subTest(script=script, kind=kind):
                    if kind == 'file':
                        out.write_text('keep output')
                    else:
                        out.symlink_to(target if kind == 'symlink' else target / 'absent')
                    result = self.run_script(script, *args)
                    self.rejected(result, 'exist' if kind == 'file' else 'symlink')
                    if kind == 'file':
                        self.assertEqual(out.read_text(), 'keep output')
                    else:
                        self.assertTrue(out.is_symlink())
                    self.assertEqual(sentinel.read_text(), 'keep target')
                    self.assertEqual(sorted(p.name for p in target.iterdir()), ['sentinel'])
                    out.unlink()
        self.assertFalse((self.root / 'calls').exists())

    def test_snapshot_valid_fixture_preserves_cli(self):
        build = self.root / 'fixture-build'
        self.binary(build / 'wsclean')
        (build / 'libschaapthreading.dylib').write_text('HARNESS fixture library')
        tools = self.root / 'fixture-tools'
        tools.mkdir()
        for name in ('install_name_tool', 'codesign'):
            tool = tools / name
            tool.write_text('#!/bin/sh\nexit 0\n')
            tool.chmod(0o755)
        result = self.run_script('snapshot.sh', str(build), 'Snap_1-a.b', PATH=str(tools) + os.pathsep + self.env['PATH'])
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.root / 'bench/bin/Snap_1-a.b'
        self.assertEqual((out / 'wsclean').read_text(), (build / 'wsclean').read_text())
        self.assertEqual((out / 'libschaapthreading.dylib').read_text(), 'HARNESS fixture library')
        self.assertIn('snapshot Snap_1-a.b', result.stdout)

    def test_variant_paths_must_be_executable_files(self):
        for v, binary, kind in (
            ('mx', 'build-mx/wsclean', 'directory'),
            ('upstream', 'build-upstream/wsclean', 'nonexecutable'),
            ('notbin', 'bench/bin/notbin/wsclean', 'directory'),
        ):
            path = self.root / binary
            path.parent.mkdir(parents=True, exist_ok=True)
            if kind == 'directory':
                path.mkdir()
            else:
                path.write_text('fixture not executable')
                path.chmod(0o644)
            for script, args in (('run.sh', (v, 'unavailable')), ('ab.sh', ('unavailable', 'one,' + v))):
                with self.subTest(v=v, script=script):
                    self.rejected(self.run_script(script, *args), 'variant')
                    self.assertFalse((self.root / 'bench/out').exists())
                    self.assertFalse((self.root / 'calls').exists())

    def test_explicit_zero_and_hour_stage_timings_are_valid(self):
        self.wall_time_fixture()
        result = self.run_script('ab.sh', 'durations', 'one', HARNESS_TIMING='Inversion: 01:02:03.125, prediction: 00:00:00.000, deconvolution: 00:00:00.000')
        self.assertEqual(result.returncode, 0, result.stderr)
        with (self.root / 'bench/out/durations-ab.tsv').open() as f:
            row, = list(csv.DictReader(f, delimiter='\t'))
        self.assertEqual([row[k] for k in ('inversion', 'prediction', 'deconvolution')], ['3723.125', '0.000', '0.000'])

    def test_missing_container_tool_rejected_before_output(self):
        tools = self.root / 'fixture-tools'
        tools.mkdir()
        for name in ('bash', 'dirname', 'python3'):
            (tools / name).symlink_to(shutil.which(name))
        for script, args in (('run.sh', ('linc', 'unavailable')), ('ab.sh', ('unavailable', 'one,linc'))):
            with self.subTest(script=script):
                self.rejected(self.run_script(script, *args, PATH=str(tools)), 'unavailable variant')
                self.assertFalse((self.root / 'bench/out').exists())
                self.assertFalse((self.root / 'calls').exists())

    def test_intermediate_output_ancestors_cannot_escape(self):
        target = self.root / 'escape'
        target.mkdir()
        (target / 'sentinel').write_text('keep target')
        for script, args, ancestor in (
            ('run.sh', ('one', 'nested'), 'bench/out/nested'),
            ('ab.sh', ('nested', 'one'), 'bench/out/nested-r1'),
        ):
            path = self.root / ancestor
            path.parent.mkdir(parents=True, exist_ok=True)
            for kind in ('symlink', 'dangling', 'file'):
                with self.subTest(script=script, kind=kind):
                    if kind == 'file':
                        path.write_text('keep ancestor')
                    else:
                        path.symlink_to(target if kind == 'symlink' else target / 'absent')
                    self.rejected(self.run_script(script, *args), 'unsafe' if kind == 'file' else 'symlink')
                    self.assertFalse((self.root / 'bench/out/nested-ab.tsv').exists())
                    self.assertEqual(sorted(p.name for p in target.iterdir()), ['sentinel'])
                    path.unlink()
        self.assertFalse((self.root / 'calls').exists())

    def test_ab_missing_stage_log_fails_with_timing_diagnostic(self):
        self.wall_time_fixture()
        result = self.run_script('ab.sh', 'nolog', 'one', HARNESS_REMOVE_LOG='1')
        self.rejected(result, 'timing')
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(len((self.root / 'bench/out/nolog-ab.tsv').read_text().splitlines()), 1)

    def time_text(self, wall, instructions=None, cycles=None, user=4.30):
        text = f'real {wall}\nuser {user}\nsys 0.20\n'
        if instructions is not None:
            text += f'   {instructions}  instructions retired\n'
        if cycles is not None:
            text += f'   {cycles}  cycles elapsed\n'
        return text

    def test_run_and_ab_record_optional_hardware_counters(self):
        self.wall_time_fixture()
        text = self.time_text('1.20', 51_590_000_000, 15_300_000_000)
        result = self.run_script('run.sh', 'one', 'counted', HARNESS_TIME_TEXT=text)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.root / 'bench/out/counted/one'
        self.assertEqual((out / 'counters.txt').read_text().split(),
                         ['instructions_G=51.5900', 'cycles_G=15.3000'])
        result = self.run_script('ab.sh', 'countedab', 'one', HARNESS_TIME_TEXT=text)
        self.assertEqual(result.returncode, 0, result.stderr)
        with (self.root / 'bench/out/countedab-ab.tsv').open() as f:
            row, = list(csv.DictReader(f, delimiter='\t'))
        self.assertEqual(row['instructions_G'], '51.5900')
        self.assertEqual(row['cycles_G'], '15.3000')

    def test_ambiguous_or_truncated_counter_records_are_refused(self):
        self.wall_time_fixture()
        duplicated = ('real 1.20\nuser 4.30\nsys 0.20\n   51590000000  instructions retired\n'
                      '   51590000000  instructions retired\n   15300000000  cycles elapsed\n')
        # A duplicate record is ambiguous rather than silently taking the first value.
        self.rejected(self.run_script('run.sh', 'one', 'dupcounters', HARNESS_TIME_TEXT=duplicated),
                      'ambiguous')
        # A truncated timing file is refused even when its counters are complete.
        self.rejected(self.run_script('run.sh', 'one', 'shortrecord', HARNESS_TIME_TEXT=(
            'real 1.20\nuser 4.30\n   51590000000  instructions retired\n'
            '   15300000000  cycles elapsed\n')), 'timing')

    def test_labelled_suffix_counters_are_not_read_as_counters(self):
        self.wall_time_fixture()
        text = ('real 1.20\nuser 4.30\nsys 0.20\n'
                '   51590000000  instructions retired per second\n')
        result = self.run_script('run.sh', 'one', 'suffixcounters', HARNESS_TIME_TEXT=text)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.root / 'bench/out/suffixcounters/one'
        self.assertEqual((out / 'counters.txt').read_text().split(),
                         ['instructions_G=na', 'cycles_G=na'])

    def test_zero_wall_and_rounding_to_zero_counters_do_not_crash_or_pass(self):
        self.wall_time_fixture()
        for tag, text in (
            ('zerowall', 'real 0.00\nuser 4.30\nsys 0.20\n'
                         '   51590000000  instructions retired\n   15300000000  cycles elapsed\n'),
            ('roundedsmall', self.time_text('1.20', 1000, 1000)),
        ):
            with self.subTest(tag=tag):
                result = self.run_script('ab.sh', tag, 'one', HARNESS_TIME_TEXT=text)
                self.assertEqual(result.returncode, 0, result.stderr)
                mode = (self.root / f'bench/out/{tag}-ab.mode.txt').read_text().lower()
                self.assertIn('unclassified', mode)
                self.assertNotIn('mode: comparable', mode)

    def test_differing_instruction_counts_are_not_called_comparable(self):
        self.wall_time_fixture()
        mapping = json.dumps({
            'one': self.time_text('1.20', 1_000_000_000, 300_000_000),
            'two': self.time_text('1.20', 51_590_000_000, 15_300_000_000),
        })
        result = self.run_script('ab.sh', 'scopes', 'one,two', HARNESS_TIME_MAP=mapping)
        self.assertEqual(result.returncode, 0, result.stderr)
        mode = (self.root / 'bench/out/scopes-ab.mode.txt').read_text().lower()
        self.assertIn('counter scope differs', mode)
        self.assertIn('unclassified', mode)

    def test_zero_or_repeated_counter_levels_are_not_called_comparable(self):
        self.wall_time_fixture()
        zero = self.time_text('1.20', 51_590_000_000, 0)
        result = self.run_script('ab.sh', 'zerocounters', 'one', HARNESS_TIME_TEXT=zero)
        self.assertEqual(result.returncode, 0, result.stderr)
        mode = (self.root / 'bench/out/zerocounters-ab.mode.txt').read_text().lower()
        self.assertIn('unclassified', mode)
        self.assertIn('incomplete or invalid', mode)

    def test_incomplete_counters_across_repeats_are_refused(self):
        self.wall_time_fixture()
        complete = self.time_text('1.20', 51_590_000_000, 15_300_000_000)
        partial = 'real 1.21\nuser 4.30\nsys 0.20\n   51580000000  instructions retired\n'
        mapping = json.dumps({'one': [complete] * 2, 'two': [complete, partial]})
        result = self.run_script('ab.sh', 'repeatpartial', 'one,two', REPS='2', COOL='0', HARNESS_TIME_MAP=mapping)
        self.assertEqual(result.returncode, 0, result.stderr)
        mode = (self.root / 'bench/out/repeatpartial-ab.mode.txt').read_text().lower()
        self.assertIn('incomplete or invalid', mode)
        self.assertNotIn('mode: comparable', mode)

    def test_counters_absent_is_recorded_but_never_invented(self):
        self.wall_time_fixture()
        result = self.run_script('run.sh', 'one', 'uncounted', HARNESS_TIME_TEXT=self.time_text('1.20'))
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.root / 'bench/out/uncounted/one'
        self.assertEqual((out / 'counters.txt').read_text().split(), ['instructions_G=na', 'cycles_G=na'])
        result = self.run_script('ab.sh', 'uncountedab', 'one', HARNESS_TIME_TEXT=self.time_text('1.20'))
        self.assertEqual(result.returncode, 0, result.stderr)
        with (self.root / 'bench/out/uncountedab-ab.tsv').open() as f:
            row, = list(csv.DictReader(f, delimiter='\t'))
        self.assertEqual(row['instructions_G'], 'na')
        self.assertEqual(row['cycles_G'], 'na')
        self.assertIn('counter', result.stdout.lower())

    def test_ab_marks_a_stall_mode_mismatch_between_equal_workloads(self):
        self.wall_time_fixture()
        mapping = json.dumps({
            'one': self.time_text('1.20', 51_590_000_000, 15_300_000_000),
            'two': self.time_text('1.35', 51_600_000_000, 20_900_000_000),
        })
        result = self.run_script('ab.sh', 'modes', 'one,two', HARNESS_TIME_MAP=mapping)
        self.assertEqual(result.returncode, 0, result.stderr)
        with (self.root / 'bench/out/modes-ab.mode.txt').open() as f:
            mode = f.read().lower()
        self.assertIn('stall', mode)
        self.assertIn('cycles', mode)
        self.assertIn('one', mode)
        self.assertIn('stall', result.stdout.lower())

    def test_ab_reports_no_stall_mismatch_for_comparable_counters(self):
        self.wall_time_fixture()
        mapping = json.dumps({
            'one': self.time_text('1.20', 51_590_000_000, 15_300_000_000),
            'two': self.time_text('1.21', 51_640_000_000, 15_350_000_000),
        })
        result = self.run_script('ab.sh', 'comparable', 'one,two', HARNESS_TIME_MAP=mapping)
        self.assertEqual(result.returncode, 0, result.stderr)
        mode = (self.root / 'bench/out/comparable-ab.mode.txt').read_text().lower()
        self.assertIn('comparable', mode)
        self.assertNotIn('stall mode mismatch', mode)

    def test_ab_treats_incomplete_counter_pairs_as_unclassified(self):
        self.wall_time_fixture()
        mapping = json.dumps({
            'one': self.time_text('1.20', 51_590_000_000, 15_300_000_000),
            'two': 'real 1.20\nuser 4.30\nsys 0.20\n   51600000000  instructions retired\n',
        })
        result = self.run_script('ab.sh', 'partial', 'one,two', HARNESS_TIME_MAP=mapping)
        self.assertEqual(result.returncode, 0, result.stderr)
        mode = (self.root / 'bench/out/partial-ab.mode.txt').read_text().lower()
        self.assertIn('unclassified', mode)
        self.assertIn('incomplete', mode)

    def test_ab_flags_repeats_spanning_several_cycle_levels(self):
        self.wall_time_fixture()
        mapping = json.dumps({
            'one': [self.time_text('1.20', 51_590_000_000, 15_300_000_000)] * 2,
            'two': [self.time_text('1.35', 51_600_000_000, 20_900_000_000),
                    self.time_text('1.20', 51_600_000_000, 15_320_000_000)],
        })
        result = self.run_script('ab.sh', 'mixedmode', 'one,two', REPS='2', COOL='0', HARNESS_TIME_MAP=mapping)
        self.assertEqual(result.returncode, 0, result.stderr)
        mode = (self.root / 'bench/out/mixedmode-ab.mode.txt').read_text().lower()
        self.assertIn('host mode present within two', mode)
        self.assertIn('unclassified', mode)

    def test_ab_mode_assessment_covers_every_variant_pair(self):
        self.wall_time_fixture()
        # Instruction counts are similar for all three (so the scope rule stays
        # quiet) and the first variant sits between the others: only the two/three
        # pair violates the stall rule, which a first-variant-only check would miss.
        mapping = json.dumps({
            'one': self.time_text('1.20', 51_590_000_000, 17_000_000_000),
            'two': self.time_text('1.21', 51_600_000_000, 15_300_000_000),
            'three': self.time_text('1.40', 51_610_000_000, 18_800_000_000),
        })
        result = self.run_script('ab.sh', 'pairwise', 'one,two,three', HARNESS_TIME_MAP=mapping)
        self.assertEqual(result.returncode, 0, result.stderr)
        mode = (self.root / 'bench/out/pairwise-ab.mode.txt').read_text()
        self.assertIn('stall mode mismatch between two and three', mode)

    def test_ab_refuses_mode_file_collisions_and_symlinks(self):
        self.wall_time_fixture()
        mode = self.root / 'bench/out/modeclash-ab.mode.txt'
        mode.parent.mkdir(parents=True)
        mode.write_text('keep mode notes')
        result = self.run_script('ab.sh', 'modeclash', 'one')
        self.rejected(result, 'exist')
        self.assertEqual(mode.read_text(), 'keep mode notes')
        self.assertFalse((self.root / 'calls').exists())
        mode.unlink()
        target = self.root / 'external-mode'
        target.write_text('untouched')
        mode.symlink_to(target)
        result = self.run_script('ab.sh', 'modeclash', 'one')
        self.rejected(result, 'symlink')
        self.assertEqual(target.read_text(), 'untouched')

    def test_aa_control_rejects_symlinked_snapshots(self):
        self.wall_time_fixture()
        (self.root / 'bench/bin/alias').symlink_to(self.root / 'bench/bin/one', target_is_directory=True)
        self.rejected(self.run_script('aa.sh', 'one', 'alias', 'nullalias'), 'symlink')
        self.binary(self.root / 'bench/bin/copy/wsclean')
        binary = self.root / 'bench/bin/copy/wsclean'
        binary.unlink()
        binary.symlink_to(self.root / 'bench/bin/one/wsclean')
        self.rejected(self.run_script('aa.sh', 'one', 'copy', 'nullalias2'), 'symlink')
        self.assertFalse((self.root / 'bench/out').exists())

    def test_aa_control_rejects_native_payload_symlinks_and_asymmetry(self):
        self.wall_time_fixture()
        live = self.root / 'build-mx'
        self.binary(live / 'wsclean')
        for name in ('one', 'copy'):
            self.binary(self.root / f'bench/bin/{name}/wsclean')
            (self.root / f'bench/bin/{name}/wsclean.native').symlink_to(live / 'wsclean')
        self.rejected(self.run_script('aa.sh', 'one', 'copy', 'nullnative'), 'payload')
        for name in ('one', 'copy'):
            (self.root / f'bench/bin/{name}/wsclean.native').unlink()
        self.binary(self.root / 'bench/bin/copy/wsclean.native')
        self.rejected(self.run_script('aa.sh', 'one', 'copy', 'nullasym'), 'only one snapshot')
        self.assertFalse((self.root / 'bench/out').exists())

    def test_aa_control_checks_the_snapshot_library(self):
        self.wall_time_fixture()
        for name in ('one', 'copy'):
            self.binary(self.root / f'bench/bin/{name}/wsclean')
        (self.root / 'bench/bin/one/libschaapthreading.dylib').write_text('fixture library')
        self.rejected(self.run_script('aa.sh', 'one', 'copy', 'nulllibasym'), 'only one snapshot')
        (self.root / 'bench/bin/copy/libschaapthreading.dylib').write_text('fixture library')
        result = self.run_script('aa.sh', 'one', 'copy', 'nulllibok')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('libschaapthreading.dylib', result.stdout)
        (self.root / 'bench/bin/copy/libschaapthreading.dylib').write_text('different library')
        self.rejected(self.run_script('aa.sh', 'one', 'copy', 'nulllibdiff'), 'not byte-identical')
        self.assertFalse((self.root / 'bench/out/nulllibdiff-ab.tsv').exists())

    def test_aa_control_requires_identical_binaries_and_runs_ab(self):
        self.wall_time_fixture()
        self.binary(self.root / 'bench/bin/copy/wsclean')
        result = self.run_script('aa.sh', 'one', 'copy', 'nullctrl')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / 'bench/out/nullctrl-ab.tsv').exists())
        self.assertEqual([Path(call['binary']).parent.name for call in self.calls()], ['one', 'copy'])
        differing = self.root / 'bench/bin/copy/wsclean'
        differing.write_text(self.fake + '\n# one byte differs\n')
        differing.chmod(0o755)
        result = self.run_script('aa.sh', 'one', 'copy', 'nullctrl2')
        self.rejected(result, 'identical')
        self.assertFalse((self.root / 'bench/out/nullctrl2-ab.tsv').exists())

    def test_aa_control_rejects_same_variant_and_bad_slugs(self):
        self.rejected(self.run_script('aa.sh', 'one', 'one', 'nullctrl'), 'differ')
        for args in ((), ('one',), ('one', 'two')):
            with self.subTest(args=args):
                self.rejected(self.run_script('aa.sh', *args), 'usage:')
        self.rejected(self.run_script('aa.sh', 'one', '..', 'tag'), 'invalid')
        self.assertFalse((self.root / 'bench/out').exists())

    # --- profile.sh ---------------------------------------------------------

    def fake_sampler(self):
        """A stand-in for macOS `sample` that writes the report immediately."""
        path = self.root / 'fakebin/sample'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/usr/bin/env bash\n'
                        'out=""\n'
                        'while [ $# -gt 0 ]; do [ "$1" = "-file" ] && { shift; out="$1"; }; shift; done\n'
                        'printf "Call graph:\\nSort by top of stack, same collapsed (when >= 5):\\n'
                        '  harness_fixture_function  (in wsclean)  42\\n" > "$out"\n')
        path.chmod(0o755)
        return path.parent

    def sampler_env(self, fakebin):
        return {'PATH': f"{fakebin}:{os.environ['PATH']}", 'SAMPLE_SECONDS': '1'}

    def test_profile_refuses_existing_output(self):
        out = self.root / 'bench/out/keep/one-profile'
        out.mkdir(parents=True)
        sentinel = out / 'sentinel'
        sentinel.write_text('keep me')
        result = self.run_script('profile.sh', 'one', 'keep')
        self.assertTrue(sentinel.exists(), 'existing profile sentinel was deleted')
        self.rejected(result, 'exist')
        self.assertFalse((self.root / 'calls').exists())

    def test_profile_required_arguments_and_slugs(self):
        for args in ((), ('one',)):
            self.rejected(self.run_script('profile.sh', *args), 'usage:')
        for slug in ('', '.', '..', '.hidden', '../escape', 'a/b', 'a b'):
            for args in ((slug, 'tag'), ('one', slug)):
                with self.subTest(args=args):
                    self.rejected(self.run_script('profile.sh', *args), 'invalid')
        self.assertFalse((self.root / 'bench/out').exists())

    def test_profile_rejects_unavailable_variant_and_forbidden_options(self):
        self.rejected(self.run_script('profile.sh', 'unknown', 'tag'), 'variant')
        for option in ('predict', 'name', 'temp-dir'):
            for prefix in ('-', '--'):
                with self.subTest(option=option, prefix=prefix):
                    self.rejected(self.run_script('profile.sh', 'one', 'tag', prefix + option, 'x'),
                                  'forbidden')
        self.assertFalse((self.root / 'bench/out').exists())

    def test_profile_requires_the_sampler(self):
        result = self.run_script('profile.sh', 'one', 'nosampler',
                                 SAMPLE_TOOL='definitely-not-a-sampler')
        self.rejected(result, 'sampler')
        self.assertFalse((self.root / 'bench/out').exists())

    def test_profile_writes_top_functions_and_uses_runner_owned_paths(self):
        fakebin = self.fake_sampler()
        result = self.run_script('profile.sh', 'one', 'prof', **self.sampler_env(fakebin))
        self.assertEqual(result.returncode, 0, result.stderr)
        top = (self.root / 'bench/out/prof/one-profile/top.txt').read_text()
        self.assertIn('harness_fixture_function', top)
        call = self.calls()[0]
        self.assertTrue(call['binary'].endswith('bench/bin/one/wsclean'), call['binary'])
        self.assertIn('-no-update-model-required', call['args'])
        # -name is runner-owned and points inside this run's output directory.
        name_index = call['args'].index('-name')
        self.assertTrue(call['args'][name_index + 1].endswith('bench/out/prof/one-profile/img'),
                        call['args'][name_index + 1])


if __name__ == '__main__':
    unittest.main()
