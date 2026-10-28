"""Native condition, scan and background workspaces over shared editing intents."""
from copy import deepcopy
import json
import math
from PySide6.QtCore import Qt,QItemSelectionModel
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QTabWidget,QScrollArea,
    QPushButton,QLabel,QLineEdit,QComboBox,QCheckBox,QTableView,QTableWidget,QTableWidgetItem,
    QHeaderView,QAbstractItemView,QGroupBox,QSplitter,QMessageBox,QMenu)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from application.editing import condition_updates,stage_background_mode,effective_independent_values
from application.figures import new_figure
from application.references import REFERENCE_PRESETS
from background_conditions import INHERITED_FIELDS
from batch_settings import build_batch_updates
from experiment_conditions import area_from_diameter
from background_pairing import apply_background_binding
from orr_core import DataError,scan_segments,select_segment,fill_missing_rpms
from desktop.models import FileModel,ChoiceDelegate

LABELS={'potential_method':'电位换算方式','pH':'pH','temperature_C':'温度 / °C','reference':'参比电极',
    'filling':'参比内充液','ref_V_SHE':'E_ref vs SHE / V','reference_source':'参比来源',
    'reference_preset_C':'参比预设温度 / °C','rhe_offset_V':'实测 RHE 总偏移 / V'}
STATUSES={'following':'跟随中','conflict':'条件冲突','waiting':'等待条件','unbound':'尚未关联',
    'independent':'独立','invalid':'无效','not_required':'当前方式不需要','manual_missing':'待填写'}
MODE_LABELS={'follow':'整组跟随关联样品','independent':'独立设置','legacy_ph':'旧版 pH 兼容'}
NUMERIC={'pH','temperature_C','ref_V_SHE','reference_preset_C','rhe_offset_V','disk_diameter_mm','area_cm2',
         'collection_efficiency','ring_potential_V','ir_ohm'}


def combo(items):
    widget=QComboBox()
    for item in items:
        label,value=item if isinstance(item,tuple) else (item,item);widget.addItem(label,value)
    return widget


def table_from_rows(widget,rows):
    keys=list(dict.fromkeys(key for row in rows for key in row));widget.setColumnCount(len(keys));widget.setRowCount(len(rows));widget.setHorizontalHeaderLabels(keys)
    for r,row in enumerate(rows):
        for c,key in enumerate(keys):
            value=row.get(key);text='' if value is None else ('是' if value else '否') if isinstance(value,bool) else str(value)
            widget.setItem(r,c,QTableWidgetItem(text))
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)


class SettingsPane(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.w=window.workspace;self.loading=True
        layout=QVBoxLayout(self);actions=QHBoxLayout()
        for text,operation in (('导入文件',window.choose_files),('打开项目',window.choose_project),('保存分析项目',window.choose_save_project)):
            button=QPushButton(text);button.clicked.connect(lambda checked=False,f=operation:window.guard(f));actions.addWidget(button)
            if text=='保存分析项目':self.project_button=button
        more=QPushButton('更多');menu=QMenu(more)
        for text,operation in (('根据文件名补全空白转速',self.fill_rpm),('移除选中文件',self.remove_selected)):
            action=menu.addAction(text);action.triggered.connect(lambda checked=False,f=operation:window.guard(f))
        more.setMenu(menu);actions.addWidget(more);actions.addStretch();layout.addLayout(actions)
        self.model=FileModel(self.w);self.table=QTableView();self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setItemDelegateForColumn(3,ChoiceDelegate(lambda:[(v,v) for v in ('样品','RRDE','背景')],self.table))
        self.table.setItemDelegateForColumn(5,ChoiceDelegate(self.background_choices,self.table))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column in (1,2,6):self.table.setColumnHidden(column,True)
        self.table.setToolTip('双击可修改用途、转速或背景；样品名、分组和点数可在“显示全部列”中查看。')
        self.table.clicked.connect(lambda index:self.source.setCurrentIndex(self.source.findData(self.model.ids[index.row()])))
        self.model.changed.connect(self.on_change);self.model.failed.connect(lambda text:self.status.setText(text))
        split=QSplitter(Qt.Orientation.Vertical);split.addWidget(self.table);layout.addWidget(split,1)
        self.import_errors=QTableWidget();self.import_errors.setMaximumHeight(110);layout.addWidget(self.import_errors)
        lower=QWidget();self.details_body=lower;ll=QVBoxLayout(lower);split.addWidget(lower);split.setSizes([300,400])
        lower.setMinimumHeight(300);lower.hide();self.editor_split=split
        row=QHBoxLayout();row.addWidget(QLabel('读取设置'));self.source=QComboBox();row.addWidget(self.source,2)
        row.addWidget(QLabel('应用范围'));self.scope=combo(['仅此文件','当前组','全部样品','表格选中']);row.addWidget(self.scope)
        ll.addLayout(row);self.source.currentIndexChanged.connect(self.load)
        self.scope.currentIndexChanged.connect(lambda:self.update_targets())
        self.target_label=QLabel();self.target_label.setWordWrap(True);ll.addWidget(self.target_label)
        tabs=QTabWidget();self.sections=tabs;ll.addWidget(tabs,1);self.fields={};self.labels={}
        experiment=QWidget();ef=QFormLayout(experiment)
        self.axis=combo(['RHE','原始']);self.axis.currentTextChanged.connect(self.stage_axis);ef.addRow('分析与导出电位坐标',self.axis)
        self.method=combo(['理论换算','实测 RHE 总偏移','已是 RHE']);self.method.currentTextChanged.connect(lambda text:self.stage_patch({'potential_method':text}))
        self.fields['potential_method']=self.method;ef.addRow('电位换算方式 *',self.method)
        self.preset=combo(list(REFERENCE_PRESETS));self.preset.currentTextChanged.connect(self.apply_preset);ef.addRow('参比预设（25 °C）',self.preset)
        for field,label in (('pH','pH *'),('temperature_C','温度 / °C *'),('reference','参比电极 *'),('filling','参比内充液'),
                ('ref_V_SHE','E_ref vs SHE / V *'),('rhe_offset_V','实测 RHE 总偏移 / V *')):self.add_field(ef,field,label)
        self.area_mode=combo([('按盘直径计算','diameter'),('直接输入面积','area')]);self.area_mode.currentIndexChanged.connect(self.stage_area)
        ef.addRow('盘面积输入',self.area_mode)
        self.add_field(ef,'disk_diameter_mm','盘直径 / mm *');self.add_field(ef,'area_cm2','盘几何面积 / cm² *')
        self.add_field(ef,'collection_efficiency','RRDE 收集效率 N *')
        ef.addRow(QLabel('新导入：pH 13、SCE、5 mm RDE、RRDE N=0.369；请按实际实验核对。'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(experiment);tabs.addTab(scroll,'实验条件')
        scan=QWidget();sf=QVBoxLayout(scan);scanform=QFormLayout()
        self.direction=combo(['递减','递增']);self.direction.currentTextChanged.connect(lambda text:self.stage_scan({'direction':text}))
        self.mode=combo(['A','B']);self.mode.currentTextChanged.connect(lambda text:self.stage_scan({'mode':text,'manual_segment':None}))
        self.segment=QComboBox();self.segment.currentIndexChanged.connect(self.stage_segment)
        scanform.addRow('扫描方向',self.direction);scanform.addRow('自动规则',self.mode);scanform.addRow('人工选段',self.segment)
        self.binding=combo([('盘环配对','paired'),('分别指定','independent')]);self.disk_bg=QComboBox();self.ring_bg=QComboBox()
        for widget in (self.binding,self.disk_bg,self.ring_bg):widget.currentIndexChanged.connect(self.stage_binding)
        scanform.addRow('背景绑定方式',self.binding);scanform.addRow('盘背景',self.disk_bg);scanform.addRow('环背景',self.ring_bg);sf.addLayout(scanform)
        self.scan_canvas=FigureCanvasQTAgg(new_figure(7,2.4));self.scan_canvas.setMinimumHeight(180);sf.addWidget(self.scan_canvas)
        self.segments_table=QTableWidget();self.segments_table.setMaximumHeight(125);sf.addWidget(self.segments_table)
        advanced=QGroupBox('高级：通道、符号、iR 与环检测');advanced.setCheckable(True);advanced.setChecked(False)
        af=QFormLayout(advanced);self.advanced_body=QWidget();ab=QFormLayout(self.advanced_body);af.addRow(self.advanced_body)
        self.advanced_body.setVisible(False);advanced.toggled.connect(self.advanced_body.setVisible)
        self.scan_fields={}
        for field,label,items in (('disk_channel','盘电流通道',[]),('ring_channel','环电流通道',[]),
                                  ('disk_sign','ORR 盘电流符号',[-1,1]),('ring_sign','产物环电流符号',[1,-1])):
            widget=combo([(str(v),v) for v in items]);widget.currentIndexChanged.connect(lambda index,f=field:self.stage_scan({f:self.scan_fields[f].currentData()}))
            self.scan_fields[field]=widget;ab.addRow(label,widget)
        for field,label in (('electrolyte','电解液 / 浓度 / 气氛'),('reference_source','参比来源'),('reference_preset_C','参比预设温度 / °C'),
                            ('ring_potential_V','环设定电位 / V'),('ring_material','环材料'),('ir_ohm','剩余补偿电阻 / Ω')):
            self.add_field(ab,field,label)
        for field,label in (('ir_enabled','追加 iR 补偿'),('ir_confirmed','已核对补偿未被仪器重复应用'),('ring_detection_confirmed','已确认环电位可定量检测过氧化物')):
            box=QCheckBox(label);box.toggled.connect(lambda value,f=field:self.stage_scan({f:value}));self.scan_fields[field]=box;ab.addRow(box)
        sf.addWidget(advanced);ss=QScrollArea();ss.setWidgetResizable(True);ss.setWidget(scan);tabs.addTab(ss,'逐文件扫描与背景')
        batch=QWidget();bf=QFormLayout(batch)
        self.batch_direction=combo([('保持',None),'递减','递增']);self.batch_mode=combo([('保持',None),'A','B'])
        self.batch_action=combo([('保持','keep'),('盘背景','disk'),('盘环配对','paired'),('分别指定','independent'),('不扣背景','none')])
        self.batch_disk=QComboBox();self.batch_ring=QComboBox()
        for label,widget in (('方向',self.batch_direction),('自动规则',self.batch_mode),('背景操作',self.batch_action),('盘背景',self.batch_disk),('环背景',self.batch_ring)):bf.addRow(label,widget)
        row=QHBoxLayout()
        for text,operation in (('预览批量设置',self.preview_batch),('暂存批量设置',self.stage_batch)):
            b=QPushButton(text);b.clicked.connect(lambda checked=False,f=operation:window.guard(f));row.addWidget(b)
        bf.addRow(row);self.batch_preview=QTableWidget();bf.addRow(self.batch_preview);tabs.addTab(batch,'批量扫描与背景')
        bg=QWidget();bl=QVBoxLayout(bg);self.bg_summary=QLabel();self.bg_summary.setWordWrap(True);bl.addWidget(self.bg_summary)
        row=QHBoxLayout()
        self.to_follow=QPushButton('改为整组跟随');self.to_independent=QPushButton('切到独立设置');self.adopt=QPushButton('用当前有效条件建立独立记录')
        for button,operation in ((self.to_follow,lambda:self.switch_mode('follow')),(self.to_independent,lambda:self.switch_mode('independent')),(self.adopt,self.adopt_effective)):
            button.clicked.connect(lambda checked=False,f=operation:window.guard(f));row.addWidget(button)
        bl.addLayout(row)
        self.legacy=combo([('旧 pH 跟随','follow'),('旧 pH 独立','manual')]);self.legacy.currentIndexChanged.connect(self.stage_legacy)
        bl.addWidget(self.legacy);self.bg_table=QTableWidget();bl.addWidget(self.bg_table);tabs.addTab(bg,'背景实验条件')
        self.status=QLabel('拖入实验文件，核对后统一应用。');self.status.setWordWrap(True);layout.addWidget(self.status)
        row=QHBoxLayout();self.details_toggle=QPushButton('逐文件／高级设置');self.details_toggle.setCheckable(True);row.addWidget(self.details_toggle)
        self.details_toggle.toggled.connect(lower.setVisible)
        self.all_columns=QCheckBox('显示全部列');self.all_columns.toggled.connect(self.show_columns);row.addWidget(self.all_columns)
        self.apply_button=QPushButton('应用设置');self.apply_button.clicked.connect(lambda:window.guard(window.apply));row.addWidget(self.apply_button)
        self.discard_button=QPushButton('放弃未应用修改');self.discard_button.clicked.connect(lambda:window.guard(window.discard));row.addWidget(self.discard_button)
        self.draft_button=QPushButton('查看草稿详情');self.draft_button.clicked.connect(self.show_draft);row.addWidget(self.draft_button);row.addStretch()
        self.plot_button=QPushButton('生成极化曲线');self.plot_button.clicked.connect(lambda:window.guard(self.quick.plot));row.addWidget(self.plot_button);layout.addLayout(row)
        from desktop.quick_import import QuickImport
        self.quick=QuickImport(self);layout.insertWidget(1,self.quick)
        self.loading=False
        self.sections.currentChanged.connect(lambda:self.update_targets())
        self.table.selectionModel().selectionChanged.connect(lambda:self.quick.refresh() if not self.loading else None)

    def show_columns(self,visible):
        for column in (1,2,6):self.table.setColumnHidden(column,not visible)

    def show_details(self,section=0):
        self.details_toggle.setChecked(True);self.sections.setCurrentIndex(section)

    def update_quick_actions(self):
        dirty=self.w.has_draft();busy=bool(getattr(self.window,'jobs',None) and self.window.jobs.busy)
        self.plot_button.setText('应用并生成极化曲线' if dirty else '生成极化曲线')
        self.plot_button.setEnabled(bool(self.w.state.traces) and not busy)
        for button in (self.apply_button,self.discard_button,self.draft_button):button.setVisible(dirty)
        self.apply_button.setEnabled(not busy);self.discard_button.setEnabled(not busy)

    def add_field(self,form,field,label):
        widget=QLineEdit();widget.editingFinished.connect(lambda f=field:self.window.guard(lambda:self.stage_field(f)))
        self.fields[field]=widget;self.labels[field]=QLabel(label);form.addRow(self.labels[field],widget)

    def background_choices(self):
        records=self.w.get_edit_configs('metadata')
        return [('不扣除',None)]+[(t.name,i) for i,t in self.w.state.traces.items() if records[i].get('role')=='背景']

    def refresh(self):
        selected=[self.model.ids[i.row()] for i in self.table.selectionModel().selectedRows()]
        self.loading=True;current=self.source.currentData();self.source.clear();self.model.reload()
        for ident in selected:
            if ident in self.model.ids:self.table.selectionModel().select(self.model.index(self.model.ids.index(ident),0),QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
        table_from_rows(self.import_errors,self.w.state.import_errors);self.import_errors.setVisible(bool(self.w.state.import_errors))
        for ident,trace in self.w.state.traces.items():self.source.addItem(trace.name,ident)
        self.source.setCurrentIndex(max(self.source.findData(current),0))
        for widget in (self.disk_bg,self.ring_bg,self.batch_disk,self.batch_ring):
            previous=widget.currentData();widget.clear()
            if widget in (self.batch_disk,self.batch_ring):widget.addItem('保持','keep')
            for label,value in self.background_choices():widget.addItem(label,value)
            widget.setCurrentIndex(max(widget.findData(previous),0))
        self.axis.setCurrentText(self.w.get_edit_settings().get('axis','RHE'))
        self.loading=False;self.load()

    def domain(self):
        ident=self.source.currentData();record=self.w.get_edit_configs().get(ident,{})
        return f'background_conditions:{ident}' if record.get('role')=='背景' else f'conditions:{ident}'

    def targets(self):
        ident=self.source.currentData();records=self.w.get_edit_configs()
        if not ident:return []
        if self.sections.currentIndex() in (1,3):return [ident]
        scope=self.scope.currentText()
        if scope=='仅此文件':return [ident]
        if scope=='表格选中':return [self.model.ids[i.row()] for i in self.table.selectionModel().selectedRows()]
        return [i for i,c in records.items() if c.get('role')!='背景' and (scope=='全部样品' or c.get('group')==records[ident].get('group'))]

    def update_targets(self):
        per_file=self.sections.currentIndex() in (1,3);self.scope.setEnabled(not per_file)
        targets=self.targets();self.target_label.setText(('此页只修改当前文件；' if per_file else '')+f'本次修改目标：{len(targets)} 个文件 · '+ '、'.join(self.w.state.traces[i].name for i in targets))

    def load(self,*_):
        if self.loading:return
        ident=self.source.currentData();self.loading=True
        self.segment.clear();self.segment.addItem('自动选择最后完整支线',None)
        if ident:
            view=self.w.get_draft_view();cfg=self.w.get_edit_configs(self.domain())[ident];effective=view['configs'].get(ident,{})
            info=effective.get('background_conditions',{});states=info.get('field_states',{})
            for field,widget in self.fields.items():
                state=states.get(field,{});editable=state.get('editable',True)
                value=cfg.get(field) if editable else effective.get(field)
                if isinstance(widget,QComboBox):widget.setCurrentText(str(value) if value is not None else '')
                else:widget.setText('' if value is None else str(value))
                widget.setEnabled(editable)
                if field in self.labels:self.labels[field].setToolTip('来源：'+str(effective.get('parameter_sources',{}).get(field,'')))
            self.preset.setEnabled(all(states.get(field,{}).get('editable',True) for field in ('reference','filling','ref_V_SHE')))
            for key,preset in REFERENCE_PRESETS.items():
                if preset and tuple(cfg.get(k) for k in ('reference','filling','ref_V_SHE'))==preset[:3]:self.preset.setCurrentText(key);break
            else:self.preset.setCurrentIndex(0)
            self.area_mode.setCurrentIndex(max(self.area_mode.findData(cfg.get('area_mode','area')),0))
            for widget,field in ((self.direction,'direction'),(self.mode,'mode'),(self.binding,'background_mode'),(self.disk_bg,'background_disk'),(self.ring_bg,'background_ring')):
                widget.setCurrentIndex(max(widget.findData(cfg.get(field)),0))
            for field,widget in self.scan_fields.items():
                if isinstance(widget,QCheckBox):widget.setChecked(bool(cfg.get(field)))
                else:
                    if field.endswith('_channel'):
                        widget.clear();widget.addItem('未指定',None)
                        for index,name in enumerate(self.w.state.traces[ident].columns[1:]):widget.addItem(f'{index+1} · {name}',index)
                    widget.setCurrentIndex(max(widget.findData(cfg.get(field)),0))
            self.disk_bg.setEnabled(cfg.get('role')!='背景');self.ring_bg.setEnabled(cfg.get('role')!='背景' and cfg.get('background_mode')=='independent')
            self.binding.setEnabled(cfg.get('role')!='背景')
            try:
                segments=scan_segments(self.w.state.traces[ident]);table_from_rows(self.segments_table,segments)
                for s in segments:self.segment.addItem(f"第 {s['segment']} 段 · {s['direction']} · {'完整' if s['complete'] else '不完整'}",s['segment'])
                self.segment.setCurrentIndex(max(self.segment.findData(cfg.get('manual_segment')),0))
                if not getattr(self.window,'jobs',None) or not self.window.jobs.busy:
                    self.draw_scan(ident,cfg)
            except DataError as exc:self.status.setText(str(exc));table_from_rows(self.segments_table,[])
            self.render_background(view,info)
            method=cfg.get('potential_method');theory=self.axis.currentText()=='RHE' and method=='理论换算'
            for field in ('pH','temperature_C','ref_V_SHE'):self.labels[field].setText(LABELS[field]+(' *' if theory else '（记录保留）'))
            self.fields['rhe_offset_V'].setVisible(method=='实测 RHE 总偏移');self.labels['rhe_offset_V'].setVisible(method=='实测 RHE 总偏移')
            self.fields['disk_diameter_mm'].setVisible(cfg.get('area_mode')=='diameter');self.labels['disk_diameter_mm'].setVisible(cfg.get('area_mode')=='diameter')
            self.fields['area_cm2'].setReadOnly(cfg.get('area_mode')=='diameter')
            self.labels['collection_efficiency'].setText('RRDE 收集效率 N'+(' *' if len(self.w.state.traces[ident].columns)>=3 and cfg.get('role')!='背景' else '（RRDE 使用）'))
            if view['view_basis']=='applied_fallback':self.status.setText('草稿待修正；下方条件基于已应用设置。 '+ '；'.join(str(e['message']) for e in view['errors']))
            elif self.w.has_draft():self.status.setText(f"有未应用修改：{len(view['staged_edits'])} 个编辑域。可查看草稿详情，核对后统一应用。")
            else:self.status.setText(f'已应用 · 配置修订 {self.w.state.revision}。* 为当前方式必填；空白表示未知。')
        else:
            for widget in self.fields.values():widget.setEnabled(False)
        self.loading=False;self.update_targets()
        if hasattr(self,'quick'):self.quick.refresh();self.update_quick_actions()

    def on_change(self):
        self.load();self.window.calculate_button.setText('应用并生成极化曲线' if self.w.has_draft() else '生成极化曲线')
        if hasattr(self.window,'update_actions'):self.window.update_actions()

    def draw_scan(self,ident,cfg):
        trace=self.w.state.traces[ident];fig=new_figure(7,2.4);ax=fig.subplots();ax.plot(trace.values[:,0],color='#aab5b9')
        try:
            chosen=select_segment(trace,cfg);a,b=chosen['start'],chosen['end'];ax.plot(range(a,b+1),trace.values[a:b+1,0],color='#167d8d',lw=2)
        except DataError as exc:ax.set_title(str(exc),fontsize=8)
        ax.set(xlabel='Acquisition row (zero-based)',ylabel='Original E / V');self.scan_canvas.figure=fig;fig.set_canvas(self.scan_canvas);self.scan_canvas.draw()

    def refresh_scan(self):
        ident=self.source.currentData()
        if ident in self.w.state.traces:
            try:self.draw_scan(ident,self.w.get_edit_configs(self.domain())[ident])
            except (DataError,ValueError,IndexError):pass

    def show_draft(self):
        view=self.w.get_draft_view();box=QMessageBox(self);box.setWindowTitle('本次修改与拒绝输入')
        box.setText('仅明确应用后生效；拒绝或矛盾的修改必须先修正。')
        box.setDetailedText(json.dumps({key:view[key] for key in ('view_basis','staged_edits','staged_setting_edits','rejected_edits','errors')},ensure_ascii=False,indent=2,default=str));box.exec()

    def stage_field(self,field):
        if self.loading:return
        text=self.fields[field].text().strip();value=text
        if field in NUMERIC:
            try:value=float(text) if text else None
            except ValueError:pass # Keep rejected raw text available for correction.
        if self.w.get_edit_configs(self.domain())[self.source.currentData()].get(field)==value:return
        if field in ('disk_diameter_mm','area_cm2'):return self.stage_area()
        if field=='ir_ohm':return self.stage_scan({field:value})
        patch={field:value}
        if field in ('reference','filling','ref_V_SHE'):patch.update(reference_preset_C=None,reference_source='用户输入')
        self.stage_patch(patch)

    def stage_patch(self,patch):
        if self.loading or not self.source.currentData():return
        targets=self.targets();domain=self.domain()
        if not targets:
            self.w.reject_config_updates(domain,None,'请选择至少一个目标文件。');self.status.setText('请选择至少一个目标文件。');return
        try:
            view=self.w.get_draft_view()
            if all(all(self.w.get_edit_configs(domain)[i].get(k)==v for k,v in patch.items()) for i in targets):return
            updates=condition_updates(view,targets,patch,names={i:t.name for i,t in self.w.state.traces.items()})
            self.w.stage_config_updates(domain,updates)
        except (DataError,ValueError,TypeError) as exc:self.w.reject_config_updates(domain,{i:deepcopy(patch) for i in targets},str(exc))
        self.on_change()

    def apply_preset(self,text):
        if self.loading:return
        preset=REFERENCE_PRESETS.get(text)
        if preset:
            reference,filling,value,source=preset
            self.stage_patch(dict(reference=reference,filling=filling,ref_V_SHE=value,reference_source=source,reference_preset_C=25.))

    def stage_area(self,*_):
        if self.loading:return
        try:
            mode=self.area_mode.currentData()
            if mode=='diameter':
                text=self.fields['disk_diameter_mm'].text().strip();diameter=float(text) if text else None
                values=dict(area_mode=mode,disk_diameter_mm=diameter,area_cm2=area_from_diameter(diameter) if diameter is not None else None)
            else:
                text=self.fields['area_cm2'].text().strip();values=dict(area_mode='area',area_cm2=float(text) if text else None,disk_diameter_mm=None)
            self.stage_patch(values)
        except (ValueError,DataError) as exc:
            self.w.reject_config_updates(self.domain(),None,str(exc));self.status.setText(str(exc))

    def stage_axis(self,text):
        if not self.loading:self.w.stage_settings_updates('axis',{'axis':text});self.on_change()

    def stage_scan(self,patch):
        if self.loading or not self.source.currentData():return
        ident=self.source.currentData();self.w.stage_config_updates('scan:'+ident,{ident:patch});self.on_change()

    def stage_segment(self,*_):
        if self.loading or not self.source.currentData():return
        value=self.segment.currentData();patch={'manual_segment':value}
        if value:patch['direction']=next(s['direction'] for s in scan_segments(self.w.state.traces[self.source.currentData()]) if s['segment']==value)
        self.stage_scan(patch)

    def stage_binding(self,*_):
        if self.loading or not self.source.currentData():return
        ident=self.source.currentData();records=self.w.get_edit_configs('scan:'+ident);cfg=deepcopy(records[ident])
        try:
            apply_background_binding(ident,cfg,self.w.state.traces,records,self.binding.currentData(),self.disk_bg.currentData(),self.ring_bg.currentData())
            self.stage_scan({k:cfg[k] for k in ('background_mode','background_disk','background_ring','background_reviewed')})
        except DataError as exc:self.w.reject_config_updates('scan:'+ident,None,str(exc));self.status.setText(str(exc))

    def batch_values(self):
        view=self.w.get_draft_view()
        if view['view_basis']=='applied_fallback':raise DataError('请先修正已有草稿。')
        return build_batch_updates(self.w.state.traces,view['records'],self.targets(),direction=self.batch_direction.currentData(),mode=self.batch_mode.currentData(),
            background_action=self.batch_action.currentData(),disk=self.batch_disk.currentData(),ring=self.batch_ring.currentData())

    def preview_batch(self):
        updates,rows=self.batch_values();table_from_rows(self.batch_preview,rows);return updates,rows

    def stage_batch(self):
        updates,rows=self.preview_batch()
        if updates:self.w.stage_config_updates('batch_scan_background',updates)
        self.on_change();return updates

    def render_background(self,view,info):
        is_bg=bool(info);usable=is_bg and view['view_basis'] in ('applied','candidate') and info.get('status')=='following' and info.get('mode')=='follow'
        self.adopt.setEnabled(usable);self.to_follow.setEnabled(is_bg and info.get('mode')!='follow');self.to_independent.setEnabled(is_bg and info.get('mode')!='independent')
        self.bg_summary.setText((f"模式：{MODE_LABELS.get(info.get('mode'),info.get('mode'))} · {STATUSES.get(info.get('status'),info.get('status'))} · {info.get('detail','')}\n关联样品："+
            '、'.join(s['filename'] for s in info.get('linked_samples',[]))) if is_bg else '选择背景文件后查看继承策略与独立记录。')
        rows=[]
        for field in INHERITED_FIELDS if info else []:
            state=info['field_states'][field]
            rows.append({'字段':LABELS[field],'有效值':info['effective'].get(field),'状态':STATUSES.get(state['status'],state['status']),
                '可编辑':state['editable'],'独立记录':info['independent'].get(field),'来源':info['effective_sources'].get(field),'说明':state.get('detail','')})
        table_from_rows(self.bg_table,rows);self.legacy.setVisible(info.get('mode')=='legacy_ph')
        self.legacy.setCurrentIndex(max(self.legacy.findData(info.get('legacy_ph_mode')),0))

    def switch_mode(self,mode):
        ident=self.source.currentData();stage_background_mode(self.w,ident,mode);self.load()

    def adopt_effective(self):
        view=self.w.get_draft_view();ident=self.source.currentData();info=view['configs'][ident].get('background_conditions',{})
        if view['view_basis'] not in ('applied','candidate') or info.get('status')!='following' or info.get('mode')!='follow':raise DataError('当前没有可完整复制的有效条件。')
        stage_background_mode(self.w,ident,'independent',values=effective_independent_values(info));self.load()

    def stage_legacy(self,*_):
        if not self.loading:
            ident=self.source.currentData();self.w.stage_config_updates('background_ph:'+ident,{ident:{'background_ph_mode':self.legacy.currentData(),'background_ph_legacy':False}});self.load()

    def fill_rpm(self):
        records=deepcopy(self.w.get_edit_configs('metadata'));before=deepcopy(records);count,_=fill_missing_rpms(self.w.state.traces,records)
        patches={i:{k:v for k,v in c.items() if k.startswith('rpm')} for i,c in records.items() if any(c.get(k)!=before[i].get(k) for k in c if k.startswith('rpm'))}
        if patches:self.w.stage_config_updates('metadata',patches)
        self.refresh();self.status.setText(f'已暂存补全 {count} 个空白转速。')

    def remove_selected(self):
        ids=[self.model.ids[i.row()] for i in self.table.selectionModel().selectedRows()]
        if ids:self.w.remove_files(ids);self.window.refresh()
