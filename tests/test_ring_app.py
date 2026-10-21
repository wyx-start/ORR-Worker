from io import BytesIO
import copy
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from orr_core import pack_project, unpack_project
from settings_draft import new_draft
from test_ring_comparison import ring_fixture

ROOT=Path(__file__).resolve().parents[1]


def widget(elements,label):
    return next(e for e in elements if e.label==label)


class RingAppTests(unittest.TestCase):
    def app(self):
        at=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=45).run()
        t,c=ring_fixture('A_900rpm.txt')
        b,bc=ring_fixture('Ar_background.txt',-1e-6,.2e-6)
        u,uc=ring_fixture('B_1600rpm.txt',-12e-6,3e-6)
        c.update(group='A',ring_potential_V=.2)
        uc.update(group='B',ring_potential_V=.5)
        bc['role']='背景'
        at.session_state.traces={t.id:t,b.id:b,u.id:u}
        at.session_state.configs={t.id:c,b.id:bc,u.id:uc}
        at.session_state.settings['axis']='原始'
        at.session_state.revision+=1
        at.session_state.settings_draft=new_draft(at.session_state.revision)
        at.run()
        return at,t,b,u

    def clean(self,at):
        self.assertEqual(len(at.exception),0,str([e.value for e in at.exception]))

    def ring_page(self,at):
        at.switch_page('app_pages/curves.py').run()
        widget(at.segmented_control,'绘制通道').set_value('环电流').run()
        widget(at.selectbox,'按组筛选').set_value('全部').run()
        self.clean(at)

    def test_ring_cross_group_units_raw_view_smoothing_and_persistence(self):
        at,t,b,u=self.app()
        self.ring_page(at)
        self.assertIn('ring_current.png',at.session_state.exports)
        self.assertIn('ring_current.svg',at.session_state.exports)
        df=pd.read_csv(BytesIO(at.session_state.exports['ring_current_data.csv']['bytes']))
        self.assertEqual(df.filename.nunique(),2)
        np.testing.assert_allclose(df[df.file_id==t.id].plotted_current_value,2.)
        self.assertTrue(any('部分比较条件未记录' in e.value for e in at.warning))
        self.assertNotIn('RRDE 收集效率 N（0–1） *',[e.label for e in at.number_input])
        self.assertNotIn('盘直径 / mm *',[e.label for e in at.number_input])
        at.session_state.results['kl']={'sentinel':'unchanged'}
        at.session_state.configs[t.id]['background_ring']=b.id
        at.run()
        widget(at.selectbox,'纵坐标').set_value('环电流 / mA').run()
        df=pd.read_csv(BytesIO(at.session_state.exports['ring_current_data.csv']['bytes']))
        np.testing.assert_allclose(df[df.file_id==t.id].plotted_current_value,.0018)
        widget(at.toggle,'启用曲线平滑').set_value(True).run()
        smooth=pd.read_csv(BytesIO(at.session_state.exports['ring_current_data.csv']['bytes']))
        self.assertIn('I_ring_smoothed_plot_only_A',smooth)
        np.testing.assert_allclose(smooth[smooth.file_id==t.id].I_ring_A,1.8e-6)
        widget(at.selectbox,'环电流显示').set_value('未扣背景').run()
        df=pd.read_csv(BytesIO(at.session_state.exports['ring_current_data.csv']['bytes']))
        np.testing.assert_allclose(df[df.file_id==t.id].plotted_current_value,.002)
        self.assertTrue(df.I_ring_corrected_A.isna().all())
        self.assertEqual(at.session_state.configs[t.id]['background_ring'],b.id)
        self.assertEqual(at.session_state.results['kl'],{'sentinel':'unchanged'})
        params=json.loads(at.session_state.exports['ring_current_parameters.json']['bytes'])
        self.assertIn('comparison_audit',params['settings']['ring_plot'])
        self.assertEqual(params['files'][0]['processing']['channels'],'ring')
        _,cs,settings=unpack_project(pack_project(at.session_state.traces,at.session_state.configs,at.session_state.settings))
        self.assertEqual(settings['ring_plot']['unit'],'mA')
        self.assertEqual(settings['ring_plot']['background_view'],'未扣背景')
        self.assertEqual(cs[t.id]['background_ring'],b.id)
        self.clean(at)

    def test_known_conflict_clears_old_ring_export_without_mutating_conditions(self):
        at,t,b,u=self.app()
        self.ring_page(at)
        at.session_state.configs[t.id]['pH']=13.
        at.session_state.configs[u.id]['pH']=12.
        at.run()
        self.clean(at)
        self.assertTrue(any('已知条件冲突' in e.value for e in at.error))
        self.assertNotIn('ring_current.png',at.session_state.exports)
        self.assertNotIn('ring_current_data.csv',at.session_state.exports)
        self.assertEqual(at.session_state.configs[t.id]['pH'],13.)

    def test_scan_form_paired_binding_then_independent_override(self):
        at,t,b,u=self.app()
        widget(at.segmented_control,'参数设置').set_value('扫描与背景').run()
        widget(at.selectbox,'要检查的文件').set_value(t.id).run()
        self.assertEqual(widget(at.selectbox,'背景模式').value,'盘环配对背景')
        widget(at.selectbox,'背景文件（盘扣盘、环扣环）').set_value(b.id).run()
        self.assertIsNone(at.session_state.configs[t.id]['background_ring'])
        self.assertTrue(at.session_state.settings_draft['configs'])
        widget(at.button,'应用设置').click().run()
        self.assertEqual(at.session_state.configs[t.id]['background_disk'],b.id)
        self.assertEqual(at.session_state.configs[t.id]['background_ring'],b.id)
        widget(at.selectbox,'背景模式').set_value('分别指定背景').run()
        widget(at.selectbox,'环背景文件').set_value('').run()
        widget(at.button,'应用设置').click().run()
        self.assertEqual(at.session_state.configs[t.id]['background_disk'],b.id)
        self.assertIsNone(at.session_state.configs[t.id]['background_ring'])
        self.clean(at)

    def test_metadata_paired_commit_is_atomic_and_preserves_independent_rows(self):
        at,t,b,u=self.app()
        # Simulate a real edit of the unified metadata table, then commit all
        # staged fields once. The old independent row must stay independent.
        at.session_state.configs[u.id].update(background_mode='independent',background_ring=b.id)
        at.session_state.revision+=1
        at.session_state.settings_draft=new_draft(at.session_state.revision)
        at.run()
        editor_key=f'metadata_{at.session_state.revision}_{at.session_state.draft_epoch}'
        row_index=list(at.session_state.traces).index(t.id)
        background_label=at.session_state.traces[b.id].name+' · '+b.id[:4]
        at.session_state[editor_key]={'edited_rows':{row_index:{'背景文件':background_label}},'added_rows':[],'deleted_rows':[]}
        at.run()
        self.assertIsNone(at.session_state.configs[t.id]['background_disk'])
        self.assertIsNone(at.session_state.configs[t.id]['background_ring'])
        widget(at.button,'应用设置').click().run()
        self.assertEqual(at.session_state.configs[t.id]['background_ring'],b.id)
        self.assertIsNone(at.session_state.configs[u.id]['background_disk'])
        self.assertEqual(at.session_state.configs[u.id]['background_ring'],b.id)
        self.clean(at)
