import unittest
from bench import gpu_resource_campaign as campaign

class ResourceCampaignTest(unittest.TestCase):
    def test_timing_is_counterbalanced_with_excluded_warmups(self):
        plan=campaign.make_plan('timing','candidate','trial')
        warm=[j for j in plan if j['warmup']]
        measured=[j for j in plan if not j['warmup']]
        self.assertEqual(len(warm),5)
        self.assertEqual(len(measured),20)
        orders=[[j['case'] for j in measured if j['repeat']==r] for r in range(1,5)]
        self.assertEqual(orders[0],list(reversed(orders[1])))
        self.assertEqual(orders[0],orders[2])
        self.assertTrue(all(not j['profile'] and not j['monitor'] for j in plan))
        self.assertEqual(len({j['tag'] for j in plan}),len(plan))

    def test_ablation_preserves_budget_and_changes_one_feature(self):
        plan=campaign.make_plan('ablation','candidate','trial')
        jobs={j['case']:j for j in plan if j['repeat']==1 and not j['warmup']}
        self.assertEqual(set(jobs),{'resident','no-plans','no-kernels','fused'})
        common={'MX_METAL_MEMORY_MB':'1024','MX_METAL_FUSE':'0'}
        self.assertEqual(jobs['resident']['env_overrides'],common)
        self.assertEqual(jobs['no-plans']['env_overrides'],{**common,'MX_METAL_NO_PLAN_CACHE':'1'})
        self.assertEqual(jobs['no-kernels']['env_overrides'],{**common,'MX_METAL_NO_KERNEL_CACHE':'1'})
        self.assertTrue(all(j['common'] for j in plan))

    def test_serial_diagnostic_has_matched_ordered_pair(self):
        plan=campaign.make_plan('overlap','candidate','trial')
        measured=[j for j in plan if not j['warmup']]
        self.assertEqual(len(measured),8)
        self.assertTrue(all(j['mode']=='prediction' and j['variant']=='candidate' for j in plan))
        for j in plan:
            expected='1' if j['case']=='serial' else '0'
            self.assertEqual(j['env_overrides']['MX_METAL_PREDICT_SERIAL'],expected)

    def test_deterministic_and_stress_contracts(self):
        controls=campaign.make_plan('deterministic','candidate','trial')
        self.assertTrue(all(j['threads']==1 and j['size']==1024 for j in controls))
        self.assertTrue(all(j['extra']==['-scale','8.1amin'] for j in controls))
        self.assertIn('baseline-cpu-aa',[j['case'] for j in controls])
        stress=campaign.make_plan('stress','candidate','trial')
        self.assertTrue(all(j['size']==4096 for j in stress))
        self.assertIn('1',[j['env_overrides'].get('MX_METAL_MEMORY_MB') for j in stress])
        with self.assertRaises(ValueError):campaign.make_plan('unknown','candidate','trial')
        with self.assertRaises(ValueError):campaign.make_plan('timing','../bad','trial')

if __name__=='__main__':unittest.main()
