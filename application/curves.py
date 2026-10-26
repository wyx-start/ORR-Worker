"""Shared plot preparation; scientific currents never receive display smoothing."""
from copy import deepcopy
import math
from matplotlib.colors import is_color_like
from application.data import axis_label,merged_data
from application.figures import new_figure,figure_bytes
from orr_core import DataError,json_bytes,parameter_record,potential_signature
from origin_export import curve_plot_table,csv_bytes
from plot_smoothing import smooth_for_plot,smoothing_defaults,SMOOTH_DENSITY,SMOOTH_MA
from ring_comparison import audit_ring_comparison

PALETTE=['#167D8D','#D66A3C','#6956A3','#609A65','#B7486C','#A68138','#416EBA','#777777']


def calculate_curves(workspace,selected,channel='disk',*,commit=True):
    if channel not in ('disk','ring'):raise DataError('请选择盘电流或环电流。')
    workspace.clear_polarization_exports(channel)
    key='curves' if channel=='disk' else 'ring_curves';workspace.state.results.pop(key,None)
    configs,scientific=workspace.pending_candidate();plot_key='plot' if channel=='disk' else 'ring_plot'
    options=deepcopy(scientific.get(plot_key,{}));is_ring=channel=='ring'
    subtract=not is_ring or options.get('background_view','处理后')!='未扣背景'
    outputs,errors=workspace.process_selected(selected,configs,scientific,channels='ring' if is_ring else 'all',subtract_background=subtract)
    if not outputs:raise DataError('没有可处理的曲线。'+'；'.join(e['原因'] for e in errors))
    audit=audit_ring_comparison(outputs) if is_ring else None
    if audit and not audit['allowed']:
        raise DataError('环电流比较存在已知条件冲突。'+'；'.join(f"{r['条件']}：{r['差异']}" for r in audit['conflicts']))
    if not is_ring and len({potential_signature(o['config'],o['axis']) for o in outputs.values()})>1:
        raise DataError('选中曲线的原始参比坐标不一致。请改用 RHE 或分别绘图。')
    smoothing=smoothing_defaults(options.get('smoothing'));enabled=bool(smoothing['enabled'])
    density=bool(options.get('density',False)) and not is_ring;unit=options.get('unit','uA') if is_ring else ('mA/cm2' if density else 'mA')
    if unit not in ('mA','uA','mA/cm2'):raise DataError('当前电流单位无效。')
    ycol=('I_ring_mA' if unit=='mA' else 'I_ring_uA') if is_ring else ('j_disk_mA_cm2' if density else 'I_disk_mA')
    for output in outputs.values():
        if ycol not in output['data']:raise DataError(output['name']+'：缺少当前单位需要的盘面积或电流列。')
    for axis in ('x','y'):
        lower,upper=options.get(axis+'min'),options.get(axis+'max')
        if any(v is not None and (isinstance(v,bool) or not math.isfinite(float(v))) for v in (lower,upper)):
            raise DataError('坐标范围必须是有限数值，留空表示自动。')
        if lower is not None and upper is not None and lower>=upper:raise DataError('坐标最小值必须小于最大值。')
    width,height=float(options.get('width',8)),float(options.get('height',5));lw=float(options.get('line_width',1.8))
    if not 4<=width<=16 or not 3<=height<=12 or not .5<=lw<=5:raise DataError('请使用有效的图片尺寸和线宽。')
    colors=options.setdefault('colors',{});plotted={};reports={};fig=new_figure(width,height);ax=fig.subplots()
    for index,(ident,output) in enumerate(outputs.items()):
        color=colors.get(ident,PALETTE[index%len(PALETTE)])
        if not is_color_like(color):raise DataError(output['name']+'：颜色格式无效。')
        colors[ident]=color;frame,report=smooth_for_plot(output['data'],smoothing,channel)
        reports[ident]=dict(report,filename=output['name'],sha256=output['sha256'])
        display_col=(f'I_ring_smoothed_plot_only_{unit}' if is_ring else (SMOOTH_DENSITY if density else SMOOTH_MA)) if enabled else ycol
        if enabled and smoothing.get('show_unsmoothed',True) and report['applied_points']:
            ax.plot(frame.E_V,frame[ycol],color=color,lw=max(.7,lw*.65),alpha=.28)
        frame['plotted_current_value']=frame[display_col];frame['plotted_current_unit']=unit
        if is_ring:
            frame['background_view']=options.get('background_view','处理后');frame['sample_name']=output['config']['name']
            frame['I_ring_corrected_A']=frame['I_ring_A'] if subtract else float('nan')
        plotted[ident]=dict(output,data=frame,plot_channel=channel,plot_smoothing_enabled=enabled)
        ax.plot(frame.E_V,frame[display_col],label=output['config']['name'],color=color,lw=lw)
    ylabel=('Ring I / mA' if unit=='mA' else 'Ring I / μA') if is_ring else ('j / mA cm$^{-2}$' if density else 'I / mA')
    ax.set(xlabel=axis_label(outputs),ylabel=ylabel,title=options.get('title','RRDE ring current comparison' if is_ring else 'ORR polarization curves'))
    ax.set_xlim(left=options.get('xmin'),right=options.get('xmax'));ax.set_ylim(bottom=options.get('ymin'),top=options.get('ymax'))
    ax.axhline(0,color='#D9DFE2',lw=.7,zorder=0)
    if options.get('legend',True):ax.legend(frameon=False,fontsize=8)
    if enabled:fig.text(.5,-.01,f"Display only · Savitzky–Golay: {smoothing['window_points']} points, order 2 · gaps retained",ha='center',fontsize=8)
    options.update(smoothing=smoothing,smoothing_report=reports,selected=list(selected))
    if audit:options['comparison_audit']=audit
    scientific[plot_key]=options
    wide=curve_plot_table(plotted)
    result=dict(figure=fig,outputs=outputs,plotted=plotted,errors=errors,plot=wide,channel=channel,
        smoothing_report=reports,comparison_audit=audit,options=options,revision=workspace.state.revision)
    if commit:
        png,svg=figure_bytes(fig);name='ring_current' if is_ring else 'polarization'
        payloads={name+'_plot.csv':(csv_bytes(wide),'text/csv'),name+'_data.csv':(csv_bytes(merged_data(plotted)),'text/csv'),
            name+'.png':(png,'image/png'),name+'.svg':(svg,'image/svg+xml'),
            ('ring_current_parameters.json' if is_ring else 'parameters.json'):(json_bytes(parameter_record(workspace.state.traces,configs,scientific,outputs)),'application/json')}
        workspace.apply_pending_settings();workspace.state.settings[plot_key]=options
        result['revision']=workspace.state.revision
        for filename,(payload,mime) in payloads.items():workspace.set_export(filename,payload,mime)
        workspace.state.results[key]={k:v for k,v in result.items() if k!='figure'}
    return result
