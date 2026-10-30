"""Threshold onset and plateau half-wave from unsmoothed processed disk data."""
from copy import deepcopy
import math
import numpy as np
from orr_core import DataError
from origin_export import effective_axis

DEFAULTS=dict(onset_threshold=.1,onset_unit='mA/cm2',plateau_mode='auto',plateau_start=None,
              plateau_end=None,baseline_mA=0.,show_markers=False)
METHOD='threshold-and-plateau-v1'
MIN_PLATEAU_POINTS=5
MAX_PLATEAU_SPREAD=.10


def potential_options(values=None):
    options=dict(DEFAULTS,**(values or {}))
    for key in ('onset_threshold','baseline_mA','plateau_start','plateau_end'):
        value=options[key]
        if value is None and key.startswith('plateau_'):continue
        try:
            if isinstance(value,bool):raise ValueError()
            options[key]=float(value)
            if not math.isfinite(options[key]):raise ValueError()
        except (ValueError,TypeError):raise DataError('电位指标参数 '+key+' 必须是有限数值。')
    if options['onset_threshold']<=0:raise DataError('起始电位的还原电流阈值必须大于 0。')
    if options['onset_unit'] not in ('mA/cm2','mA'):raise DataError('起始电位阈值单位无效。')
    if options['plateau_mode'] not in ('auto','manual'):raise DataError('平台选择方式无效。')
    if options['plateau_mode']=='manual' and (options['plateau_start'] is None or options['plateau_end'] is None or options['plateau_start']>=options['plateau_end']):
        raise DataError('请填写有效的平台电位区间：起点小于终点。')
    return options


def _crossing(e,q,target):
    """Adjacent observations only, in descending potential; never bridge a gap."""
    scale=max(abs(target),float(np.max(np.abs(q[np.isfinite(q)]))) if np.isfinite(q).any() else 0.,1e-12)
    equal=np.isfinite(q)&np.isclose(q,target,rtol=0.,atol=16*np.finfo(float).eps*scale)
    exact=np.flatnonzero(equal);points=[]
    if len(exact)>1:return None,'ambiguous','目标电流对应多个电位或水平段。'
    points.extend(float(e[i]) for i in exact)
    directions=[]
    for i in range(len(e)-1):
        a,b=q[i],q[i+1]
        if np.isfinite(a) and np.isfinite(b) and not equal[i] and not equal[i+1] and (a<target<b or b<target<a):
            points.append(float(e[i]+(target-a)*(e[i+1]-e[i])/(b-a)))
            directions.append(b>a)
    if len(points)>1:return None,'ambiguous','目标电流有多个交点；请检查扫描段、噪声或多重还原波。'
    if not points:return None,'unavailable','数据未覆盖目标电流，或交点位于数据缺口；不外推、不跨缺口。'
    finite=q[np.isfinite(q)]
    if len(finite) and finite[0]>target:return None,'unavailable','高电位端已经超过目标电流，未覆盖完整 ORR 过渡。'
    if directions and not directions[0]:return None,'unavailable','交点方向不符合向低电位还原电流增加；请核对符号和支线。'
    return points[0],'ok','相邻未平滑数据线性内插。'


def analyze_potentials(output,options=None):
    o=potential_options(options);cfg=output.get('config',{});frame=output['data']
    row=dict(file=output.get('name',cfg.get('name','')),sample=cfg.get('name',output.get('name','')),
        sha256=output.get('sha256'),axis=effective_axis(output),rpm=cfg.get('rpm'),
        segment=output.get('segment',{}).get('segment'),direction=output.get('segment',{}).get('direction'),
        disk_sign=cfg.get('disk_sign',-1),area_cm2=cfg.get('area_cm2'),background_disk=cfg.get('background_disk'),
        method=METHOD,unsmoothed=True,onset_threshold=o['onset_threshold'],onset_unit=o['onset_unit'],
        baseline_mA=o['baseline_mA'],plateau_mode=o['plateau_mode'],plateau_estimator='median',
        min_plateau_points=MIN_PLATEAU_POINTS,max_plateau_spread=MAX_PLATEAU_SPREAD,
        E_onset_V=None,E_half_V=None,onset_status='unavailable',onset_reason='',half_status='unavailable',half_reason='',
        onset_target_mA=None,half_target_mA=None,plateau_current_mA=None,plateau_start_V=None,plateau_end_V=None,
        plateau_points=0,plateau_spread_fraction=None)
    def fail(reason):
        row.update(onset_reason=reason,half_reason=reason);return row
    try:e=frame.E_V.to_numpy(dtype=float);q=frame.I_disk_A.to_numpy(dtype=float)*1000
    except (AttributeError,ValueError,TypeError):return fail('缺少有效的未平滑盘电流或电位列。')
    sign=cfg.get('disk_sign',-1)
    if isinstance(sign,bool) or sign not in (-1,1):return fail('盘电流符号必须为 -1 或 1。')
    q=q*sign
    if len(e)<2 or not np.isfinite(e).all():return fail('电位点不足或含缺失电位。')
    differences=np.diff(e)
    if not (np.all(differences>0) or np.all(differences<0)):return fail('电位必须是严格单调支线；重复电位或折返不能拼接计算。')
    if differences[0]>0:e=e[::-1];q=q[::-1]
    base=o['baseline_mA'];area=cfg.get('area_cm2');threshold=o['onset_threshold']
    if o['onset_unit']=='mA/cm2':
        try:
            if isinstance(area,bool) or not math.isfinite(float(area)) or float(area)<=0:raise ValueError()
            threshold*=float(area)
        except (ValueError,TypeError):threshold=None;row['onset_reason']='电流密度阈值需要有效的盘几何面积；可补面积或改用 mA 阈值。'
    if threshold is not None:
        row['onset_target_mA']=base+threshold
        row['E_onset_V'],row['onset_status'],row['onset_reason']=_crossing(e,q,base+threshold)
    low,high=(float(e.min()),float(e.min()+.2*(e.max()-e.min()))) if o['plateau_mode']=='auto' else (o['plateau_start'],o['plateau_end'])
    row.update(plateau_start_V=low,plateau_end_V=high)
    if low<e.min()-1e-10 or high>e.max()+1e-10:
        row['half_reason']='指定平台区间未被本曲线完整覆盖。';return row
    region=q[(e>=low-1e-12)&(e<=high+1e-12)];row['plateau_points']=int(np.isfinite(region).sum())
    if len(region)<MIN_PLATEAU_POINTS or row['plateau_points']<MIN_PLATEAU_POINTS:
        row['half_reason']='平台区间至少需要 5 个有效点；请手动选择覆盖充分的平台。';return row
    if not np.isfinite(region).all():row['half_reason']='平台区间含数据缺口，请选择连续有效平台。';return row
    limiting=float(np.median(region));height=limiting-base;row['plateau_current_mA']=limiting
    if height<=0:row['half_reason']='平台相对基线没有正的还原电流高度；请核对盘符号或平台。';return row
    spread=float(np.ptp(region)/height);row['plateau_spread_fraction']=spread
    if spread>MAX_PLATEAU_SPREAD:
        row['half_reason']='平台电流跨度超过波高的 10%；不能认定稳定平台，请手动核对区间。';return row
    row['half_target_mA']=base+.5*height
    row['E_half_V'],row['half_status'],row['half_reason']=_crossing(e,q,row['half_target_mA'])
    if row['half_status']=='ok' and o['plateau_mode']=='auto':row['half_reason']+=' 自动最低 20% 电位区间仅为平台候选，请核对。'
    return row
