import json
from pathlib import Path
import unittest
from unittest.mock import patch
from bench import analyze_gpu_resources as analysis

PROOF=('prediction proof: shared_planes=2 submitted=3 completed=3 '
       'cpu_fallback=0 grid_memcpy_bytes=0 serial_waits=0\n')
CONV=('[mx-metal] convolution batches=4 planes=8 pool_hits=0 kernel_hits=0 '
      'fused_calls=4 fused_planes=8\n')
BUDGET=('[mx-metal] budget owned_buffer_used=10 peak=20 limit=1073741824 '
        'reservations=2 evictions=0 refusals=0\n')


def synthetic_run(text,case='resident',env=None,expected_gpu=True):
    """Synthetic parser fixture; no benchmark or native GPU execution."""
    folder=Path('synthetic-resource-phase')
    job=dict(tag='synthetic-resource',variant='synthetic',case=case,
             env_overrides={'MX_METAL_MEMORY_MB':'1024'} if env is None else env,
             expected_gpu=expected_gpu,profile=False,warmup=False)
    target=analysis.ROOT/'bench/out'/job['tag']/job['variant']
    files={folder/'plan.json':json.dumps([job]),
           folder/'runs.json':json.dumps([{**job,'exit':0}]),
           target/'time.txt':text+'real 4\nuser 2\nsys 1\n100 maximum resident set size\n',
           target/'wsclean.log':'Inversion: 0:0:1, prediction: 0:0:1, deconvolution: 0:0:1'}
    with patch.object(Path,'read_text',autospec=True,side_effect=lambda path:files[path]):
        return analysis.analyze_folder(folder)['runs'][0]


class ResourceAnalysisTest(unittest.TestCase):
    def test_configured_budget_requires_complete_receipt_and_exact_limit(self):
        for receipt in ('',BUDGET.replace('1073741824','2147483648')):
            with self.subTest(receipt=receipt),self.assertRaisesRegex(ValueError,'budget'):
                synthetic_run(PROOF+CONV+receipt)
        for field in ('owned_buffer_used=10','peak=20','limit=1073741824',
                      'reservations=2','evictions=0','refusals=0'):
            with self.subTest(missing=field),self.assertRaisesRegex(ValueError,'budget'):
                synthetic_run(PROOF+CONV+BUDGET.replace(field,''))
        for receipt in (BUDGET.replace('owned_buffer_used=10','owned_buffer_used=21'),
                        BUDGET.replace('peak=20','peak=1073741825')):
            with self.subTest(receipt=receipt),self.assertRaisesRegex(ValueError,'budget'):
                synthetic_run(PROOF+CONV+receipt)
        self.assertEqual(synthetic_run(PROOF+CONV+BUDGET)['budget']['limit'],1073741824)
        self.assertEqual(synthetic_run(PROOF+CONV,'baseline-convolution',{})['budget'],{})
        self.assertEqual(synthetic_run('', 'baseline-cpu',{},False)['budget'],{})
        for case in ('disabled','budget-refusal'):
            env={'MX_METAL_MEMORY_MB':'1'}
            with self.subTest(case=case),self.assertRaisesRegex(ValueError,'budget'):
                synthetic_run('',case,env,False)
            data=synthetic_run(BUDGET.replace('1073741824','1048576'),case,env,False)
            self.assertEqual(data['budget']['limit'],1048576)

    def test_convolution_trials_require_positive_batches_and_planes(self):
        for case in ('resident','no-plans','no-kernels','baseline-convolution','fused'):
            env={} if case=='baseline-convolution' else None
            for receipt in ('',CONV.replace('batches=4','batches=0'),
                            CONV.replace('planes=8','planes=0'),
                            CONV.replace(' planes=8','')):
                with self.subTest(case=case,receipt=receipt),self.assertRaisesRegex(ValueError,'convolution'):
                    synthetic_run(PROOF+receipt+BUDGET,case,env)
            self.assertEqual(synthetic_run(PROOF+CONV+BUDGET,case,env)['convolution']['batches'],4)
        for receipt in (CONV.replace('fused_calls=4','fused_calls=0'),
                        CONV.replace(' fused_calls=4','')):
            with self.subTest(receipt=receipt),self.assertRaisesRegex(ValueError,'fusion'):
                synthetic_run(PROOF+receipt+BUDGET,'fused')

    def test_schedule_waits_match_successful_prediction_work(self):
        proof=PROOF+PROOF.replace('submitted=3 completed=3','submitted=2 completed=2')
        for waits in (0,1,4,6):
            with self.subTest(waits=waits),self.assertRaisesRegex(ValueError,'serial'):
                synthetic_run(proof.replace('serial_waits=0','serial_waits='+str(waits))+BUDGET,'serial')
        serial=proof.replace('serial_waits=0','serial_waits=3',1)
        serial=serial.rsplit('serial_waits=0',1)[0]+'serial_waits=2\n'
        self.assertEqual(synthetic_run(serial+BUDGET,'serial')['serial_waits'],5)
        self.assertEqual(synthetic_run(proof+BUDGET,'overlapped')['serial_waits'],0)
        with self.assertRaisesRegex(ValueError,'serial'):
            synthetic_run(PROOF.replace('serial_waits=0','serial_waits=1')+BUDGET,'overlapped')
        for case in ('serial','overlapped'):
            with self.subTest(case=case),self.assertRaisesRegex(ValueError,'serial'):
                synthetic_run(PROOF.replace(' serial_waits=0','')+BUDGET,case)

    def test_ablation_receipts_prove_caches_disabled(self):
        for case,field in (('no-plans','pool_hits'),('no-kernels','kernel_hits')):
            for receipt in (CONV.replace(field+'=0',field+'=1'),CONV.replace(' '+field+'=0','')):
                with self.subTest(case=case,receipt=receipt),self.assertRaisesRegex(ValueError,field):
                    synthetic_run(PROOF+receipt+BUDGET,case)
            synthetic_run(PROOF+CONV+BUDGET,case)

    def test_controls_reject_all_actual_gpu_work(self):
        for case in ('disabled','budget-refusal'):
            for receipt in (PROOF.replace('completed=3','completed=0'),
                            CONV.replace('batches=4','batches=0').replace('fused_calls=4','fused_calls=0'),
                            '[mx-metal] convolution batches=0 planes=0 fused_calls=0 fused_planes=1\n'):
                with self.subTest(case=case,receipt=receipt),self.assertRaisesRegex(ValueError,'unexpected'):
                    synthetic_run(receipt+BUDGET,case,expected_gpu=False)
            synthetic_run(BUDGET,case,expected_gpu=False)

    def test_budget_violation_and_missing_gpu_work_fail(self):
        text='[mx-metal] budget owned_buffer_used=10 peak=30 limit=20 reservations=2 evictions=0 refusals=0\n'
        with self.assertRaisesRegex(ValueError,'budget'):analysis.parse_resources(text,False)
        with self.assertRaisesRegex(ValueError,'GPU'):analysis.parse_resources('',True)
        with self.assertRaisesRegex(ValueError,'unexpected'):
            analysis.parse_resources('[mx-metal] convolution batches=1 planes=2 fused_calls=1\n',False)

    def test_completed_work_and_cumulative_counters(self):
        text=('prediction proof: shared_planes=2 submitted=3 completed=3 cpu_fallback=0 grid_memcpy_bytes=0 serial_waits=3\n'
              '[mx-metal] convolution batches=4 planes=8 pool_hits=3 pool_misses=1 kernel_hits=6 kernel_uploads=2 kernel_bytes=100 output_copy_bytes=200 fused_calls=4 fused_planes=8 refusals=0\n'
              '[mx-metal] budget owned_buffer_used=10 peak=20 limit=20 reservations=2 evictions=1 refusals=0\n')
        data=analysis.parse_resources(text,True)
        self.assertEqual(data['convolution']['pool_hits'],3)
        self.assertEqual(data['budget']['peak'],20)
        self.assertEqual(data['prediction_completed'],3)
        self.assertEqual(data['serial_waits'],3)
        with self.assertRaisesRegex(ValueError,'unexpected'):analysis.parse_resources(text,False)

    def test_trace_uses_production_second_clock_and_gpu_stages(self):
        helper=getattr(analysis,'summarize_spans',None)
        self.assertTrue(callable(helper),'production trace parser missing')
        trace,busy=helper([{'stage':'fft.gpu','start':10.0,'end':12.0,'bytes':4},
                           {'stage':'fusion.gpu','start':11.0,'end':13.0,'bytes':8}])
        self.assertEqual(busy,3.0)
        self.assertEqual(trace['fft.gpu']['host_s'],2.0)
        self.assertEqual(trace['fusion.gpu']['bytes'],8)

    def test_missing_and_duplicate_trials_fail(self):
        plan=[{'tag':'a','case':'cpu'},{'tag':'b','case':'fused'}]
        with self.assertRaises(ValueError):analysis.validate_inventory(plan,[plan[0]])
        with self.assertRaises(ValueError):analysis.validate_inventory(plan,[plan[0],plan[0]])
        with self.assertRaises(ValueError):analysis.validate_inventory(plan,[plan[1],plan[0]])
        analysis.validate_inventory(plan,plan)

if __name__=='__main__':unittest.main()
