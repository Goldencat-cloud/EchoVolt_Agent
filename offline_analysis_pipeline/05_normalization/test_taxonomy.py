import importlib.util
import json
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('taxonomy_analysis',HERE/'normalize_taxonomy.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)


class TaxonomyBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        anchors=json.loads((mod.HELPERS/'corpus-name-anchors.json').read_text(encoding='utf-8'))
        catalog=json.loads((mod.HELPERS/'catalog.json').read_text(encoding='utf-8'))
        cls.resolver=mod.Resolver(anchors,catalog)

    def case(self,name,quote=None,title='',body='',**fields):
        quote=quote or name
        e={'id':'P1','name':name,'brand':None,'series':None,'model_year':None,'version':None,
           'evidence':[{'block_id':'T1','source_type':'text','quote':quote}],**fields}
        p={'title':title,'blocks':[{'block_id':'T0','type':'text','text':title},
                                  {'block_id':'T1','type':'text','text':quote},
                                  {'block_id':'T2','type':'text','text':body}]}
        return self.resolver.resolve('test',e,p)

    def test_user_alias_suqi(self):
        for alias in ['酥妻','小米酥妻','酥七','速七','苏七','苏7','小米苏七','小米酥7']:
            with self.subTest(alias=alias):
                m=self.case(alias)
                self.assertEqual((m['brand'],m['series']),('小米','SU7'))
                self.assertIsNone(m['attributes']['model_year'])
                self.assertTrue(any(b['scope']=='alias_dictionary' for b in m['resolution_basis']))
                if '小米' not in alias:
                    self.assertTrue(any(b['scope']=='forum_context' for b in m['resolution_basis']))

    def test_brand_only_stays_brand(self):
        m=self.case('小米汽车',body='我的小米SU7不错')
        self.assertEqual(m['resolution_level'],'brand')
        self.assertIsNone(m['series'])

    def test_generic_suv_stays_brand(self):
        self.assertEqual(self.case('小米SUV')['resolution_level'],'brand')

    def test_explicit_brand_and_version_uses_forum(self):
        m=self.case('小米标准版',version='标准版')
        self.assertEqual((m['brand'],m['series']),('小米','SU7'))

    def test_same_mention_brand_and_model_evidence_goes_deeper(self):
        m=self.case('小米汽车','小米酥妻，蓝牙连不到钥匙')
        self.assertEqual((m['brand'],m['series']),('小米','SU7'))

    def test_phone_pro_not_forum_car(self):
        m=self.case('小米17 Pro',brand='小米',series='17 Pro',version='Pro')
        self.assertEqual(m['status'],'excluded')

    def test_redmi_not_vehicle_series(self):
        m=self.case('红米Note 17',brand='红米',series='Note 17')
        self.assertEqual(m['status'],'excluded')

    def test_alias_not_a_second_series_node(self):
        self.assertEqual(mod.clean_series('苏七','小米'),'SU7')
        self.assertEqual(mod.clean_series('小米SU7','小米'),'SU7')

    def test_versions_do_not_create_more_series_nodes(self):
        a=self.case('小米SU7',brand='小米',series='SU7')
        b=self.case('小米SU7 Max',brand='小米',series='SU7',version='Max')
        self.assertEqual(mod.node_path(a)[-1]['id'],mod.node_path(b)[-1]['id'])
        self.assertEqual(b['attributes']['version'],'Max')
        self.assertIsNone(b['specid'])

    def test_year_is_attribute_without_complete_configuration(self):
        m=self.case('小米SU7 2024款 Max',brand='小米',series='SU7',model_year='2024',version='Max')
        self.assertEqual(m['resolution_level'],'series')
        self.assertEqual(m['attributes']['model_year'],'2024')
        self.assertIsNone(m['specid'])

    def test_explicit_jinpeng_overrides_forum(self):
        m=self.case('金彭SU7')
        self.assertEqual(m['brand'],'金彭')
        self.assertNotEqual(mod.node_path(m)[-1]['id'],mod.node_path(self.case('SU7'))[-1]['id'])

    def test_shangjie_alias_conflict(self):
        m=self.case('尚界酥妻')
        self.assertEqual(m['brand'],'尚界')
        self.assertIsNone(m['series'])
        self.assertTrue(m['review_required'])

    def test_explicit_competitor_preserved(self):
        m=self.case('特斯拉Model Y')
        self.assertEqual((m['brand'],m['series']),('特斯拉','Model Y'))

    def test_named_target_in_comparison(self):
        m=self.case('小米SU7','SU7比特斯拉Model 3更舒服',brand='小米',series='SU7')
        self.assertEqual((m['brand'],m['series']),('小米','SU7'))

    def test_same_code_explicit_other_brand(self):
        m=self.case('小米SU7','金彭SU7国礼版')
        self.assertNotEqual((m['brand'],m['series']),('小米','SU7'))

    def test_colloquial_competitor(self):
        for alias in ['毛豆3','毛豆三']:
            m=self.case(alias)
            self.assertEqual((m['brand'],m['series']),('特斯拉','Model 3'))

    def test_max_can_use_forum(self):
        m=self.case('Max',version='Max')
        self.assertEqual(m['series'],'SU7')
        self.assertEqual(m['attributes']['version'],'Max')

    def test_max_ambiguous_in_multicar_post(self):
        m=self.case('Max',body='小米SU7和特斯拉Model 3哪个舒服？')
        self.assertNotEqual(m['status'],'mapped')

    def test_config_match(self):
        name='小米SU7 2024款 四驱超长续航高阶智驾Max版'
        m=self.case(name,brand='小米',series='SU7',model_year='2024',version='Max')
        self.assertEqual(m['specid'],'65768')
        self.assertEqual(m['resolution_level'],'configuration')

    def test_no_inferred_year(self):
        m=self.case('小米SU7 Max',brand='小米',series='SU7',model_year='2024',version='Max')
        self.assertIsNone(m['attributes']['model_year'])
        self.assertEqual(m['resolution_level'],'series')
        self.assertTrue(m['review_required'])

    def test_prototype_not_configuration(self):
        m=self.case('小米SU7 Ultra Prototype',brand='小米',series='SU7',version='Ultra Prototype')
        self.assertIsNone(m['specid'])
        self.assertIn('原型车',m['attributes']['version'])


if __name__=='__main__':
    unittest.main()
