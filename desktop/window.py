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
from desktop.lifecycle import DesktopLifecycle
from desktop.jobs import JobController
from application.tasks import atomic_write


class MainWindow(DesktopLifecycle,QMainWindow):
    def __init__(self, workspace=None):
        super().__init__()
        self.setFont(ui_font())
        self.workspace = workspace or Workspace()
        self._ui_epoch=0
        self.jobs=JobController(self.workspace,lambda:self._ui_epoch,self)
        self.loading = False
        self.force_close = False
        self.setWindowTitle("ORR Worker · 桌面版预览")
        self.resize(1220, 850)
        self.setAcceptDrops(True)
        self.tabs = QTabWidget();self.setCentralWidget(self.tabs)
        from desktop.settings import SettingsPane
        self.settings_pane=SettingsPane(self)
        self.source=self.settings_pane.source;self.fields=self.settings_pane.fields
        self.segment=self.settings_pane.segment;self.mode=self.settings_pane.mode
        self.direction=self.settings_pane.direction;self.table=self.settings_pane.table
        self.status=self.settings_pane.status;self.apply_button=self.settings_pane.apply_button
        self.tabs.addTab(self.settings_pane,"导入与设置")
        from desktop.analysis import AnalysisPane
        self.analyses={}
        for kind,title in (("curves","极化曲线"),("kl","多转速 K–L"),("rrde","RRDE 选择性")):
            pane=AnalysisPane(self,kind);self.analyses[kind]=pane;self.tabs.addTab(pane,title)
        self.calculate_button=self.analyses['curves'].calculate_button
        self.canvas=self.analyses['curves'].canvas
        export=QWidget();el=QVBoxLayout(export)
        el.addWidget(QLabel("绘图 CSV 在对应分析页优先导出；完整数据、参数和项目可分别保存。"))
        self.export_buttons={}
        for key,text,operation in (("data","导出全部完整数据 CSV",self.choose_data_export),("parameters","导出当前配置参数 JSON",self.choose_parameters_export),("project","保存分析项目",self.choose_save_project),("zip","保存当前全部结果 ZIP",self.choose_zip_export)):
            button=QPushButton(text);button.clicked.connect(lambda checked=False,f=operation:self.guard(f));el.addWidget(button);self.export_buttons[key]=button
        self.exports=QComboBox();el.addWidget(self.exports)
        save=QPushButton("保存所选结果文件");save.clicked.connect(lambda:self.guard(self.choose_asset_export));el.addWidget(save);self.asset_export_button=save
        self.export_note=QLabel();self.export_note.setWordWrap(True);el.addWidget(self.export_note);el.addStretch()
        self.tabs.addTab(export,"导出与项目")
        self.tabs.currentChanged.connect(lambda:self.update_actions())
        self.setup_lifecycle()
        self.refresh()

    def guard(self, operation):
        try:return operation()
        except (DataError,ValueError,TypeError,OSError,IndexError,RuntimeError) as exc:
            self.status.setText(str(exc));QMessageBox.warning(self,"请核对设置",str(exc))

    def choose_files(self):
        self.ensure_idle()
        names,_=QFileDialog.getOpenFileNames(self,"导入实验文件","","实验文本 (*.txt *.csv *.dat)")
        if names:self.request_import(names)

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
        self.settings_pane.refresh()
        for pane in self.analyses.values():pane.refresh()
        self.exports.clear();self.exports.addItems(list(self.workspace.state.exports))
        self.update_actions()

    def update_actions(self):
        for pane in self.analyses.values():pane.update_buttons()
        dirty=self.workspace.has_draft()
        self.settings_pane.project_button.setText('应用并保存分析项目' if dirty else '保存分析项目')
        for key,normal,pending in (('data','导出全部完整数据 CSV','应用并导出全部完整数据 CSV'),('parameters','导出当前配置参数 JSON','应用并导出当前配置参数 JSON'),('project','保存分析项目','应用并保存分析项目')):
            self.export_buttons[key].setText(pending if dirty else normal)
        self.export_buttons['zip'].setEnabled(not dirty)
        busy=self.jobs.busy
        for button in self.export_buttons.values():button.setEnabled(not busy)
        self.export_buttons['zip'].setEnabled(not dirty and not busy)
        self.asset_export_button.setEnabled(not dirty and not busy)
        self.settings_pane.project_button.setEnabled(not busy)
        if hasattr(self,'project_state_label'):self.update_project_state()
        if dirty:self.export_note.setText('有未应用修改。完整数据、配置参数与项目可合并应用；分析结果请在对应页重新计算后导出。')

    def export_complete_data(self,path=None):
        from application.results import complete_data
        outputs,errors=complete_data(self.workspace);self.refresh()
        self.export_note.setText(f"已处理 {len(outputs)} 个文件；"+'；'.join(f"{e['文件']}：{e['原因']}" for e in errors))
        return self.export_file('all_curves.csv',path)

    def export_parameters(self,path=None):
        from orr_core import json_bytes
        self.workspace.apply_pending_settings()
        self.workspace.set_export('configuration_parameters.json',json_bytes(self.workspace.parameters()),'application/json')
        self.refresh();return self.export_file('configuration_parameters.json',path)

    def export_zip(self,path=None):
        from application.data import zip_exports
        if self.workspace.has_draft():raise DataError("请先在相应分析页应用并重新计算，再保存结果包。")
        if not self.workspace.state.exports:raise DataError("请先生成分析结果。")
        if path is None:path,_=QFileDialog.getSaveFileName(self,"保存全部结果","ORR_Worker_results.zip","结果包 (*.zip)")
        if path:atomic_write(path,zip_exports(self.workspace.state.exports))

    def load_conditions(self, *_):
        return self.settings_pane.load()

    def stage_field(self, field):
        return self.settings_pane.stage_field(field)

    def stage_patch(self, patch):
        return self.settings_pane.stage_patch(patch)

    def stage_segment(self, *_):
        return self.settings_pane.stage_segment()

    def apply(self):
        self.workspace.apply_pending_settings();self.refresh();self.status.setText("设置已应用；请重新生成曲线。")

    def discard(self):
        self.workspace.reset_draft();self.refresh();self.status.setText("已放弃未应用修改。")

    def calculate(self):
        result=self.analyses['curves'].calculate();self.tabs.setCurrentIndex(1);return result

    def export_file(self, name, path=None):
        if self.workspace.has_draft():raise DataError("请先应用并生成当前结果，再保存。")
        if name not in self.workspace.state.exports:raise DataError("请先生成相应结果。")
        if path is None:path,_=QFileDialog.getSaveFileName(self,"保存结果",name)
        if path:atomic_write(path,self.workspace.state.exports[name]['bytes'])

    def save_project(self, path=None):
        if path is None:path,_=QFileDialog.getSaveFileName(self,"保存分析项目","ORR_Worker_analysis.orrproj","分析项目 (*.orrproj)")
        if path:
            from application.tasks import snapshot,execute
            result=execute(snapshot(self.workspace,'project',{'target':str(path),'inputs':self.collect_project_inputs()}))
            result['prepared'].publish();self.workspace.state.clear();self.workspace.state.update(result['state'])
            self.mark_project_saved(path);self.refresh();self.status.setText("项目已保存。")

    def open_project(self, path=None):
        if path is None:path,_=QFileDialog.getOpenFileName(self,"打开分析项目","","分析项目 (*.orrproj)")
        if path:
            self.workspace.restore_project(Path(path).read_bytes());self.mark_project_saved(path);self.refresh();self.status.setText("项目已恢复；重新生成分析结果。")

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()

    def dropEvent(self,event):
        paths=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if len(paths)==1 and Path(paths[0]).suffix.lower()=='.orrproj':self.guard(lambda:self.request_load(paths[0]))
        elif any(Path(path).suffix.lower()=='.orrproj' for path in paths):self.status.setText('项目文件请单独拖入；实验文件可以批量拖入。')
        else:self.guard(lambda:self.request_import(paths))

    def closeEvent(self,event):
        return self.native_close_event(event)
