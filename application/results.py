"""Shared scientific figures and complete result exports; no frontend imports."""
from application.data import axis_label,merged_data,zip_exports
from application.figures import new_figure,figure_bytes
from origin_export import csv_bytes,effective_axis,kl_fit_plot_table
from orr_core import DataError,json_bytes,parameter_record


def publish_figures(workspace,figures):
    for name,figure in figures.items():
        workspace.checkpoint()
        png,svg=figure_bytes(figure)
        workspace.checkpoint()
        workspace.set_export(name+'.png',png,'image/png');workspace.set_export(name+'.svg',svg,'image/svg+xml')


def rrde_figures(saved):
    chosen=saved['outputs'];fig=new_figure(8,7);axes=fig.subplots(2,1,sharex=True)
    model=new_figure(8,4.5);ax=model.subplots()
    for ident,frame in saved['frames'].items():
        name=chosen[ident]['config']['name'];axes[0].plot(frame.E_V,frame.peroxide_pct,label=name);axes[1].plot(frame.E_V,frame.n_RRDE,label=name)
        line,=ax.plot(frame.E_V,frame.peroxide_pct,label=name+' · 2e');ax.plot(frame.E_V,frame.four_e_pct_model,color=line.get_color(),ls='--',label=name+' · 4e (model)')
    axes[0].set(ylabel='Peroxide yield / %',title='RRDE analysis');axes[1].set(xlabel=axis_label(chosen),ylabel='Electron number n')
    axes[0].axhline(100,color='#b5bdc1',ls='--',lw=.8);axes[1].axhline(2,color='#b5bdc1',ls='--',lw=.8);axes[1].axhline(4,color='#b5bdc1',ls='--',lw=.8)
    axes[0].legend(frameon=False,fontsize=8);ax.set(xlabel=axis_label(chosen),ylabel='Product fraction / %',title='RRDE two-product model');ax.legend(frameon=False,fontsize=8)
    return {'rrde_selectivity':fig,'rrde_two_four_e':model}


def kl_figures(saved,potential=None):
    result,points=saved['data'],saved['points'];chosen=saved['outputs'];figures={}
    fig=new_figure(8,4.5);ax=fig.subplots();ax.plot(result.E_V,result.n_KL,color='#167d8d',marker='o',ms=3)
    for n in (2,4):ax.axhline(n,color='#b5bdc1',ls='--',lw=.8)
    ax.set(xlabel=axis_label(chosen),ylabel='Apparent electron number n',title='Koutecky–Levich analysis');figures['kl_electron_number']=fig
    fig=new_figure(8,4.5);ax=fig.subplots();ax.plot(result.E_V,result.two_e_pct_model,label='2e (model)');ax.plot(result.E_V,result.four_e_pct_model,label='4e (model)')
    ax.set(xlabel=axis_label(chosen),ylabel='Selectivity estimate / %',title='K–L two-path model estimate');ax.legend(frameon=False);figures['kl_two_four_e_model']=fig
    if not points.empty:
        available=sorted(points.E_V.unique());potential=available[len(available)//2] if potential is None else potential
        fit=points[points.E_V==potential].sort_values('omega_inv_sqrt')
        if fit.empty:raise DataError('所选电位没有可显示的拟合点。')
        fig=new_figure(7,4);ax=fig.subplots();ax.scatter(fit.omega_inv_sqrt,fit.inverse_j_cm2_A,label='Data',color='#167d8d');ax.plot(fit.omega_inv_sqrt,fit.fit_inverse_j_cm2_A,label='Linear fit',color='#d66a3c')
        fig.orr_fit_potential=float(potential)
        ax.set(xlabel='ω$^{-1/2}$ / (rad s$^{-1}$)$^{-1/2}$',ylabel='1/j / cm$^2$ A$^{-1}$',title=f'K–L fit at {potential:.4f} V');ax.legend(frameon=False);figures['kl_fit']=fig
    return figures


def complete_rrde(workspace,selected):
    saved=workspace.calculate_rrde(selected);figures=rrde_figures(saved);publish_figures(workspace,figures)
    workspace.set_export('rrde_plot.csv',csv_bytes(saved['plot']),'text/csv')
    workspace.set_export('rrde_parameters.json',json_bytes(saved['params']),'application/json')
    return saved,figures


def complete_kl(workspace,inputs):
    saved=workspace.calculate_kl(inputs)
    potential=workspace.state.settings.get('kl_plot',{}).get('fit_potential')
    if saved['points'].empty or potential not in saved['points'].E_V.to_numpy():potential=None
    figures=kl_figures(saved,potential);publish_figures(workspace,figures)
    if 'kl_fit' in figures:workspace.state.settings.setdefault('kl_plot',{})['fit_potential']=figures['kl_fit'].orr_fit_potential
    axis='RHE' if all(effective_axis(o)=='RHE' for o in saved['outputs'].values()) else saved['params']['axis']
    wide=saved['data'][['E_V','n_KL','two_e_pct_model','four_e_pct_model']].rename(columns={'E_V':'E_RHE_V' if axis=='RHE' else 'E_original_reference_V'})
    workspace.set_export('kl_plot.csv',csv_bytes(wide),'text/csv');workspace.set_export('kl_fit_plot.csv',csv_bytes(kl_fit_plot_table(saved['points'],axis)),'text/csv')
    record_kl_parameters(workspace,saved)
    return saved,figures


def record_kl_parameters(workspace,saved):
    params=parameter_record(workspace.state.traces,workspace.state.configs,workspace.state.settings,saved['outputs'])
    params['analysis_kl']=saved['params'];params['analysis_display']=dict(fit_potential_V=workspace.state.settings.get('kl_plot',{}).get('fit_potential'))
    workspace.set_export('kl_parameters.json',json_bytes(params),'application/json')


def complete_data(workspace):
    workspace.state.exports.pop('all_curves.csv',None);workspace.state.exports.pop('parameters.json',None)
    configs,settings=workspace.pending_candidate();outputs,errors=workspace.process_selected(list(workspace.state.traces),configs,settings)
    if not outputs:raise DataError('没有可处理的数据。'+'；'.join(e['原因'] for e in errors))
    payload=csv_bytes(merged_data(outputs));params=json_bytes(parameter_record(workspace.state.traces,configs,settings,outputs))
    workspace.apply_pending_settings();workspace.set_export('all_curves.csv',payload,'text/csv');workspace.set_export('parameters.json',params,'application/json')
    return outputs,errors


def coverage_preview(workspace,selected):
    configs,settings=workspace.pending_candidate();outputs,errors=workspace.process_selected(selected,configs,settings,channels='disk')
    if errors or not outputs or len(outputs)!=len(selected):raise DataError('共同覆盖需要全部所选文件可处理。'+'；'.join(e['文件']+'：'+e['原因'] for e in errors))
    low=max(float(o['data'].E_V.min()) for o in outputs.values());high=min(float(o['data'].E_V.max()) for o in outputs.values())
    if low>=high:raise DataError('所选曲线没有共同覆盖。')
    return {'start':low,'end':high}
