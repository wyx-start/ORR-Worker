"""Native minimum closed loop. All scientific writes go through Workspace."""
from pathlib import Path
from copy import deepcopy
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTabWidget, QPushButton, QLabel, QComboBox, QLineEdit, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QSplitter, QHeaderView)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

from application.workspace import Workspace
from application.figures import new_figure
from application.curves import calculate_curves
from orr_core import DataError, scan_segments
from desktop.fonts import ui_font


class MainWindow(QMainWindow):
    def __init__(self, workspace=None):
        super().__init__()
        self.setFont(ui_font())
        self.workspace = workspace or Workspace()
        self.loading = False
        self.force_close = False
        self.setWindowTitle("ORR Worker · 桌面版预览")
        self.resize(1220, 850)
        self.setAcceptDrops(True)
        self.tabs = QTabWidget();self.setCentralWidget(self.tabs)
        page=QWidget();layout=QVBoxLayout(page)
        actions=QHBoxLayout()
        for text, callback in (("导入文件",self.choose_files),("打开项目",self.open_project),
                               ("保存分析项目",self.save_project)):
            button=QPushButton(text);button.clicked.connect(lambda checked=False,f=callback:self.guard(f));actions.addWidget(button)
        actions.addStretch();layout.addLayout(actions)
        self.table=QTableWidget(0,5)
        self.table.setHorizontalHeaderLabels(["文件","样品","用途","转速 / rpm","数据点"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table,1)
        self.source=QComboBox();self.source.currentIndexChanged.connect(self.load_conditions)
        form=QFormLayout();form.addRow("要修改的文件",self.source)
        self.fields={}
        for field,label in (("pH","pH *"),("temperature_C","温度 / °C *"),("reference","参比电极 *"),
                            ("filling","参比内充液"),("ref_V_SHE","E_ref vs SHE / V *")):
            widget=QLineEdit();widget.editingFinished.connect(lambda f=field:self.stage_field(f));self.fields[field]=widget
            form.addRow(label,widget)
        self.direction=QComboBox();self.direction.addItems(["递减","递增"])
        self.direction.currentTextChanged.connect(lambda value:self.stage_patch({"direction":value}))
        self.mode=QComboBox();self.mode.addItems(["A","B"])
        self.mode.currentTextChanged.connect(lambda value:self.stage_patch({"mode":value,"manual_segment":None}))
        self.segment=QComboBox();self.segment.currentIndexChanged.connect(self.stage_segment)
        form.addRow("扫描方向",self.direction);form.addRow("自动规则",self.mode);form.addRow("扫描段",self.segment)
        layout.addLayout(form)
        row=QHBoxLayout()
        self.apply_button=QPushButton("应用设置");self.apply_button.clicked.connect(lambda:self.guard(self.apply))
        row.addWidget(self.apply_button)
        discard=QPushButton("放弃未应用修改");discard.clicked.connect(lambda:self.guard(self.discard));row.addWidget(discard)
        row.addStretch();layout.addLayout(row)
        self.status=QLabel("拖入 TXT / CSV / DAT，或打开分析项目。默认 pH 13、SCE、5 mm RDE；* 为所需条件。")
        self.status.setWordWrap(True);layout.addWidget(self.status)
        self.tabs.addTab(page,"导入与设置")
        curve=QWidget();cl=QVBoxLayout(curve);row=QHBoxLayout()
        self.calculate_button=QPushButton("生成极化曲线")
        self.calculate_button.clicked.connect(lambda:self.guard(self.calculate));row.addWidget(self.calculate_button)
        for text,name in (("保存绘图 CSV","polarization_plot.csv"),("保存 PNG","polarization.png"),("保存 SVG","polarization.svg")):
            button=QPushButton(text);button.clicked.connect(lambda checked=False,n=name:self.guard(lambda:self.export_file(n)));row.addWidget(button)
        row.addStretch();cl.addLayout(row)
        self.canvas=FigureCanvasQTAgg(new_figure());self.toolbar=NavigationToolbar2QT(self.canvas,self)
        cl.addWidget(self.toolbar);cl.addWidget(self.canvas,1)
        self.tabs.addTab(curve,"极化曲线")
        for title in ("多转速 K–L","RRDE 选择性"):
            index=self.tabs.addTab(QWidget(),title+"（迁移中）");self.tabs.setTabEnabled(index,False)
        export=QWidget();el=QVBoxLayout(export)
        self.exports=QComboBox();el.addWidget(QLabel("当前修订生成的文件；保存分析项目仍为独立入口。"));el.addWidget(self.exports)
        save=QPushButton("保存所选结果");save.clicked.connect(lambda:self.guard(lambda:self.export_file(self.exports.currentText())));el.addWidget(save);el.addStretch()
        self.tabs.addTab(export,"导出与项目")
        self.refresh()

    def guard(self, operation):
        try:return operation()
        except (DataError,ValueError,TypeError,OSError,IndexError) as exc:
            self.status.setText(str(exc));QMessageBox.warning(self,"请核对设置",str(exc))

    def choose_files(self):
        names,_=QFileDialog.getOpenFileNames(self,"导入实验文件","","实验文本 (*.txt *.csv *.dat)")
        if names:self.import_paths(names)

    def import_paths(self, names):
        files=[];errors=[]
        for name in names:
            path=Path(name)
            try:files.append((path.name,path.read_bytes()))
            except OSError as exc:errors.append({"文件":path.name,"原因":str(exc)})
        count=self.workspace.add_files(files)
        self.workspace.state.import_errors.extend(errors)
        self.refresh()
        self.status.setText(f"新增 {count} 个文件。"+"；".join(f"{e['文件']}：{e['原因']}" for e in self.workspace.state.import_errors))
        return count

    def refresh(self):
        self.loading=True
        current=self.source.currentData();self.source.clear()
        state=self.workspace.state;records=self.workspace.get_edit_configs("conditions")
        self.table.setRowCount(len(state.traces))
        for row,(ident,trace) in enumerate(state.traces.items()):
            config=records[ident];self.source.addItem(trace.name,ident)
            for col,value in enumerate((trace.name,config.get("name"),config.get("role"),config.get("rpm"),len(trace.values))):
                self.table.setItem(row,col,QTableWidgetItem("" if value is None else str(value)))
        index=self.source.findData(current);self.source.setCurrentIndex(max(index,0))
        self.exports.clear();self.exports.addItems(list(state.exports))
        self.loading=False;self.load_conditions()
        self.calculate_button.setText("应用并生成极化曲线" if self.workspace.has_draft() else "生成极化曲线")

    def load_conditions(self, *_):
        if self.loading:return
        ident=self.source.currentData()
        self.loading=True
        self.segment.clear();self.segment.addItem("自动选择最后完整支线",None)
        if ident:
            cfg=self.workspace.get_edit_configs("conditions")[ident]
            for field,widget in self.fields.items():widget.setText("" if cfg.get(field) is None else str(cfg[field]))
            self.direction.setCurrentText(cfg.get("direction","递减"));self.mode.setCurrentText(cfg.get("mode","A"))
            try:
                for s in scan_segments(self.workspace.state.traces[ident]):
                    self.segment.addItem(f"第 {s['segment']} 段 · {s['direction']} · {'完整' if s['complete'] else '不完整'} · {s['points']} 点",s["segment"])
                index=self.segment.findData(cfg.get("manual_segment"));self.segment.setCurrentIndex(max(index,0))
            except DataError as exc:self.status.setText(str(exc))
        self.loading=False

    def stage_field(self, field):
        if self.loading:return
        value=self.fields[field].text().strip()
        try:
            if field in ("pH","temperature_C","ref_V_SHE"):value=float(value) if value else None
            patch={field:value}
            if field in ("reference","filling","ref_V_SHE"):patch.update(reference_preset_C=None,reference_source="用户输入")
            self.stage_patch(patch)
        except ValueError:self.status.setText("请输入数值，或留空表示未知。")

    def stage_patch(self, patch):
        if self.loading or not self.source.currentData():return
        ident=self.source.currentData();records=self.workspace.get_edit_configs("conditions")
        if all(records[ident].get(k)==v for k,v in patch.items()):return
        fields={key:"用户输入（桌面端）" for key in patch if key in self.fields}
        if fields:patch=dict(patch,parameter_sources=fields)
        self.workspace.stage_config_updates("conditions",{ident:patch})
        self.status.setText(self.workspace.state.get("draft_error") or "有未应用修改。")
        self.calculate_button.setText("应用并生成极化曲线")

    def stage_segment(self, *_):
        if self.loading:return
        value=self.segment.currentData();patch={"manual_segment":value}
        if value:
            selected=next(s for s in scan_segments(self.workspace.state.traces[self.source.currentData()]) if s['segment']==value)
            patch['direction']=selected['direction']
        self.stage_patch(patch)

    def apply(self):
        self.workspace.apply_pending_settings();self.refresh();self.status.setText("设置已应用；请重新生成曲线。")

    def discard(self):
        self.workspace.reset_draft();self.refresh();self.status.setText("已放弃未应用修改。")

    def calculate(self):
        selected=[i for i,c in self.workspace.get_draft_view()['records'].items() if c.get('role')!='背景']
        result=calculate_curves(self.workspace,selected)
        self.canvas.figure=result['figure'];result['figure'].set_canvas(self.canvas);self.canvas.draw()
        self.refresh();self.tabs.setCurrentIndex(1)
        self.status.setText(f"已生成 {len(result['outputs'])} 条曲线。"+"；".join(e['原因'] for e in result['errors']))
        return result

    def export_file(self, name, path=None):
        if self.workspace.has_draft():raise DataError("请先应用并生成当前结果，再保存。")
        if name not in self.workspace.state.exports:raise DataError("请先生成相应结果。")
        if path is None:path,_=QFileDialog.getSaveFileName(self,"保存结果",name)
        if path:Path(path).write_bytes(self.workspace.state.exports[name]['bytes'])

    def save_project(self, path=None):
        if path is None:path,_=QFileDialog.getSaveFileName(self,"保存分析项目","ORR_Worker_analysis.orrproj","分析项目 (*.orrproj)")
        if path:
            Path(path).write_bytes(self.workspace.project_bytes());self.refresh();self.status.setText("项目已保存。")

    def open_project(self, path=None):
        if path is None:path,_=QFileDialog.getOpenFileName(self,"打开分析项目","","分析项目 (*.orrproj)")
        if path:
            self.workspace.restore_project(Path(path).read_bytes());self.refresh();self.status.setText("项目已恢复；重新生成分析结果。")

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()

    def dropEvent(self,event):
        self.guard(lambda:self.import_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]))

    def closeEvent(self,event):
        if not self.force_close and self.workspace.has_draft():
            answer=QMessageBox.question(self,"未应用修改","放弃未应用修改并退出？")
            if answer!=QMessageBox.StandardButton.Yes:event.ignore();return
        event.accept()
