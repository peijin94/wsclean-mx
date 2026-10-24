"""Deep benchmark defaults and metadata; stubs are not timing measurements."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from bench import gpu_profile_campaign as profile
from bench import gpu_resource_campaign as resource
from bench import plot_gpu_resources as plots


class DeepIterationDefaultsTest(unittest.TestCase):
    def test_resource_plans_record_default_and_override(self):
        plan=resource.make_plan('timing','candidate','trial')
        self.assertTrue(all(j.get('niter')==150000 for j in plan))
        plan=resource.make_plan('timing','candidate','trial',niter=20000)
        self.assertTrue(all(j['niter']==20000 for j in plan))
        with self.assertRaises(ValueError):
            resource.make_plan('timing','candidate','trial',niter=-1)

    def test_resource_cli_records_explicit_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'plan'
            argv=['campaign','timing','--candidate','candidate','--label','trial',
                  '--output',str(output),'--plan-only','--niter','20000']
            with patch('sys.argv',argv):
                self.assertEqual(resource.main(),0)
            plan=json.loads((output/'plan.json').read_text())
            self.assertTrue(all(j['niter']==20000 for j in plan))

    def test_profile_windows_cover_deep_deadline(self):
        job=profile.make_plan('sample')[0]
        process=Mock(returncode=0)
        process.poll.return_value=0;process.wait.return_value=0
        with tempfile.TemporaryDirectory() as directory:
            binary=Path(directory)/'bench/bin'/job['variant']/'wsclean'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\nexit 0\n');binary.chmod(0o755)
            with patch.object(profile,'ROOT',Path(directory)), \
                 patch.object(profile,'health',return_value={}), \
                 patch.object(profile,'find_target',return_value=987655), \
                 patch.object(profile.subprocess,'Popen',return_value=process) as popen, \
                 patch('builtins.print'):
                profile.run_job(job,Path(directory))
        self.assertEqual(popen.call_args_list[1].args[0][2],'1800000')
        self.assertEqual(popen.call_args_list[2].args[0][2],'1800')

    def test_plot_iteration_label_uses_recorded_values(self):
        self.assertTrue(callable(getattr(plots,'iteration_label',None)))
        self.assertEqual(plots.iteration_label([{'niter':150000}]*2),'niter 150000')
        self.assertEqual(plots.iteration_label([{'niter':20000}]*2),'niter 20000')
        self.assertEqual(plots.iteration_label([{}]),'iteration budget not recorded')
        for rows in ([{'niter':150000},{'niter':20000}],
                     [{'niter':150000},{}],[{'niter':True}]):
            with self.assertRaises(ValueError):plots.iteration_label(rows)

    def _plot_data(self):
        cases=['candidate-default','resident','fused']
        return [
            {'phase':'timing','runs':[
                {'niter':150000,'case':case,'warmup':False,'budget':{'peak':0}}
                for case in cases],
             'summary':{case:{'times':{'rss_bytes':{'median':0}}} for case in cases}},
            {'phase':'trace','runs':[
                {'niter':150000,'case':case}
                for case in ['baseline-convolution','resident','fused']]},
            {'phase':'overlap','runs':[{'niter':150000}], 'summary':{}},
        ]

    def _assert_render_rejects_phase_budget(self,phase,niter):
        data=self._plot_data()
        for run in next(p for p in data if p['phase']==phase)['runs']:
            if niter is None:run.pop('niter')
            else:run['niter']=niter
        output=MagicMock(spec=Path)
        with patch.object(plots,'plt') as pyplot, \
             patch.object(plots,'sampled_bars'), \
             patch.object(plots,'copy_totals',return_value=(0,0,0)):
            pyplot.subplots.return_value=(Mock(),MagicMock())
            with self.assertRaises(ValueError):plots.render(data,output)
            pyplot.rcParams.update.assert_not_called()
            pyplot.subplots.assert_not_called()
            output.mkdir.assert_not_called()
            pyplot.subplots.return_value[0].savefig.assert_not_called()

    def test_render_rejects_trace_budget_mismatch_and_legacy_mixture(self):
        for niter in (20000,None):
            with self.subTest(niter=niter):
                self._assert_render_rejects_phase_budget('trace',niter)

    def test_render_rejects_overlap_budget_mismatch_and_legacy_mixture(self):
        for niter in (20000,None):
            with self.subTest(niter=niter):
                self._assert_render_rejects_phase_budget('overlap',niter)

    def test_render_rejects_timing_budget_mismatch_and_legacy_mixture_at_entry(self):
        for niter in (20000,None):
            with self.subTest(niter=niter):
                self._assert_render_rejects_phase_budget('timing',niter)

    def test_render_accepts_uniform_known_and_unknown_budgets(self):
        for niter,label in ((150000,'niter 150000'),(20000,'niter 20000'),
                            (None,'iteration budget not recorded')):
            with self.subTest(niter=niter):
                data=self._plot_data()
                for phase in data:
                    for run in phase['runs']:
                        if niter is None:run.pop('niter')
                        else:run['niter']=niter
                output=MagicMock(spec=Path)
                resources,overlap=Mock(),Mock()
                with patch.object(plots,'plt') as pyplot, \
                     patch.object(plots,'sampled_bars'), \
                     patch.object(plots,'copy_totals',return_value=(0,0,0)):
                    pyplot.subplots.side_effect=[(resources,MagicMock()),(overlap,MagicMock())]
                    plots.render(data,output)
                    self.assertIn(f'; {label};',resources.suptitle.call_args.args[0])
                    self.assertEqual(pyplot.subplots.call_count,2)
                    output.mkdir.assert_called_once_with(parents=True,exist_ok=True)
                    resources.savefig.assert_called_once_with(output/'resources.png',dpi=160)
                    overlap.savefig.assert_called_once_with(output/'overlap.png',dpi=160)


if __name__=='__main__':unittest.main()
