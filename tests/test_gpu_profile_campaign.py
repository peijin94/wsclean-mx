"""Harness tests; simulated process rows are not profiling measurements."""
import unittest
import json
import signal
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from bench import gpu_profile_campaign as campaign
from bench.gpu_profile_campaign import matching_pids,make_plan

class GpuCampaignTest(unittest.TestCase):
    def test_nonzero_sampler_exit_fails_job_and_preserves_receipt(self):
        job=make_plan('sample')[1]
        process=Mock(returncode=0)
        process.poll.return_value=0
        process.wait.return_value=0
        monitor=Mock(returncode=0)
        monitor.wait.return_value=0
        sampler=Mock(returncode=7)
        sampler.wait.return_value=7
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            with patch.object(campaign,'health',side_effect=[{'ok':'before'},{'ok':'after'}]), \
                 patch.object(campaign,'find_target',return_value=987655), \
                 patch.object(campaign.subprocess,'Popen',side_effect=[process,monitor,sampler]), \
                 patch.object(campaign.os,'killpg') as killpg, \
                 patch('builtins.print') as output:
                with self.assertRaisesRegex(RuntimeError,'sample failed'):
                    campaign.run_job(job,folder)
            result=json.loads((folder/(job['tag']+'.receipt.json')).read_text())
            self.assertEqual(result['exit'],0)
            self.assertEqual(result['monitor_exit'],0)
            self.assertEqual(result['sample_exit'],7)
            self.assertEqual(result['before'],{'ok':'before'})
            self.assertEqual(result['after'],{'ok':'after'})
            self.assertIn('end_unix_s',result)
            monitor.stdin.close.assert_called_once_with()
            killpg.assert_not_called()
            output.assert_not_called()

    def test_timing_trace_and_sample_auxiliary_logs_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            for phase in ('timing','trace','sample'):
                for job in make_plan(phase):
                    process=Mock(returncode=0)
                    process.poll.return_value=0
                    process.wait.return_value=0
                    with patch.object(campaign,'health',return_value={}), \
                         patch.object(campaign,'find_target',return_value=987655), \
                         patch.object(campaign.subprocess,'Popen',return_value=process) as popen, \
                         patch.object(campaign.os,'killpg') as killpg, \
                         patch('builtins.print'):
                        result=campaign.run_job(job,Path(directory))
                    expected=job['profile'] or job['sample']
                    self.assertEqual('-log-time' in result['command'],expected)
                    self.assertEqual(result['env'].get('MX_WGRIDDER_VERBOSE'),'1' if expected else None)
                    self.assertEqual(result['env'].get('MX_METAL_PROFILE'),'1' if job['profile'] else None)
                    self.assertEqual(popen.call_args_list[0].args[0],result['command'])
                    killpg.assert_not_called()

    def test_process_start_failure_still_finalizes(self):
        job=make_plan('timing')[0]
        error=OSError('mock spawn failed')
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            with patch.object(campaign,'health',return_value={'ok':True}), \
                 patch.object(campaign.subprocess,'Popen',side_effect=error), \
                 patch.object(campaign.os,'killpg') as killpg:
                with self.assertRaises(OSError) as raised:campaign.run_job(job,folder)
            self.assertIs(raised.exception,error)
            result=json.loads((folder/(job['tag']+'.receipt.json')).read_text())
            self.assertIsNone(result['exit'])
            self.assertEqual(result['exception']['text'],str(error))
            self.assertEqual(result['after'],{'ok':True})
            killpg.assert_not_called()

    def test_wait_failure_cleans_monitor_and_sampler_even_if_monitor_close_fails(self):
        job=make_plan('sample')[1]
        error=RuntimeError('mock benchmark wait failed')
        process=Mock(pid=987654,returncode=-signal.SIGTERM)
        process.poll.return_value=None
        process.wait.side_effect=[error,-signal.SIGTERM]
        monitor=Mock(returncode=-signal.SIGKILL)
        sampler=Mock(returncode=-signal.SIGKILL)
        monitor.stdin.close.side_effect=OSError('monitor pipe failed')
        for child in (monitor,sampler):
            child.wait.side_effect=[campaign.subprocess.TimeoutExpired('mock',10),
                                    campaign.subprocess.TimeoutExpired('mock',10),-signal.SIGKILL]
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            with patch.object(campaign,'health',return_value={'ok':True}), \
                 patch.object(campaign.subprocess,'Popen',side_effect=[process,monitor,sampler]), \
                 patch.object(campaign,'find_target',return_value=987655), \
                 patch.object(campaign.os,'killpg') as killpg:
                with self.assertRaises(RuntimeError) as raised:campaign.run_job(job,folder)
            self.assertIs(raised.exception,error)
            result=json.loads((folder/(job['tag']+'.receipt.json')).read_text())
            self.assertEqual(result['exit'],-signal.SIGTERM)
            self.assertEqual(result['monitor_exit'],-signal.SIGKILL)
            self.assertEqual(result['sample_exit'],-signal.SIGKILL)
            self.assertEqual(result['cleanup_errors'],[{'type':'OSError','text':'monitor pipe failed'}])
            for child in (monitor,sampler):
                child.terminate.assert_called_once_with()
                child.kill.assert_called_once_with()
            killpg.assert_called_once_with(process.pid,signal.SIGTERM)

    def test_end_health_failure_is_recorded_and_fails_job(self):
        job=make_plan('timing')[0]
        process=Mock(returncode=0)
        process.poll.return_value=0
        process.wait.return_value=0
        error=OSError('mock health failed')
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            with patch.object(campaign,'health',side_effect=[{},error]), \
                 patch.object(campaign.subprocess,'Popen',return_value=process), \
                 patch.object(campaign.os,'killpg') as killpg:
                with self.assertRaises(OSError) as raised:campaign.run_job(job,folder)
            self.assertIs(raised.exception,error)
            result=json.loads((folder/(job['tag']+'.receipt.json')).read_text())
            self.assertEqual(result['exit'],0)
            self.assertEqual(result['after_error'],{'type':'OSError','text':str(error)})
            killpg.assert_not_called()

    def test_overhead_pairs_only_toggle_profile(self):
        captured=[]
        with tempfile.TemporaryDirectory() as directory:
            for job in make_plan('overhead'):
                process=Mock(returncode=0)
                process.poll.return_value=0
                process.wait.return_value=0
                with patch.object(campaign,'health',return_value={'ok':True}), \
                     patch.object(campaign.subprocess,'Popen',return_value=process) as popen:
                    campaign.run_job(job,Path(directory))
                command=list(popen.call_args.args[0]);command[3]='TAG'
                captured.append((job,command,popen.call_args.kwargs['env']))
        for left,right in zip(captured[::2],captured[1::2]):
            self.assertEqual(left[0]['repeat'],right[0]['repeat'])
            self.assertNotEqual(left[0]['profile'],right[0]['profile'])
            self.assertEqual(left[1],right[1])
            envs=[]
            for job,command,env in (left,right):
                env=dict(env)
                self.assertEqual(env.pop('MX_METAL_PROFILE',None),'1' if job['profile'] else None)
                envs.append(env)
            self.assertEqual(*envs)

    def test_lookup_exception_retains_receipt_and_original_error(self):
        job=make_plan('pilot')[0]
        process=Mock(pid=987654, returncode=-signal.SIGTERM)
        process.poll.return_value=None
        process.wait.return_value=-signal.SIGTERM
        error=RuntimeError('mock PID discovery failure')
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            with patch.object(campaign,'health',side_effect=[{'ok':'before'},OSError('end health failed')]), \
                 patch.object(campaign.subprocess,'Popen',return_value=process), \
                 patch.object(campaign,'find_target',side_effect=error), \
                 patch.object(campaign.os,'killpg') as killpg:
                with self.assertRaises(RuntimeError) as raised:
                    campaign.run_job(job,folder)
            self.assertIs(raised.exception,error)
            receipt=folder/(job['tag']+'.receipt.json')
            self.assertTrue(receipt.exists(),'receipt missing after PID discovery exception')
            result=json.loads(receipt.read_text())
            self.assertEqual(result['exception'],{'type':'RuntimeError','text':str(error)})
            self.assertEqual(result['exit'],-signal.SIGTERM)
            self.assertEqual(result['after_error'],{'type':'OSError','text':'end health failed'})
            self.assertIn('end_unix_s',result)
            self.assertIn('command',result)
            self.assertEqual(result['env']['MX_METAL_PROFILE'],'1')
            killpg.assert_called_once_with(process.pid,signal.SIGTERM)

    def test_truncated_comm_and_time_parent(self):
        exe='/Users/some long path/bench/bin/gpu/wsclean';needle='/specific/gpu/img'
        rows=f'10 /usr/bin/time /usr/bin/time -lp {exe} -name {needle}\n11 /Users/some {exe} -name {needle}\n12 /Users/some {exe} -name /different/gpu/img\n'
        self.assertEqual(matching_pids(rows,needle,exe),[11])

    def test_fullgrid_diagnostic_is_explicit(self):
        rows=make_plan('fullgrid')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['size'],4096)
        self.assertEqual(rows[0]['extra'],['-no-min-grid-resolution'])
        self.assertTrue(rows[0]['profile'])

    def test_plans_unique_and_modes_explicit(self):
        for phase in ['pilot','timing','trace','threads','4k','sample','overhead']:
            rows=make_plan(phase)
            self.assertEqual(len(rows),len({x['tag'] for x in rows}))
            for row in rows:
                self.assertIn(row['size'],[3072,4096])
                self.assertIn(row['threads'],[1,2,4,8])
        timing=make_plan('timing')
        self.assertTrue(all(not x['profile'] and not x['monitor'] and not x['sample'] for x in timing))
        self.assertEqual(sum(not x['warmup'] for x in timing),15)
