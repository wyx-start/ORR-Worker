"""One controlled QThread job. Only the main thread accepts state or files."""
import threading
import os
import traceback
from pathlib import Path
from PySide6.QtCore import QObject,QThread,Signal,Slot
from application.tasks import snapshot,execute,workspace_stamp,JobCancelled


def record_error(message):
    try:
        directory=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'ORR Worker'/'desktop';directory.mkdir(parents=True,exist_ok=True)
        with (directory/'jobs.log').open('a',encoding='utf-8') as stream:stream.write(message+'\n')
    except OSError:pass


class Worker(QThread):
    delivered=Signal(object)
    failed=Signal(str)
    cancelled=Signal()
    progress=Signal(int,str)
    def __init__(self,job,executor=execute,parent=None):
        super().__init__(parent);self.job=job;self.executor=executor;self.cancel_event=threading.Event()
    def run(self):
        try:self.delivered.emit(self.executor(self.job,self.cancel_event.is_set,self.progress.emit))
        except JobCancelled:self.cancelled.emit()
        except Exception as exc:record_error(self.job.operation+'\n'+traceback.format_exc());self.failed.emit(str(exc))


class JobController(QObject):
    progress=Signal(int,str)
    accepted=Signal(object)
    failed=Signal(str)
    discarded=Signal(str)
    activeChanged=Signal(bool)
    idle=Signal()
    def __init__(self,workspace,epoch=lambda:0,parent=None):
        super().__init__(parent);self.workspace=workspace;self.epoch=epoch;self.worker=None
        self._epoch=0;self._stamp=None;self._input_token=None;self._current_inputs=None
    @property
    def busy(self):return self.worker is not None
    def start(self,operation,payload,*,input_token=None,current_inputs=None,executor=execute):
        if self.busy:raise RuntimeError('已有任务正在执行，请等待或取消。')
        job=snapshot(self.workspace,operation,payload);self._epoch=self.epoch();self._stamp=job.stamp
        self._input_token=input_token;self._current_inputs=current_inputs
        worker=Worker(job,executor,self);self.worker=worker
        worker.progress.connect(self._progress);worker.delivered.connect(self._accept);worker.failed.connect(self.failed);worker.cancelled.connect(lambda:self.discarded.emit('任务已取消；设置和正式文件未替换。'))
        worker.finished.connect(self._finished);self.activeChanged.emit(True);worker.start();return job.ident
    def cancel(self):
        if self.worker:self.worker.cancel_event.set();self.progress.emit(0,'正在取消，等待当前文件或计算步骤结束…')
    @Slot(int,str)
    def _progress(self,percent,message):
        if self.worker and not self.worker.cancel_event.is_set():self.progress.emit(percent,message)
    @Slot(object)
    def _accept(self,result):
        prepared=result.get('prepared')
        try:
            stale=(self.worker is None or self.worker.cancel_event.is_set() or self.epoch()!=self._epoch or workspace_stamp(self.workspace)!=self._stamp)
            if self._current_inputs is not None:
                try:stale=stale or self._current_inputs()!=self._input_token
                except Exception:stale=True
            if stale:
                if prepared:prepared.discard()
                self.discarded.emit('任务期间输入已修改或已取消；返回结果已丢弃，正式文件未替换。');return
            if prepared:prepared.publish()
            self.workspace.state.clear();self.workspace.state.update(result['state'])
            self.accepted.emit(result)
        except Exception as exc:
            if prepared:
                try:prepared.discard()
                except OSError:record_error(traceback.format_exc())
            record_error(traceback.format_exc())
            self.failed.emit(str(exc))
    @Slot()
    def _finished(self):
        worker=self.worker;self.worker=None
        if worker:worker.deleteLater()
        self.activeChanged.emit(False);self.idle.emit()


def wait_for_idle(controller,timeout_ms=120000):
    """Verification helper: process the Qt event loop, never block its thread."""
    if not controller.busy:return
    from PySide6.QtCore import QEventLoop,QTimer
    loop=QEventLoop();timer=QTimer();timer.setSingleShot(True)
    controller.idle.connect(loop.quit);timer.timeout.connect(loop.quit);timer.start(timeout_ms);loop.exec()
    controller.idle.disconnect(loop.quit)
    if controller.busy:controller.cancel();raise TimeoutError('Native task exceeded verification timeout')
