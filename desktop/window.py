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
        from desktop.settings import SettingsPane
        self.settings_pane=SettingsPane(self)
        self.source=self.settings_pane.source;self.fields=self.settings_pane.fields
        self.segment=self.settings_pane.segment;self.mode=self.settings_pane.mode
        self.direction=self.settings_pane.direction;self.table=self.settings_pane.table
        self.status=self.settings_pane.status;self.apply_button=self.settings_pane.apply_button
        self.tabs.addTab(self.settings_pane,"导入与设置")
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
        self.settings_pane.refresh()
        self.exports.clear();self.exports.addItems(list(self.workspace.state.exports))
        self.calculate_button.setText("应用并生成极化曲线" if self.workspace.has_draft() else "生成极化曲线")

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
