"""Qt metadata model emits explicit stored-record edits, never effective views."""
from copy import deepcopy
from PySide6.QtCore import QAbstractTableModel, Qt, Signal
from PySide6.QtWidgets import QStyledItemDelegate,QComboBox
from orr_core import DataError,set_manual_rpm
from background_pairing import apply_background_binding


class FileModel(QAbstractTableModel):
    changed=Signal()
    failed=Signal(str)
    columns=[('文件',None),('样品 / 图例','name'),('分组','group'),('用途','role'),('转速 / rpm','rpm'),('盘背景','background_disk'),('点数',None)]
    def __init__(self,workspace,parent=None):
        super().__init__(parent);self.workspace=workspace;self.ids=[];self.reload()
    def reload(self):
        self.beginResetModel();self.ids=list(self.workspace.state.traces);self.endResetModel()
    def rowCount(self,parent=None):return len(self.ids)
    def columnCount(self,parent=None):return len(self.columns)
    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if role==Qt.ItemDataRole.DisplayRole:return self.columns[section][0] if orientation==Qt.Orientation.Horizontal else section+1
    def flags(self,index):
        flags=super().flags(index)
        if index.isValid() and self.columns[index.column()][1]:
            config=self.workspace.get_edit_configs('metadata')[self.ids[index.row()]]
            if index.column()!=5 or config.get('role')!='背景':flags|=Qt.ItemFlag.ItemIsEditable
        return flags
    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.EditRole):return None
        ident=self.ids[index.row()];trace=self.workspace.state.traces[ident]
        config=self.workspace.get_edit_configs('metadata')[ident];field=self.columns[index.column()][1]
        value=trace.name if index.column()==0 else len(trace.values) if index.column()==6 else config.get(field)
        if field=='background_disk' and role==Qt.ItemDataRole.DisplayRole:
            return self.workspace.state.traces[value].name if value in self.workspace.state.traces else '不扣除'
        return '' if value is None else value
    def setData(self,index,value,role=Qt.ItemDataRole.EditRole):
        if role!=Qt.ItemDataRole.EditRole or not index.isValid():return False
        ident=self.ids[index.row()];field=self.columns[index.column()][1]
        if not field:return False
        records=self.workspace.get_edit_configs('metadata');old=records[ident];patch={field:value}
        try:
            if field=='rpm':
                config=deepcopy(old);set_manual_rpm(config,value)
                patch={k:v for k,v in config.items() if k.startswith('rpm')}
            elif field=='role' and value not in ('样品','RRDE','背景'):raise DataError('请选择样品、RRDE 或背景。')
            elif field=='background_disk':
                if old.get('role')=='背景':raise DataError('背景文件不能再绑定背景。')
                background=value or None;config=deepcopy(old)
                mode='paired' if len(self.workspace.state.traces[ident].columns)>=3 else 'independent'
                apply_background_binding(ident,config,self.workspace.state.traces,records,mode,background,old.get('background_ring'))
                patch={k:config[k] for k in ('background_mode','background_disk','background_ring','background_reviewed')}
            accepted=self.workspace.stage_config_updates('metadata',{ident:patch})
            if not accepted:self.failed.emit(self.workspace.state.get('draft_error','修改未接受'))
            self.dataChanged.emit(index,index);self.changed.emit();return accepted
        except (DataError,ValueError,TypeError) as exc:
            self.workspace.reject_config_updates('metadata',{ident:patch},str(exc));self.failed.emit(str(exc));self.changed.emit();return False


class ChoiceDelegate(QStyledItemDelegate):
    def __init__(self,choices,parent=None):super().__init__(parent);self.choices=choices
    def createEditor(self,parent,option,index):
        combo=QComboBox(parent)
        for label,value in self.choices():combo.addItem(label,value)
        return combo
    def setEditorData(self,editor,index):editor.setCurrentIndex(max(editor.findData(index.data(Qt.ItemDataRole.EditRole)),0))
    def setModelData(self,editor,model,index):model.setData(index,editor.currentData())
