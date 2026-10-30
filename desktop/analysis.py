"""Native analysis workspaces. Calculations and export bytes use shared services."""
from copy import deepcopy
import hashlib
import math
from PySide6.QtCore import Qt,QItemSelectionModel
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QSplitter,QScrollArea,
    QListWidget,QListWidgetItem,QComboBox,QLabel,QPushButton,QCheckBox,QLineEdit,QSpinBox,
    QDoubleSpinBox,QGroupBox,QTableWidget,QColorDialog)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg,NavigationToolbar2QT
from application.curves import calculate_curves,PALETTE
from application.analysis import clear_result
from application.results import complete_kl,complete_rrde,kl_figures,publish_figures,record_kl_parameters
from application.figures import new_figure
from application.editing import condition_updates
from plot_smoothing import PRESET_WINDOWS,smoothing_defaults
from orr_core import DataError,KOH_PRESET,kl_condition_differences
from orr_core import json_bytes
from application.potentials import potential_options
from desktop.settings import combo,table_from_rows

FIGURE_LABELS={'polarization':'极化曲线','ring_current':'环电流比较','kl_electron_number':'K–L 表观电子数',
    'kl_two_four_e_model':'K–L 两路径模型','kl_fit':'K–L 线性拟合','rrde_selectivity':'RRDE 产率与电子数','rrde_two_four_e':'RRDE 两产物模型'}


class AnalysisPane(QWidget):
    def __init__(self,window,kind):
        super().__init__();self.window=window;self.w=window.workspace;self.kind=kind;self.loading=True
        self.known_ids=set();self.workspace_epoch=None;self.last_revision=None;self.figures={};self.saved=None;self.efficiency_edits={}
        layout=QVBoxLayout(self);split=QSplitter();layout.addWidget(split,1)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(280);scroll.setMaximumWidth(390)
        controls=QWidget();left=QVBoxLayout(controls);scroll.setWidget(controls);split.addWidget(scroll)
        left.addWidget(QLabel('参与分析的样品'));self.group=QComboBox();self.group.currentIndexChanged.connect(self.group_changed);left.addWidget(self.group)
        self.files=QListWidget();self.files.setMinimumHeight(140);self.files.itemChanged.connect(self.selection_changed);left.addWidget(self.files)
        row=QHBoxLayout()
        for text,checked in (('全选',True),('清空',False)):
            b=QPushButton(text);b.clicked.connect(lambda checked_arg=False,v=checked:self.check_all(v));row.addWidget(b)
        left.addLayout(row)
        conditions=QPushButton('修改实验条件／扫描与背景');conditions.clicked.connect(self.open_conditions);left.addWidget(conditions)
        if kind=='curves':self.curve_controls(left)
        elif kind=='kl':self.kl_controls(left)
        else:self.rrde_controls(left)
        left.addStretch()
        main=QWidget();ml=QVBoxLayout(main);split.addWidget(main);split.setSizes([310,900])
        actions=QHBoxLayout();self.calculate_button=QPushButton();self.calculate_button.clicked.connect(lambda:window.guard(self.request_calculate));actions.addWidget(self.calculate_button)
        self.csv_button=QPushButton('保存绘图 CSV');self.csv_button.clicked.connect(lambda:window.guard(self.request_csv));actions.addWidget(self.csv_button)
        self.png_button=QPushButton('保存 PNG');self.png_button.clicked.connect(lambda:window.guard(self.request_png));actions.addWidget(self.png_button)
        actions.addStretch();ml.addLayout(actions)
        self.note=QLabel('选择文件并计算。');self.note.setWordWrap(True);ml.addWidget(self.note)
        self.figure_choice=QComboBox();self.figure_choice.currentIndexChanged.connect(lambda:self.show_figure(self.figure_choice.currentData()));ml.addWidget(self.figure_choice)
        self.canvas=FigureCanvasQTAgg(new_figure());ml.addWidget(NavigationToolbar2QT(self.canvas,self));ml.addWidget(self.canvas,1)
        self.fit_potential=QComboBox();self.fit_potential.currentIndexChanged.connect(self.request_fit)
        self.fit_potential.setVisible(kind=='kl');ml.addWidget(self.fit_potential)
        self.details=QGroupBox('处理记录、条件差异与异常点');self.details.setCheckable(True);self.details.setChecked(False)
        dl=QVBoxLayout(self.details);self.table=QTableWidget();self.table.setMaximumHeight(220);dl.addWidget(self.table);self.table.setVisible(False);self.details.toggled.connect(self.table.setVisible);ml.addWidget(self.details)
        if kind=='curves':
            self.potential_result=QWidget();pr=QVBoxLayout(self.potential_result);pr.setContentsMargins(0,0,0,0)
            self.potential_note=QLabel('阈值起始电位与平台半波电位 · 处理后未平滑盘电流；自动平台须核对。');self.potential_note.setWordWrap(True);pr.addWidget(self.potential_note)
            self.potential_table=QTableWidget();self.potential_table.setMaximumHeight(120);pr.addWidget(self.potential_table)
            self.potential_csv=QPushButton('保存电位指标 CSV');self.potential_csv.clicked.connect(lambda:window.guard(lambda:self.request_export('polarization_potentials.csv',recompute=True)));pr.addWidget(self.potential_csv)
            ml.addWidget(self.potential_result);self.potential_result.hide()
        extra=QHBoxLayout();self.extra=QComboBox();extra.addWidget(QLabel('更多导出'));extra.addWidget(self.extra,1)
        button=QPushButton('保存所选文件');button.clicked.connect(lambda:window.guard(self.request_extra));extra.addWidget(button);ml.addLayout(extra);self.extra_button=button
        self._needs_blank=False
        self.loading=False

    def line(self,form,label,key,default=''):
        widget=QLineEdit(str(default));form.addRow(label,widget);return widget

    def curve_controls(self,left):
        form=QFormLayout();self.curve_form=form;self.channel=combo([('盘电流','disk'),('环电流','ring')]);self.channel.currentIndexChanged.connect(self.channel_changed);form.addRow('绘制通道',self.channel)
        self.unit=combo([('电流 / mA','mA'),('电流密度 / mA·cm⁻²','mA/cm2')]);self.unit.currentIndexChanged.connect(self.display_changed);form.addRow('纵坐标',self.unit)
        self.background_view=combo(['处理后','未扣背景']);self.background_view.currentIndexChanged.connect(self.display_changed);form.addRow('环背景显示',self.background_view)
        left.addLayout(form)
        self.smooth=QCheckBox('启用曲线平滑（仅绘图）');self.smooth.toggled.connect(self.display_changed);left.addWidget(self.smooth)
        self.smooth_body=QWidget();form=QFormLayout(self.smooth_body);self.smooth_form=form
        self.strength=combo(['弱','中','强','自定义']);self.strength.currentIndexChanged.connect(self.display_changed);form.addRow('平滑强度',self.strength)
        self.window_points=QSpinBox();self.window_points.setRange(5,1001);self.window_points.setSingleStep(2);self.window_points.setValue(11);self.window_points.valueChanged.connect(self.display_changed);form.addRow('自定义奇数窗口',self.window_points)
        self.unsmoothed=QCheckBox('显示浅色未平滑参考线');self.unsmoothed.setChecked(True);self.unsmoothed.toggled.connect(self.display_changed);form.addRow(self.unsmoothed);left.addWidget(self.smooth_body)
        label=QLabel('平滑不进入 K–L／RRDE；缺口不补齐，不等间距和短段保留原值。');label.setWordWrap(True);left.addWidget(label)
        self.potential_settings=QGroupBox('起始／半波电位设置');self.potential_settings.setCheckable(True);self.potential_settings.setChecked(False)
        pl=QVBoxLayout(self.potential_settings);self.potential_body=QWidget();pf=QFormLayout(self.potential_body);pl.addWidget(self.potential_body)
        self.potential_body.hide();self.potential_settings.toggled.connect(self.potential_body.setVisible)
        self.onset_threshold=QLineEdit('0.1');pf.addRow('起始电位还原阈值 *',self.onset_threshold)
        self.onset_unit=combo([('mA/cm²（需盘面积）','mA/cm2'),('mA','mA')]);pf.addRow('阈值单位',self.onset_unit)
        self.plateau_mode=combo([('自动最低 20% 电位区间（候选）','auto'),('手动指定平台区间','manual')]);pf.addRow('极限平台',self.plateau_mode)
        self.plateau_start=QLineEdit();self.plateau_end=QLineEdit();pf.addRow('平台起点 / V *',self.plateau_start);pf.addRow('平台终点 / V *',self.plateau_end)
        self.potential_baseline=QLineEdit('0');pf.addRow('ORR 基线电流 / mA',self.potential_baseline)
        self.potential_markers=QCheckBox('图中标注：圆点起始、方点半波（未平滑）');pf.addRow(self.potential_markers)
        note=QLabel('电位按当前坐标；还原方向取正。起始为基线＋阈值，半波为基线到平台的半高。默认基线为 0；未扣净背景时可改基线。平台至少 5 点，电流跨度≤波高 10%；无平台／多交点留空。');note.setWordWrap(True);pf.addRow(note)
        self.potential_form=pf;left.addWidget(self.potential_settings)
        for widget in (self.onset_threshold,self.plateau_start,self.plateau_end,self.potential_baseline):widget.editingFinished.connect(self.display_changed)
        for widget in (self.onset_unit,self.plateau_mode):widget.currentIndexChanged.connect(self.display_changed)
        self.potential_markers.toggled.connect(self.display_changed)
        style=QGroupBox('图形设置');style.setCheckable(True);style.setChecked(False);sf=QVBoxLayout(style);body=QWidget();form=QFormLayout(body);sf.addWidget(body);body.setVisible(False);style.toggled.connect(body.setVisible)
        self.style_fields={}
        for key,label,default in (('title','图标题','ORR polarization curves'),('line_width','线宽',1.8),('width','宽度 / 英寸',8),('height','高度 / 英寸',5),
            ('xmin','横轴最小（空白自动）',''),('xmax','横轴最大（空白自动）',''),('ymin','纵轴最小（空白自动）',''),('ymax','纵轴最大（空白自动）','')):
            widget=self.line(form,label,key,default);widget.editingFinished.connect(self.display_changed);self.style_fields[key]=widget
        self.legend=QCheckBox('显示图例');self.legend.setChecked(True);self.legend.toggled.connect(self.display_changed);form.addRow(self.legend)
        self.color_file=QComboBox();form.addRow('曲线颜色',self.color_file);color=QPushButton('选择颜色');color.clicked.connect(self.choose_color);form.addRow(color);left.addWidget(style)

    def kl_controls(self,left):
        form=QFormLayout();self.kl_form=form;self.custom_constants={};self.previous_scheme='koh_25C'
        self.scheme=combo([('O2 / 0.1 M KOH / 25 °C','koh_25C'),('自定义物性参数','custom')]);self.scheme.currentIndexChanged.connect(self.scheme_changed);form.addRow('物性方案 *',self.scheme)
        self.constants={}
        for key,label in (('C','氧浓度 C / mol·cm⁻³ *'),('D','扩散系数 D / cm²·s⁻¹ *'),('nu','运动黏度 ν / cm²·s⁻¹ *')):
            widget=self.line(form,label,key,KOH_PRESET[key]);widget.editingFinished.connect(self.input_changed);self.constants[key]=widget
        self.source=self.line(form,'来源与适用条件','source',KOH_PRESET['source']);self.source.editingFinished.connect(self.input_changed)
        self.start=self.line(form,'分析起点 / V *','start');self.end=self.line(form,'分析终点 / V *','end')
        for widget in (self.start,self.end):widget.editingFinished.connect(self.input_changed)
        self.count=QSpinBox();self.count.setRange(1,500);self.count.setValue(30);self.count.valueChanged.connect(self.input_changed);form.addRow('等间距电位点数',self.count)
        left.addLayout(form);self.coverage=QLabel('共同覆盖仅表示数据范围，不等于 ORR 适用区间。');self.coverage.setWordWrap(True);left.addWidget(self.coverage)
        coverage=QPushButton('填入当前共同覆盖范围');coverage.clicked.connect(lambda:self.window.guard(self.request_coverage));left.addWidget(coverage)
        self.confirmed=QCheckBox('已核对同一电极／相同条件，且物性适用 *');self.confirmed.toggled.connect(self.input_changed);left.addWidget(self.confirmed)
        label=QLabel('K–L 给出表观电子数；两路径比例是模型估算。不要按 n 是否落入 2–4 选择区间。');label.setWordWrap(True);left.addWidget(label)

    def rrde_controls(self,left):
        form=QFormLayout();self.efficiency=QLineEdit();self.efficiency.editingFinished.connect(self.stage_efficiency);form.addRow('所选文件收集效率 N *',self.efficiency);left.addLayout(form)
        label=QLabel('新 RRDE 默认 N=0.369。文件值不同时保持各自设置；主动填写会暂存到所有选中文件。低电流阈值沿用项目记录。环电位与定量检测确认可在扫描设置中修改。')
        label.setWordWrap(True);left.addWidget(label)

    def selected(self):return [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count()) if self.files.item(i).checkState()==Qt.CheckState.Checked and not self.files.item(i).isHidden()]

    def settings_key(self):return ('ring_plot' if self.channel.currentData()=='ring' else 'plot') if self.kind=='curves' else self.kind

    def refresh(self):
        selected=set(self.selected());previous_group=self.group.currentText();self.loading=True
        epoch=self.w.state.workspace_epoch;reset=self.workspace_epoch!=epoch;self.workspace_epoch=epoch
        if reset and self.kind=='curves':self.channel.setCurrentIndex(max(self.channel.findData(self.w.state.settings.get('plot_channel','disk')),0))
        records=self.w.get_edit_configs();available={i for i,c in records.items() if c.get('role')!='背景' and (self.kind!='rrde' or len(self.w.state.traces[i].columns)>=3)}
        options=self.w.state.settings.get(self.settings_key(),{})
        if reset:
            selected=set(options.get('selected',options.get('selection_by_group',{}).get(options.get('group','全部'),available)))
            self.known_ids=set();self.efficiency_edits={};self.seed_inputs(options);previous_group=options.get('group','全部')
        elif not self.known_ids:selected=available
        else:selected|=available-self.known_ids
        self.known_ids=available
        groups=list(dict.fromkeys(records[i].get('group','未分组') for i in self.w.state.traces if i in available))
        group_options=groups if self.kind=='kl' else ['全部']+groups
        self.group.clear();self.group.addItems(group_options)
        if group_options:self.group.setCurrentText(previous_group if previous_group in group_options else group_options[0])
        self.files.clear()
        for ident in self.w.state.traces:
            if ident not in available:continue
            config=records[ident]
            item=QListWidgetItem(f"{config.get('name',self.w.state.traces[ident].name)} · {config.get('rpm') if config.get('rpm') is not None else '转速待填'} rpm")
            item.setData(Qt.ItemDataRole.UserRole,ident);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if ident in selected else Qt.CheckState.Unchecked);self.files.addItem(item)
            item.setHidden(self.group.currentText()!='全部' and config.get('group')!=self.group.currentText())
        if self.kind=='curves':self.color_file.clear();[self.color_file.addItem(records[i].get('name',i),i) for i in self.selected()]
        if self.kind=='rrde':self.seed_efficiency()
        if reset or (self.last_revision is not None and self.last_revision!=self.w.state.revision):self.clear_view()
        self.loading=False;self.update_buttons();self.refresh_exports()

    def seed_inputs(self,options):
        if self.kind=='kl':
            self.scheme.setCurrentIndex(max(self.scheme.findData(options.get('scheme','koh_25C')),0))
            for key,widget in self.constants.items():widget.setText('' if options.get(key,KOH_PRESET[key]) is None else str(options.get(key,KOH_PRESET[key])))
            self.source.setText(options.get('source',KOH_PRESET['source']));self.start.setText('' if options.get('start') is None else str(options['start']));self.end.setText('' if options.get('end') is None else str(options['end']));self.count.setValue(int(options.get('count',30)));self.confirmed.setChecked(False)
            self.previous_scheme=self.scheme.currentData();self.custom_constants={}
            if self.previous_scheme=='custom':self.custom_constants={key:widget.text() for key,widget in self.constants.items()};self.custom_constants['source']=self.source.text()
        elif self.kind=='curves':self.seed_curve_options(options)

    def seed_curve_options(self,options):
        is_ring=self.channel.currentData()=='ring';self.unit.clear()
        for text,value in ([('环电流 / μA','uA'),('环电流 / mA','mA')] if is_ring else [('电流 / mA','mA'),('电流密度 / mA·cm⁻²','mA/cm2')]):self.unit.addItem(text,value)
        unit=options.get('unit','uA') if is_ring else ('mA/cm2' if options.get('density') else 'mA')
        self.unit.setCurrentIndex(max(self.unit.findData(unit),0));self.background_view.setCurrentText(options.get('background_view','处理后'));self.background_view.setEnabled(is_ring)
        self.curve_form.setRowVisible(self.background_view,is_ring)
        smooth=smoothing_defaults(options.get('smoothing'));self.smooth.setChecked(bool(smooth['enabled']));self.strength.setCurrentText(smooth['preset']);self.window_points.setValue(int(smooth.get('custom_window',11)));self.unsmoothed.setChecked(bool(smooth['show_unsmoothed']))
        for key,widget in self.style_fields.items():
            default='RRDE ring current comparison' if is_ring else 'ORR polarization curves'
            value=options.get(key,default if key=='title' else {'width':8,'height':5,'line_width':1.8}.get(key));widget.setText('' if value is None else str(value))
        self.legend.setChecked(options.get('legend',True));self.window_points.setEnabled(self.strength.currentText()=='自定义')
        self.smooth_body.setVisible(self.smooth.isChecked());self.smooth_form.setRowVisible(self.window_points,self.strength.currentText()=='自定义')
        metrics=potential_options(options.get('potentials'))
        self.onset_threshold.setText(str(metrics['onset_threshold']));self.onset_unit.setCurrentIndex(self.onset_unit.findData(metrics['onset_unit']))
        self.plateau_mode.setCurrentIndex(self.plateau_mode.findData(metrics['plateau_mode']))
        for key,widget in (('plateau_start',self.plateau_start),('plateau_end',self.plateau_end),('baseline_mA',self.potential_baseline)):
            widget.setText('' if metrics[key] is None else str(metrics[key]))
        self.potential_markers.setChecked(metrics['show_markers']);self.update_potential_fields()

    def channel_changed(self,*_):
        if self.loading:return
        self.loading=True;self.seed_curve_options(self.w.state.settings.get(self.settings_key(),{}));self.loading=False
        self.clear_view();self.display_changed()

    def group_changed(self,*_):
        if self.loading:return
        records=self.w.get_edit_configs();group=self.group.currentText();self.loading=True
        for index in range(self.files.count()):
            item=self.files.item(index);hidden=group!='全部' and records[item.data(Qt.ItemDataRole.UserRole)].get('group')!=group
            item.setHidden(hidden)
            if hidden:item.setCheckState(Qt.CheckState.Unchecked)
        self.loading=False;self.selection_changed()

    def check_all(self,value):
        self.loading=True
        for index in range(self.files.count()):
            item=self.files.item(index)
            if not item.isHidden():item.setCheckState(Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)
        self.loading=False;self.selection_changed()

    def selection_changed(self,*_):
        if self.loading:return
        if self.kind=='curves':
            self.color_file.clear();records=self.w.get_edit_configs()
            for ident in self.selected():self.color_file.addItem(records[ident].get('name',ident),ident)
            self.display_changed()
        else:
            self.input_changed()
            if self.kind=='rrde':self.seed_efficiency()

    def input_changed(self,*_):
        if self.loading:return
        self.window.touch_ui()
        clear_result(self.w,self.kind);self.clear_view();self.note.setText('分析输入已修改，请重新计算。');self.refresh_exports()

    def scheme_changed(self,*_):
        if self.loading:return
        if self.previous_scheme=='custom':
            self.custom_constants={key:widget.text() for key,widget in self.constants.items()};self.custom_constants['source']=self.source.text()
        if self.scheme.currentData()=='koh_25C':
            for key,widget in self.constants.items():widget.setText(str(KOH_PRESET[key]))
            self.source.setText(KOH_PRESET['source'])
        else:
            for key,widget in self.constants.items():widget.setText(self.custom_constants.get(key,str(KOH_PRESET[key])))
            self.source.setText(self.custom_constants.get('source',''))
        self.previous_scheme=self.scheme.currentData();self.input_changed();self.update_buttons()

    def seed_efficiency(self):
        records=self.w.get_edit_configs();values={records[i].get('collection_efficiency') for i in self.selected()}
        value=next(iter(values)) if len(values)==1 else None
        text=self.efficiency_edits.get(tuple(sorted(self.selected())),'' if value is None else str(value))
        self.efficiency.setText(text);self.efficiency.setPlaceholderText('各文件不同／未知，保留各自值');self.efficiency.setModified(False)

    def stage_efficiency(self):
        if self.loading or not self.efficiency.isModified():return
        key=tuple(sorted(self.selected()));self.efficiency_edits[key]=self.efficiency.text()
        domain='rrde_efficiency:'+hashlib.sha256('|'.join(key).encode()).hexdigest()[:12]
        try:
            text=self.efficiency.text().strip();value=float(text) if text else None
            updates=condition_updates(self.w.get_draft_view(),self.selected(),{'collection_efficiency':value})
            if not key:raise DataError('请选择至少一个 RRDE 文件。')
            accepted=self.w.stage_config_updates(domain,updates)
            if not accepted:self.note.setText(self.w.state.get('draft_error','收集效率修改未接受。'))
            self.update_buttons();self.window.update_actions()
        except (ValueError,DataError) as exc:
            self.w.reject_config_updates(domain,None,str(exc));self.note.setText(str(exc))

    def curve_options(self):
        options=deepcopy(self.w.state.settings.get(self.settings_key(),{}));unit=self.unit.currentData()
        options.update(density=unit=='mA/cm2',unit=unit,background_view=self.background_view.currentText(),legend=self.legend.isChecked(),selected=self.selected(),group=self.group.currentText())
        for key,widget in self.style_fields.items():
            text=widget.text().strip();options[key]=text if key=='title' else float(text) if text else None
        strength=self.strength.currentText();custom=self.window_points.value()
        options['smoothing']=dict(smoothing_defaults(options.get('smoothing')),enabled=self.smooth.isChecked(),preset=strength,
            window_points=PRESET_WINDOWS.get(strength,custom),custom_window=custom,show_unsmoothed=self.unsmoothed.isChecked())
        if self.channel.currentData()=='disk':options['potentials']=self.potential_inputs()
        return options

    def potential_inputs(self):
        number=lambda widget:float(widget.text()) if widget.text().strip() else None
        manual=self.plateau_mode.currentData()=='manual'
        def bound(widget):
            if manual:return number(widget)
            try:
                value=number(widget);return value if value is None or math.isfinite(value) else None
            except ValueError:return None # Inactive raw manual input must not block automatic mode.
        return potential_options(dict(onset_threshold=number(self.onset_threshold),onset_unit=self.onset_unit.currentData(),
            plateau_mode=self.plateau_mode.currentData(),plateau_start=bound(self.plateau_start),plateau_end=bound(self.plateau_end),
            baseline_mA=number(self.potential_baseline),show_markers=self.potential_markers.isChecked()))

    def update_potential_fields(self):
        disk=self.channel.currentData()=='disk';self.potential_settings.setVisible(disk)
        manual=self.plateau_mode.currentData()=='manual'
        for widget in (self.plateau_start,self.plateau_end):self.potential_form.setRowVisible(widget,manual)

    def display_changed(self,*_):
        if self.loading:return
        self.window.touch_ui()
        channel=self.channel.currentData();self.w.clear_polarization_exports(channel);self.clear_view()
        try:
            self.update_potential_fields()
            self.window_points.setEnabled(self.strength.currentText()=='自定义')
            self.smooth_body.setVisible(self.smooth.isChecked());self.smooth_form.setRowVisible(self.window_points,self.strength.currentText()=='自定义')
            self.w.state.settings[self.settings_key()]=self.curve_options()
            self.w.state.settings['plot_channel']=self.channel.currentData()
            channel=self.channel.currentData();self.w.clear_polarization_exports(channel);self.clear_view()
            if self.window.jobs.busy:
                self.note.setText('设置已修改；当前后台结果将被核对，任务结束后请重新生成。');return
            if self.selected():
                result=calculate_curves(self.w,self.selected(),channel,commit=False);self.present_curve(result)
                self.note.setText('显示预览；保存绘图 CSV 会使用当前显示并重新校验。'+self.curve_notes(result))
        except (DataError,ValueError,TypeError) as exc:self.note.setText(str(exc))
        self.refresh_exports();self.update_buttons()

    def choose_color(self):
        ident=self.color_file.currentData()
        if not ident:return
        color=QColorDialog.getColor(parent=self)
        if color.isValid():self.w.state.settings.setdefault(self.settings_key(),{}).setdefault('colors',{})[ident]=color.name();self.display_changed()

    def use_coverage(self):
        configs,settings=self.w.pending_candidate();outputs,errors=self.w.process_selected(self.selected(),configs,settings,channels='disk')
        if errors or len(outputs)!=len(self.selected()) or not outputs:raise DataError('共同覆盖需要全部所选文件可处理。'+'；'.join(e['原因'] for e in errors))
        low=max(float(o['data'].E_V.min()) for o in outputs.values());high=min(float(o['data'].E_V.max()) for o in outputs.values())
        if low>=high:raise DataError('所选曲线没有共同覆盖。')
        self.start.setText(str(low));self.end.setText(str(high));self.coverage.setText(f'共同覆盖 {low:.5f} ～ {high:.5f} V；仍须核对 ORR 适用区间。');self.input_changed()
        return low,high

    def kl_inputs(self):
        def number(widget):
            text=widget.text().strip();return float(text) if text else None
        preset=self.scheme.currentData()=='koh_25C'
        return dict(**{key:KOH_PRESET[key] if preset else number(widget) for key,widget in self.constants.items()},
            start=number(self.start),end=number(self.end),count=self.count.value(),source=KOH_PRESET['source'] if preset else self.source.text(),
            selected=self.selected(),group=self.group.currentText(),confirmed=self.confirmed.isChecked(),scheme=self.scheme.currentData())

    def calculate(self):
        self.clear_view();self.note.setText('正在计算当前设置…')
        try:
            if self.kind=='curves':
                self.w.state.settings[self.settings_key()]=self.curve_options();result=calculate_curves(self.w,self.selected(),self.channel.currentData());self.present_curve(result)
                self.note.setText(f"已生成 {len(result['outputs'])} 条曲线。"+self.curve_notes(result))
            else:
                if self.kind=='kl':saved,figures=complete_kl(self.w,self.kl_inputs())
                else:saved,figures=complete_rrde(self.w,self.selected())
                self.saved=saved;self.install_figures(figures);table_from_rows(self.table,saved['data'].to_dict('records')+saved.get('errors',[]))
                self.note.setText(self.result_notes(saved));result=saved
                if self.kind=='kl':
                    self.loading=True;self.fit_potential.clear()
                    if not saved['points'].empty:
                        for value in sorted(saved['points'].E_V.unique()):self.fit_potential.addItem(f'{value:.5f} V',float(value))
                        index=self.fit_potential.findData(self.w.state.settings.get('kl_plot',{}).get('fit_potential'))
                        self.fit_potential.setCurrentIndex(index if index>=0 else self.fit_potential.count()//2)
                    self.loading=False
            self.last_revision=self.w.state.revision;self.window.refresh();return result
        except (DataError,ValueError,TypeError,IndexError) as exc:
            self.note.setText(str(exc));self.refresh_exports()
            if self.kind=='kl':
                try:
                    configs,settings=self.w.pending_candidate();outputs,errors=self.w.process_selected(self.selected(),configs,settings,channels='disk')
                    rows=kl_condition_differences(list(outputs.values()))+errors
                except (DataError,ValueError,TypeError):rows=self.w.get_draft_view()['errors']
                table_from_rows(self.table,rows)
                if rows:self.details.setChecked(True)
            raise

    def curve_notes(self,result):
        notes=[f"{e['文件']}：{e['原因']}" for e in result['errors']]
        for report in result['smoothing_report'].values():notes.extend(f"{report['filename']}：{note}" for note in report['notes'])
        audit=result.get('comparison_audit')
        if audit and audit['missing']:notes.append('部分比较条件未记录；只核对已知项。允许不同转速和环设定电位。')
        return '；'.join(notes)

    def result_notes(self,saved):
        if self.kind=='kl':
            invalid=int((~saved['data'].valid_two_path_model).sum());return f"{len(saved['data'])} 个电位，{invalid} 个模型检查异常；数值保留，不裁剪。"
        invalid=int((~saved['data'].valid_two_product_model).sum());unconfirmed=[o['name'] for o in saved['outputs'].values() if not o['config'].get('ring_detection_confirmed')]
        return f"{len(saved['data'])} 个点，{invalid} 个模型检查异常。"+('尚未确认环检测条件：'+'、'.join(unconfirmed)+'。' if unconfirmed else '')+'；'.join(f"{e['文件']}：{e['原因']}" for e in saved['errors'])

    def present_curve(self,result):
        self.last_revision=self.w.state.revision;self.install_figures({'ring_current' if self.channel.currentData()=='ring' else 'polarization':result['figure']})
        rows=[]
        for ident,o in result['outputs'].items():rows.append({'文件':o['name'],'扫描段':o['segment']['segment'],'方向':o['segment']['direction'],'处理记录':'；'.join(o['notes'])})
        rows.extend(result['errors']);table_from_rows(self.table,rows)
        if self.kind=='curves':
            metrics=result.get('potentials');self.potential_result.setVisible(metrics is not None)
            if metrics is not None:
                metric_rows=[]
                for row in metrics.to_dict('records'):
                    value=lambda key:round(float(row[key]),5) if row[key] is not None and math.isfinite(float(row[key])) else ''
                    metric_rows.append({'样品':row['sample'],'电位坐标':row['axis'],'E_onset / V':value('E_onset_V'),'E_1/2 / V':value('E_half_V'),
                        '起始说明':row['onset_reason'],'半波说明':row['half_reason']})
                table_from_rows(self.potential_table,metric_rows)

    def install_figures(self,figures):
        self._needs_blank=False
        self.figures=figures;self.figure_choice.blockSignals(True);self.figure_choice.clear()
        for name in figures:self.figure_choice.addItem(FIGURE_LABELS.get(name,name),name)
        self.figure_choice.blockSignals(False)
        if figures:self.show_figure(next(iter(figures)))

    def show_figure(self,name):
        if name in self.figures:
            figure=self.figures[name];self.canvas.figure=figure;figure.set_canvas(self.canvas);self.canvas.draw()

    def clear_view(self):
        self.saved=None;self.figures={};self.figure_choice.clear();self.table.setRowCount(0)
        if self.kind=='curves':self.potential_result.hide();self.potential_table.setRowCount(0)
        if getattr(self.window,'jobs',None) and self.window.jobs.busy:
            self._needs_blank=True;self.canvas.hide();return
        figure=new_figure();self.canvas.figure=figure;figure.set_canvas(self.canvas);self.canvas.draw()

    def change_fit(self,*_):
        if self.loading or not self.saved or self.kind!='kl' or self.fit_potential.currentData() is None:return
        figures=kl_figures(self.saved,self.fit_potential.currentData());self.figures['kl_fit']=figures['kl_fit'];publish_figures(self.w,{'kl_fit':figures['kl_fit']});self.figure_choice.setCurrentIndex(self.figure_choice.findData('kl_fit'));self.show_figure('kl_fit');self.refresh_exports()
        self.w.state.settings.setdefault('kl_plot',{})['fit_potential']=float(self.fit_potential.currentData());record_kl_parameters(self.w,self.saved)

    def update_buttons(self):
        label={'curves':'生成极化曲线','kl':'计算 K–L','rrde':'计算 RRDE'}[self.kind]
        self.calculate_button.setText(('应用并'+label if self.w.has_draft() else label))
        self.csv_button.setText('应用并导出绘图 CSV' if self.w.has_draft() else '保存绘图 CSV')
        busy=self.window.jobs.busy
        if self.kind=='curves':self.potential_csv.setEnabled(not busy)
        for button in (self.calculate_button,self.csv_button,self.png_button,self.extra_button):button.setEnabled(not busy)
        if self.kind=='kl':
            custom=self.scheme.currentData()=='custom'
            for widget in self.constants.values():widget.setEnabled(custom);self.kl_form.setRowVisible(widget,custom)
            self.source.setEnabled(custom);self.kl_form.setRowVisible(self.source,custom)

    def refresh_exports(self):
        current=self.extra.currentText();prefix=('ring_current' if self.channel.currentData()=='ring' else 'polarization') if self.kind=='curves' else self.kind+'_'
        names=[n for n in self.w.state.exports if n.startswith(prefix) or (self.kind=='curves' and n=='parameters.json')]
        self.extra.clear();self.extra.addItems(names);self.extra.setCurrentText(current if current in names else names[0] if names else '')

    def export_csv(self,path=None):
        self.calculate();name=('ring_current_plot.csv' if self.channel.currentData()=='ring' else 'polarization_plot.csv') if self.kind=='curves' else self.kind+'_plot.csv'
        return self.window.export_file(name,path)

    def export_png(self,path=None):
        if not self.figures or self.w.has_draft():self.calculate()
        name=str(self.figure_choice.currentData())+'.png'
        if name not in self.w.state.exports:self.calculate();name=str(self.figure_choice.currentData())+'.png'
        return self.window.export_file(name,path)

    def export_extra(self,path=None):
        if self.w.has_draft():self.calculate()
        return self.window.export_file(self.extra.currentText(),path)

    def open_conditions(self):
        self.window.tabs.setCurrentIndex(0)
        pane=self.window.settings_pane;pane.show_details(0);pane.scope.setCurrentText('表格选中');pane.table.clearSelection()
        for ident in self.selected():
            if ident in pane.model.ids:pane.table.selectionModel().select(pane.model.index(pane.model.ids.index(ident),0),QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
        if self.selected():self.window.source.setCurrentIndex(self.window.source.findData(self.selected()[0]))
        pane.update_targets()

    def task_inputs(self):
        if self.kind=='curves':return json_bytes({'selected':self.selected(),'channel':self.channel.currentData(),'options':self.curve_options()})
        if self.kind=='rrde':return json_bytes({'selected':self.selected(),'efficiency_text':self.efficiency.text()})
        return json_bytes(dict(selected=self.selected(),scheme=self.scheme.currentData(),constants={k:w.text() for k,w in self.constants.items()},
            source=self.source.text(),start=self.start.text(),end=self.end.text(),count=self.count.value(),confirmed=self.confirmed.isChecked()))

    def request_calculate(self,*,target=None,asset=None):
        self.window.ensure_idle()
        if self.kind=='curves':self.w.clear_polarization_exports(self.channel.currentData())
        else:clear_result(self.w,self.kind)
        self.clear_view()
        if self.kind=='curves':payload=dict(selected=self.selected(),channel=self.channel.currentData(),plot_key=self.settings_key(),options=self.curve_options())
        elif self.kind=='kl':payload={'inputs':self.kl_inputs()}
        else:payload={'selected':self.selected()}
        if target:payload.update(target=str(target),asset=asset)
        token=self.task_inputs();self.note.setText('正在准备后台计算…')
        return self.window.start_task(self.kind,payload,pane=self,input_token=token,current_inputs=self.task_inputs)

    def request_export(self,name,*,recompute=False,path=None):
        from PySide6.QtWidgets import QFileDialog
        self.window.ensure_idle()
        if not name:raise DataError('请先生成相应结果。')
        if path is None:path,_=QFileDialog.getSaveFileName(self,'保存分析结果',name)
        if not path:return
        if recompute or self.w.has_draft() or name not in self.w.state.exports:return self.request_calculate(target=path,asset=name)
        return self.window.start_task('asset',{'asset':name,'target':str(path)},pane=self,input_token=self.task_inputs(),current_inputs=self.task_inputs)

    def request_csv(self,path=None):
        name=('ring_current_plot.csv' if self.channel.currentData()=='ring' else 'polarization_plot.csv') if self.kind=='curves' else self.kind+'_plot.csv'
        return self.request_export(name,recompute=True,path=path)

    def request_png(self,path=None):
        name=self.figure_choice.currentData()
        if not name:name=('ring_current' if self.channel.currentData()=='ring' else 'polarization') if self.kind=='curves' else 'kl_electron_number' if self.kind=='kl' else 'rrde_selectivity'
        return self.request_export(name+'.png',path=path)

    def request_extra(self,path=None):return self.request_export(self.extra.currentText(),path=path)

    def request_fit(self,*_):
        if self.loading or not self.saved or self.kind!='kl' or self.fit_potential.currentData() is None:return
        if self.window.jobs.busy:self.window.touch_ui();return
        potential=float(self.fit_potential.currentData())
        return self.window.start_task('fit',{'potential':potential},pane=self,input_token=potential,current_inputs=lambda:float(self.fit_potential.currentData()))

    def request_coverage(self):
        self.window.ensure_idle();self.input_changed()
        return self.window.start_task('coverage',{'selected':self.selected()},pane=self,input_token=self.task_inputs(),current_inputs=self.task_inputs)

    def accept_delivery(self,delivery):
        result=delivery['result'];operation=delivery['operation'];figures=delivery['figures']
        self.last_revision=self.w.state.revision
        if operation=='coverage':
            self.start.setText(str(result['start']));self.end.setText(str(result['end']))
            self.coverage.setText(f"共同覆盖 {result['start']:.5f} ～ {result['end']:.5f} V；仍须核对 ORR 适用区间。")
            self.note.setText('共同覆盖已更新，未进行科学拟合。')
        elif operation=='curves':
            result=dict(result,figure=next(iter(figures.values())));self.present_curve(result)
            self.note.setText(f"已生成 {len(result['outputs'])} 条曲线。"+self.curve_notes(result))
        elif operation=='fit':
            self.figures.update(figures);self.show_figure('kl_fit');self.note.setText('拟合图与参数已更新。')
        else:
            self.saved=result;self.install_figures(figures);table_from_rows(self.table,result['data'].to_dict('records')+result.get('errors',[]));self.note.setText(self.result_notes(result))
            if operation=='kl':
                self.loading=True;self.fit_potential.clear()
                if not result['points'].empty:
                    for potential in sorted(result['points'].E_V.unique()):self.fit_potential.addItem(f'{potential:.5f} V',float(potential))
                    self.fit_potential.setCurrentIndex(max(self.fit_potential.findData(self.w.state.settings.get('kl_plot',{}).get('fit_potential')),0))
                self.loading=False

    def finish_graph_state(self):
        if self._needs_blank:
            self._needs_blank=False;figure=new_figure();self.canvas.figure=figure;figure.set_canvas(self.canvas);self.canvas.draw()
        self.canvas.show()
