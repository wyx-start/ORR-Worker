"""Native task routing, project cleanliness and close/save policy."""
from pathlib import Path
import math
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QFileDialog,QLabel,QProgressBar,QPushButton,QLineEdit,QComboBox,QMessageBox
from application.tasks import project_fingerprint,atomic_write
from application.workspace import Workspace
from orr_core import DataError


class DesktopLifecycle:
    def setup_lifecycle(self):
        self._saved_fingerprint=project_fingerprint(Workspace());self._saved_ui_epoch=self._ui_epoch
        self.project_path=None;self._after_success=None;self._close_when_idle=False;self._last_job_state=None;self._active_pane=None
        self.project_state_label=QLabel();self.progress_bar=QProgressBar();self.progress_bar.setRange(0,100);self.progress_bar.setMaximumWidth(170)
        self.cancel_button=QPushButton('取消任务');self.cancel_button.clicked.connect(self.jobs.cancel)
        self.statusBar().addPermanentWidget(self.project_state_label);self.statusBar().addPermanentWidget(self.progress_bar);self.statusBar().addPermanentWidget(self.cancel_button)
        self.progress_bar.hide();self.cancel_button.hide()
        self.jobs.progress.connect(self.task_progress);self.jobs.activeChanged.connect(self.task_active)
        self.jobs.accepted.connect(self.task_accepted);self.jobs.failed.connect(self.task_failed);self.jobs.discarded.connect(self.task_discarded);self.jobs.idle.connect(self.task_idle)
        app=QApplication.instance();app.focusChanged.connect(self.watch_editor_focus)
        for widget in self.findChildren(QLineEdit):self.watch_editor_focus(None,widget)

    def watch_editor_focus(self,old,widget):
        if isinstance(widget,QLineEdit) and self.isAncestorOf(widget) and not widget.property('orr_native_watched'):
            widget.setProperty('orr_native_watched',True);widget.textEdited.connect(self.touch_ui)
        if isinstance(widget,QComboBox) and self.settings_pane.table.isAncestorOf(widget) and not widget.property('orr_native_watched'):
            widget.setProperty('orr_native_watched',True);widget.activated.connect(self.touch_ui)

    def touch_ui(self,*_):
        self._ui_epoch+=1
        if hasattr(self,'project_state_label'):self.update_project_state()

    def has_unsaved_work(self):
        return self.workspace.has_draft() or project_fingerprint(self.workspace)!=self._saved_fingerprint or self._ui_epoch!=self._saved_ui_epoch

    def mark_project_saved(self,path):
        self.project_path=str(path);self._saved_fingerprint=project_fingerprint(self.workspace);self._saved_ui_epoch=self._ui_epoch
        for widget in self.findChildren(QLineEdit):widget.setModified(False)
        self.update_project_state()

    def update_project_state(self):
        dirty=self.has_unsaved_work();draft=self.workspace.has_draft()
        self.project_state_label.setText('未应用草稿 · 项目未保存' if draft else '项目未保存' if dirty else '项目已保存')
        self.setWindowTitle('ORR Worker · 桌面版预览'+(' *' if dirty else ''))

    def ensure_idle(self):
        if self.jobs.busy:raise DataError('已有任务正在执行，请等待或取消。')

    def start_task(self,operation,payload,*,pane=None,after=None,input_token=None,current_inputs=None):
        self.ensure_idle();self._active_pane=pane;self._after_success=after;self._last_job_state=None
        return self.jobs.start(operation,payload,input_token=input_token,current_inputs=current_inputs)

    def task_progress(self,percent,message):
        self.progress_bar.setValue(percent);self.statusBar().showMessage(message)
        if self._active_pane:self._active_pane.note.setText(message)

    def task_active(self,busy):
        self.progress_bar.setVisible(busy);self.cancel_button.setVisible(busy)
        self.settings_pane.scan_canvas.setVisible(not busy)
        for pane in self.analyses.values():
            pane.canvas.setVisible(not busy)
            for toolbar in pane.findChildren(__import__('matplotlib.backends.backend_qtagg',fromlist=['NavigationToolbar2QT']).NavigationToolbar2QT):toolbar.setVisible(not busy)
            if not busy:pane.finish_graph_state()
        if not busy:self.settings_pane.refresh_scan()
        self.update_actions()

    def task_accepted(self,delivery):
        self._last_job_state='accepted';operation=delivery['operation'];payload=delivery['payload'];pane=self._active_pane
        if pane and operation in ('curves','kl','rrde','fit','coverage'):pane.accept_delivery(delivery)
        if operation=='import':
            self.status.setText(f"新增 {delivery['result']['added']} 个文件。"+'；'.join(f"{e['文件']}：{e['原因']}" for e in self.workspace.state.import_errors))
        if operation in ('project','load'):self.mark_project_saved(payload.get('target') or payload.get('path'))
        self.refresh()
        if operation in ('import','load'):
            coverage=delivery['result'].get('coverage');kl=self.analyses['kl']
            if coverage and not kl.start.text().strip() and not kl.end.text().strip() and kl.group.currentText()==coverage['group']:
                kl.start.setText(str(coverage['start']));kl.end.setText(str(coverage['end']));kl.coverage.setText(f"共同覆盖 {coverage['start']:.5f} ～ {coverage['end']:.5f} V；仍须核对 ORR 区间。")
            elif delivery['result'].get('coverage_error'):kl.coverage.setText(delivery['result']['coverage_error'])
        if operation=='data':
            outputs,errors=delivery['result'];self.export_note.setText(f'已处理 {len(outputs)} 个文件。'+'；'.join(e['文件']+'：'+e['原因'] for e in errors))
        if delivery.get('prepared'):self.statusBar().showMessage('已保存：'+str(delivery['prepared'].target))
        elif operation=='load':self.statusBar().showMessage('项目已恢复；结果需重新计算。')
        else:self.statusBar().showMessage('任务完成。')

    def task_failed(self,message):
        self._last_job_state='failed';self._after_success=None;self._close_when_idle=False
        self.status.setText('任务失败：'+message);self.statusBar().showMessage('任务失败：'+message)
        if self._active_pane:self._active_pane.note.setText('任务失败：'+message)

    def task_discarded(self,message):
        self._last_job_state='discarded';self._after_success=None
        self.status.setText(message);self.statusBar().showMessage(message)
        if self._active_pane:self._active_pane.note.setText(message)

    def task_idle(self):
        self.update_project_state()
        callback=self._after_success if self._last_job_state=='accepted' else None;self._after_success=None
        self._active_pane=None
        if callback:QTimer.singleShot(0,lambda:self.guard(callback))
        elif self._close_when_idle:self._close_when_idle=False;QTimer.singleShot(0,self.close)

    def collect_project_inputs(self):
        """Use existing numeric task fields; invalid raw text blocks saving."""
        kl=self.analyses['kl'];values=kl.kl_inputs();values.pop('confirmed',None)
        for key in ('C','D','nu','start','end'):
            value=values.get(key)
            if value is not None and not math.isfinite(value):raise DataError('K–L '+key+' 应为有限数值，或留空。')
        return {'kl':values,'rrde':{'selected':self.analyses['rrde'].selected()}}

    def choose_save_project(self,*,after=None):
        self.ensure_idle();path,_=QFileDialog.getSaveFileName(self,'保存分析项目',self.project_path or 'ORR_Worker_analysis.orrproj','分析项目 (*.orrproj)')
        if path:
            inputs=self.collect_project_inputs();return self.start_task('project',{'target':path,'inputs':inputs},after=after)

    def choose_project(self):
        self.ensure_idle();path,_=QFileDialog.getOpenFileName(self,'打开分析项目','','分析项目 (*.orrproj)')
        if path:return self.request_load(path)

    def request_load(self,path,*,discard=False):
        self.ensure_idle()
        if self.has_unsaved_work() and not discard:
            answer=QMessageBox.question(self,'替换当前工作区','当前工作尚未保存。先保存分析项目？',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
            if answer==QMessageBox.StandardButton.Cancel:return
            if answer==QMessageBox.StandardButton.Save:return self.choose_save_project(after=lambda:self.request_load(path,discard=True))
        return self.start_task('load',{'path':str(path)})

    def request_import(self,paths):
        self.ensure_idle()
        if self.workspace.has_draft():raise DataError('请先应用或放弃草稿，再导入文件。')
        return self.start_task('import',{'paths':[str(path) for path in paths]})

    def choose_data_export(self):
        self.ensure_idle();path,_=QFileDialog.getSaveFileName(self,'保存全部完整数据','all_curves.csv','CSV (*.csv)')
        if path:return self.start_task('data',{'asset':'all_curves.csv','target':path})

    def choose_parameters_export(self):
        self.ensure_idle();path,_=QFileDialog.getSaveFileName(self,'保存当前配置参数','configuration_parameters.json','JSON (*.json)')
        if path:return self.start_task('parameters',{'target':path})

    def choose_zip_export(self):
        self.ensure_idle()
        if self.workspace.has_draft():raise DataError('请先在分析页应用并重新计算，再保存结果包。')
        path,_=QFileDialog.getSaveFileName(self,'保存当前结果包','ORR_Worker_results.zip','ZIP (*.zip)')
        if path:return self.start_task('zip',{'target':path})

    def choose_asset_export(self):
        self.ensure_idle();name=self.exports.currentText()
        if not name or name not in self.workspace.state.exports:raise DataError('请先生成相应结果。')
        if self.workspace.has_draft():raise DataError('请先应用并重新计算，再保存结果。')
        path,_=QFileDialog.getSaveFileName(self,'保存所选结果',name)
        if path:return self.start_task('asset',{'asset':name,'target':path})

    def native_close_event(self,event):
        if self.jobs.busy:
            if self.force_close:self._close_when_idle=True;self.jobs.cancel()
            else:
                answer=QMessageBox.question(self,'任务仍在执行','取消当前任务，结束后再关闭窗口？',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)
                if answer==QMessageBox.StandardButton.Yes:self._close_when_idle=True;self.jobs.cancel()
            event.ignore();return
        if not self.force_close and self.has_unsaved_work():
            answer=QMessageBox.question(self,'工作尚未保存','保存分析项目后退出？',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
            if answer==QMessageBox.StandardButton.Cancel:event.ignore();return
            if answer==QMessageBox.StandardButton.Save:
                event.ignore();self.guard(lambda:self.choose_save_project(after=self.close));return
        try:QApplication.instance().focusChanged.disconnect(self.watch_editor_focus)
        except (RuntimeError,TypeError):pass
        event.accept()
