"""Small import overview; edits reuse stored-record intents and explicit scopes."""
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,QComboBox,QLineEdit
from application.editing import condition_updates
from application.references import REFERENCE_PRESETS
from batch_settings import build_batch_updates
from experiment_conditions import missing_conditions,apply_conditions
from orr_core import DataError,select_segment


def common(records,ids,field):
    values=[records[i].get(field) for i in ids]
    return values[0] if values and all(value==values[0] for value in values) else None


def describe(records,ids,field):
    if not ids:return '未导入'
    values=[records[i].get(field) for i in ids]
    if not all(value==values[0] for value in values):return '各文件不同'
    value=values[0]
    return '未记录' if value is None else f'{value:g}' if isinstance(value,(int,float)) else str(value)


class QuickImport(QWidget):
    def __init__(self,pane):
        super().__init__();self.pane=pane;self.window=pane.window;self.w=pane.w;self.loading=True
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        row=QHBoxLayout();self.summary=QLabel();self.summary.setWordWrap(True);row.addWidget(self.summary,1)
        self.toggle=QPushButton('修改本批常用设置');self.toggle.setCheckable(True);row.addWidget(self.toggle);layout.addLayout(row)
        self.body=QWidget();form=QFormLayout(self.body);form.setContentsMargins(0,4,0,4)
        self.scope=QComboBox();self.scope.addItems(['全部样品','当前组','表格选中']);form.addRow('修改范围',self.scope)
        self.target_note=QLabel();self.target_note.setWordWrap(True);form.addRow(self.target_note)
        self.ph=QLineEdit();form.addRow('pH（理论 RHE 必需）',self.ph)
        self.reference=QComboBox();self.reference.addItem('保持各文件参比／自定义请用高级设置',None)
        for label,preset in REFERENCE_PRESETS.items():
            if preset:self.reference.addItem(label,label)
        form.addRow('参比（25 °C 预设）',self.reference)
        self.background=QComboBox();form.addRow('批量背景',self.background)
        note=QLabel('修改即加入草稿，仅改这一项；核对后直接点“应用并生成极化曲线”。面积、N、人工选段等在逐文件／高级设置中修改。')
        note.setWordWrap(True);form.addRow(note);layout.addWidget(self.body);self.body.hide()
        self.toggle.toggled.connect(self.body.setVisible);self.scope.currentIndexChanged.connect(self.refresh)
        self.ph.editingFinished.connect(lambda:self.window.guard(self.stage_ph))
        self.reference.activated.connect(lambda:self.window.guard(self.stage_reference))
        self.background.activated.connect(lambda:self.window.guard(self.stage_background))
        self.issues=QLabel();self.issues.setWordWrap(True);layout.addWidget(self.issues)
        self.loading=False

    def targets(self):
        records=self.w.get_draft_view()['records'];ids=[i for i,c in records.items() if c.get('role')!='背景']
        if self.scope.currentText()=='表格选中':
            selected={self.pane.model.ids[index.row()] for index in self.pane.table.selectionModel().selectedRows()}
            return [i for i in ids if i in selected]
        if self.scope.currentText()=='当前组':
            source=self.pane.source.currentData();group=records.get(source,{}).get('group')
            return [i for i in ids if records[i].get('group')==group]
        return ids

    def refresh(self,*_):
        if self.loading:return
        self.loading=True
        try:
            view=self.w.get_draft_view();records=view['records'];ids=[i for i,c in records.items() if c.get('role')!='背景']
            targets=self.targets();axis=view['settings'].get('axis','RHE')
            if not ids:
                self.summary.setText('拖入文件即可开始。新文件默认：pH 13 · SCE · 25 °C · 5 mm RDE · N=0.369。')
            else:
                basis='待应用' if view['view_basis']=='candidate' else '已应用'
                self.summary.setText(f'{len(ids)} 个样品 · {axis} 电位 · {basis}条件：pH '+describe(records,ids,'pH')+
                    ' · '+describe(records,ids,'reference')+' · '+describe(records,ids,'temperature_C')+' °C\n'+
                    '盘面积 '+describe(records,ids,'area_cm2')+' cm² · RRDE N '+describe(records,ids,'collection_efficiency')+
                    ' · 扫描 '+describe(records,ids,'mode')+' / '+describe(records,ids,'direction')+
                    ('（含人工选段）' if any(records[i].get('manual_segment') is not None for i in ids) else '（自动选段）'))
            self.target_note.setText(f'只修改 {len(targets)} 个样品；背景条件沿用各自继承策略。')
            self.target_note.setToolTip('、'.join(self.w.state.traces[i].name for i in targets))
            # Read rejected text from its own editing domain; a summary fallback
            # must never reset the editor that needs repair.
            ph_records=self.w.get_edit_configs('quick_conditions:pH')
            value=common(ph_records,targets,'pH');self.ph.setText('' if value is None else str(value))
            self.ph.setPlaceholderText('未记录或各文件不同；填写后统一修改')
            editable=bool(targets) and axis=='RHE' and all(records[i].get('potential_method')=='理论换算' for i in targets)
            self.ph.setEnabled(editable);self.reference.setEnabled(editable)
            self.ph.setToolTip('当前范围使用其他电位方式时，请展开逐文件／高级设置。')
            reference_records=self.w.get_edit_configs('quick_conditions:reference');matched=None
            for label,preset in REFERENCE_PRESETS.items():
                if preset and targets and all(tuple(reference_records[i].get(k) for k in ('reference','filling','ref_V_SHE','reference_preset_C'))==(*preset[:3],25.) for i in targets):matched=label;break
            self.reference.setCurrentIndex(max(self.reference.findData(matched),0))
            self.background.clear();self.background.addItem('保持各文件现有背景','keep');self.background.addItem('全部不扣背景','none')
            for ident,trace in self.w.state.traces.items():
                if records[ident].get('role')=='背景':self.background.addItem(trace.name,ident)
            self.background.setEnabled(bool(targets));self.toggle.setEnabled(bool(ids))
            problems=[]
            if view['view_basis']=='applied_fallback':problems.append('草稿待修正；上方摘要基于已应用设置。'+ '；'.join(str(e['message']) for e in view['errors']))
            for ident in ids:
                errors=missing_conditions(view['configs'][ident],axis=axis)
                try:select_segment(self.w.state.traces[ident],records[ident])
                except (DataError,ValueError,TypeError) as exc:errors.append(str(exc))
                if errors:problems.append(self.w.state.traces[ident].name+'：'+'；'.join(errors))
            missing_rpm=sum(records[i].get('rpm') is None for i in ids)
            text=(f'需处理 {len(problems)} 项：'+problems[0] if problems else '核对表格后可直接生成极化曲线，无需逐项重填。')
            if missing_rpm:text+=f' 另有 {missing_rpm} 个转速未填写（仅 K–L 需要，可双击表格手填）。'
            self.issues.setText(text);self.issues.setToolTip('\n'.join(problems));self.problems=problems
        finally:self.loading=False

    def stage_conditions(self,values,domain):
        targets=self.targets()
        if not targets:raise DataError('请选择至少一个样品。')
        try:
            view=self.w.get_draft_view()
            updates=condition_updates(view,targets,values,names={i:t.name for i,t in self.w.state.traces.items()})
            if view['view_basis']=='applied_fallback':
                # An explicit repair back to an applied value must replace this
                # domain's earlier accepted intent, even when the diff is empty.
                for ident in targets:
                    after=deepcopy(view['records'][ident]);apply_conditions(after,values,background_ph_edit=False)
                    updates[ident]={**updates.get(ident,{}),**{k:deepcopy(after[k]) for k in values},
                        'parameter_sources':{k:after['parameter_sources'][k] for k in values}}
            if not self.w.stage_config_updates(domain,updates):raise DataError(self.w.state.get('draft_error','修改未接受。'))
        except (DataError,ValueError,TypeError) as exc:
            self.w.reject_config_updates(domain,{i:deepcopy(values) for i in targets},str(exc))
            self.pane.on_change();raise
        self.pane.on_change()

    def stage_ph(self):
        if self.loading or not self.ph.isEnabled():return
        text=self.ph.text().strip()
        if not text:return # A mixed/unknown placeholder is not an instruction to clear records.
        try:value=float(text)
        except ValueError:value=text
        if all(self.w.get_edit_configs('quick_conditions:pH')[i].get('pH')==value for i in self.targets()):return
        self.stage_conditions({'pH':value},'quick_conditions:pH')

    def stage_reference(self):
        if self.loading:return
        preset=REFERENCE_PRESETS.get(self.reference.currentData())
        if preset:
            reference,filling,value,source=preset
            self.stage_conditions(dict(reference=reference,filling=filling,ref_V_SHE=value,reference_source=source,reference_preset_C=25.),'quick_conditions:reference')
        else:self.pane.show_details(0)

    def stage_background(self):
        if self.loading:return
        value=self.background.currentData()
        if value=='keep':return
        view=self.w.get_draft_view()
        if view['view_basis']=='applied_fallback':raise DataError('请先修正已有草稿。')
        updates,_=build_batch_updates(self.w.state.traces,view['records'],self.targets(),
            background_action='none' if value=='none' else 'paired',disk=value)
        if not self.w.stage_config_updates('quick_background',updates):raise DataError(self.w.state.get('draft_error','修改未接受。'))
        self.pane.on_change()

    def plot(self):
        self.window.ensure_idle();self.stage_ph()
        if self.w.get_draft_view()['view_basis']=='applied_fallback':raise DataError('请先修正待处理的草稿。')
        ids=self.targets()
        if not ids:raise DataError('请先导入或选中样品。')
        curves=self.window.analyses['curves'];curves.refresh();curves.group.setCurrentText('全部')
        for index in range(curves.files.count()):
            item=curves.files.item(index);item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in ids else Qt.CheckState.Unchecked)
        curves.channel.setCurrentIndex(curves.channel.findData('disk'))
        self.window.tabs.setCurrentIndex(1);return curves.request_calculate()
