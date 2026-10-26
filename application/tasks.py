"""Immutable in-memory jobs and two-phase file publication; no UI dependencies.

Pickle is used only for snapshots created by this process, never for project or
user-supplied files. Projects continue to use the existing validated ZIP format.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import pickle
import tempfile
import uuid
from copy import deepcopy
from orr_core import DataError,clean_json,json_bytes
from application.workspace import Workspace,State


class JobCancelled(Exception):pass


def project_fingerprint(workspace):
    traces={ident:{'name':trace.name,'raw':hashlib.sha256(trace.raw).hexdigest()}
            for ident,trace in workspace.state.traces.items()}
    data={'traces':traces,'configs':workspace.state.configs,'settings':workspace.state.settings}
    return hashlib.sha256(json.dumps(clean_json(data),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def workspace_stamp(workspace):
    keys=('revision','workspace_epoch','settings_draft','draft_errors','draft_error','rejected_config_edits')
    data={key:workspace.state.get(key) for key in keys}
    data['project']=project_fingerprint(workspace)
    data['arrays']={ident:hashlib.sha256(trace.values.tobytes()).hexdigest() for ident,trace in workspace.state.traces.items()}
    data['exports']={name:hashlib.sha256(value['bytes']).hexdigest() for name,value in workspace.state.exports.items()}
    data['results']={}
    for name,value in workspace.state.results.items():
        if not isinstance(value,dict):continue
        record={key:value.get(key) for key in ('revision','input_signature','selected')}
        if isinstance(record['input_signature'],bytes):record['input_signature']=hashlib.sha256(record['input_signature']).hexdigest()
        data['results'][name]=record
    return hashlib.sha256(json.dumps(clean_json(data),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class JobSnapshot:
    ident:str
    stamp:str
    operation:str
    payload:bytes
    state:bytes


def snapshot(workspace,operation,payload):
    return JobSnapshot(uuid.uuid4().hex,workspace_stamp(workspace),operation,
        pickle.dumps(deepcopy(payload),protocol=5),pickle.dumps(dict(workspace.state),protocol=5))


@dataclass(frozen=True)
class PreparedFile:
    temporary:Path
    target:Path

    def discard(self):
        if self.temporary.parent!=self.target.parent or not self.temporary.name.startswith('.orr-worker-'):
            raise RuntimeError('Invalid temporary publication path')
        self.temporary.unlink(missing_ok=True)

    def publish(self):
        try:os.replace(self.temporary,self.target)
        except OSError:
            self.discard();raise


def prepare_file(target,content,checkpoint=lambda:None):
    target=Path(target).resolve()
    if not target.parent.is_dir():raise OSError('保存目录不存在：'+str(target.parent))
    checkpoint();descriptor,name=tempfile.mkstemp(prefix='.orr-worker-',suffix='.tmp',dir=target.parent)
    prepared=PreparedFile(Path(name),target)
    try:
        with os.fdopen(descriptor,'wb') as stream:
            for offset in range(0,len(content),1024*1024):checkpoint();stream.write(content[offset:offset+1024*1024])
            stream.flush();os.fsync(stream.fileno())
        checkpoint();return prepared
    except BaseException:
        prepared.discard();raise


def atomic_write(target,content):
    prepared=prepare_file(target,content);prepared.publish()


def execute(job,cancelled=lambda:False,progress=lambda percent,message:None):
    from application.curves import calculate_curves
    from application.results import complete_kl,complete_rrde,complete_data,kl_figures,publish_figures,record_kl_parameters,coverage_preview
    from application.data import zip_exports
    workspace=Workspace(State(pickle.loads(job.state)));payload=pickle.loads(job.payload)
    def checkpoint():
        if cancelled():raise JobCancelled()
    workspace.checkpoint=checkpoint
    workspace.progress=progress
    checkpoint();progress(0,'正在准备任务…');result=None;figures={};content=None;prepared=None
    try:
        operation=job.operation
        if operation=='import':
            files=[];errors=[]
            for index,name in enumerate(payload['paths']):
                checkpoint();path=Path(name)
                try:files.append((path.name,path.read_bytes()))
                except OSError as exc:errors.append({'文件':path.name,'原因':str(exc)})
                progress(int(20*(index+1)/max(len(payload['paths']),1)),path.name)
            result={'added':workspace.add_files(files)};workspace.state.import_errors.extend(errors)
        elif operation=='load':
            checkpoint();workspace.restore_project(Path(payload['path']).read_bytes(),discard=True);result={'loaded':payload['path']}
        elif operation=='project':
            workspace.apply_pending_settings()
            for key,values in payload.get('inputs',{}).items():workspace.state.settings.setdefault(key,{}).update(values)
            content=workspace.project_bytes();result={'project':True}
        elif operation=='curves':
            workspace.state.settings[payload['plot_key']]=payload['options'];workspace.state.settings['plot_channel']=payload['channel']
            result=calculate_curves(workspace,payload['selected'],payload['channel']);figures={'ring_current' if payload['channel']=='ring' else 'polarization':result.pop('figure')}
        elif operation=='kl':result,figures=complete_kl(workspace,payload['inputs'])
        elif operation=='rrde':result,figures=complete_rrde(workspace,payload['selected'])
        elif operation=='fit':
            result=workspace.state.results.get('kl')
            if not result:raise DataError('请先计算当前 K–L 结果。')
            figure=kl_figures(result,payload['potential'])['kl_fit'];figures={'kl_fit':figure};publish_figures(workspace,figures)
            workspace.state.settings.setdefault('kl_plot',{})['fit_potential']=float(payload['potential']);record_kl_parameters(workspace,result)
        elif operation=='coverage':result=coverage_preview(workspace,payload['selected'])
        elif operation=='data':result=complete_data(workspace)
        elif operation=='parameters':
            workspace.apply_pending_settings();content=json_bytes(workspace.parameters());workspace.set_export('configuration_parameters.json',content,'application/json')
        elif operation=='zip':
            if workspace.has_draft():raise DataError('请先应用并重新计算，再保存结果包。')
            if not workspace.state.exports:raise DataError('请先生成分析结果。')
            content=zip_exports(workspace.state.exports)
        elif operation=='asset':
            if workspace.has_draft():raise DataError('请先应用并重新生成结果。')
        else:raise DataError('未知后台任务。')
        if operation in ('import','load') and 'start' not in workspace.state.settings.get('kl',{}) and 'end' not in workspace.state.settings.get('kl',{}):
            groups=[c.get('group') for c in workspace.state.configs.values() if c.get('role')!='背景']
            if groups:
                selected=[i for i,c in workspace.state.configs.items() if c.get('role')!='背景' and c.get('group')==groups[0]]
                try:
                    workspace.progress=lambda percent,message:progress(80+int(percent*.1),message)
                    result['coverage']=dict(coverage_preview(workspace,selected),group=groups[0])
                except (DataError,ValueError,TypeError) as exc:result['coverage_error']=str(exc)
        checkpoint();progress(90,'正在准备结果文件…')
        if payload.get('target'):
            if content is None:
                name=payload.get('asset')
                if not name or name not in workspace.state.exports:raise DataError('当前任务没有生成所选结果文件。')
                content=workspace.state.exports[name]['bytes']
            prepared=prepare_file(payload['target'],content,checkpoint)
        checkpoint();progress(100,'等待核对设置与接收结果…')
        return {'state':workspace.state,'result':result,'figures':figures,'prepared':prepared,'operation':operation,'payload':payload}
    except BaseException:
        if prepared:prepared.discard()
        raise
