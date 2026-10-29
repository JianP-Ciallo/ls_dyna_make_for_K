"""Read existing native pressure histories; never solves or resamples results."""
import csv
from io import StringIO
from pathlib import Path
import re
import numpy as np


def pressure_history(time_s, element_ids, stress_pa, monitor, reference_pressure_pa):
    t=np.asarray(time_s,float); ids=np.asarray(element_ids); stress=np.asarray(stress_pa,float)
    if ids.ndim==2:
        if not np.all(ids==ids[0]): raise ValueError('原生监测单元编号在时程中改变')
        ids=ids[0]
    if t.ndim!=1 or len(t)<2 or not np.all(np.isfinite(t)) or np.any(np.diff(t)<=0):
        raise ValueError('原生输出时钟必须有限且严格递增')
    if ids.ndim!=1 or stress.shape!=(len(t),len(ids),3) or not np.all(np.isfinite(stress)):
        raise ValueError('原生应力数组或监测编号不完整')
    if not np.isfinite(reference_pressure_pa): raise ValueError('无效参考压力')
    offsets=np.flatnonzero(ids==monitor['element_id'])
    if len(offsets)!=1:raise ValueError('结果中缺失或重复的监测单元')
    pressure=-stress[:,int(offsets[0]),:].mean(axis=1)
    over=pressure-float(reference_pressure_pa); positive=np.maximum(over,0)
    impulse=float(np.sum(np.diff(t)*(positive[:-1]+positive[1:])/2))
    return dict(monitor, time_s=t.tolist(), pressure_pa=pressure.tolist(), overpressure_pa=over.tolist(),
                reference_pressure_pa=float(reference_pressure_pa), pressure_kind='cell_mean_hydrostatic',
                pressure_description='单元平均静水压力；压缩为正，未等同于全程空气材料压力',
                peak_overpressure_pa=float(max(0.,over.max())), positive_impulse_pa_s=impulse,
                actual_window_s=[float(t[0]),float(t[-1])], native_clock_preserved=True)


def read_native_pressure(directory, monitors, reference_pressure_pa=101325.):
    try:
        from lasso.dyna import Binout
    except ImportError as exc:
        raise ValueError('读取原生结果需要已安装 lasso-python；没有启动求解') from exc
    files=native_binout_files(directory)
    if not files or any(p.is_symlink() or not p.is_file() for p in files):
        raise ValueError('未找到有效原生binout结果')
    if len(files)>64 or sum(p.stat().st_size for p in files)>2*1024**3:
        raise ValueError('结果读取超过当前2 GiB文件预算')
    pattern='binout' if (Path(directory)/'binout').is_file() else 'binout[0-9]*'
    if set(Path(directory).glob(pattern))!=set(files):
        raise ValueError('原生binout文件命名有歧义，请选择同一次运行的结果文件夹')
    b=Binout(str(Path(directory)/pattern))
    try:
        keys=b.read('elout','solid'); t=b.read('elout','solid','time'); ids=b.read('elout','solid','ids')
        def component(name):
            key=next((k for k in keys if k in (name,name.replace('_',''),'sig_'+name[1:])),None)
            if key is None: raise ValueError('原生结果缺少压力应力分量：'+name)
            return np.asarray(b.read('elout','solid',key),float)
        stress=np.stack([component(k) for k in ('sig_xx','sig_yy','sig_zz')],axis=-1)
        if stress.size>24_000_000:raise ValueError('结果采样数超过读取预算')
        air=[m for m in monitors if m['kind']=='air_pressure']
        if not air:raise ValueError('此导出没有空气压力监测点，请在新工况中添加后导出')
        return [pressure_history(t,ids,stress,m,reference_pressure_pa) for m in air]
    finally:
        close=getattr(getattr(b,'lsda',None),'close',None)
        if close:close()


def native_binout_files(directory):
    return sorted(p for p in Path(directory).glob('binout*') if re.fullmatch(r'binout(?:\d+)?(?:%\d+)?',p.name))


def curves_csv(curves):
    output=StringIO(newline=''); writer=csv.writer(output)
    writer.writerow(['monitor_id','element_id','time_s','pressure_pa','overpressure_pa','pressure_kind'])
    for curve in curves:
        for t,p,over in zip(curve['time_s'],curve['pressure_pa'],curve['overpressure_pa']):
            def safe_text(value):
                text=str(value)
                return "'"+text if text.lstrip().startswith(('=','+','-','@')) or text.startswith(('\t','\r','\n')) else text
            writer.writerow([safe_text(curve['id']),curve['element_id'],repr(t),repr(p),repr(over),safe_text(curve['pressure_kind'])])
    return output.getvalue().encode('utf-8-sig')


def choose_result_directory():
    """Explicit local-user selection: the HTTP client cannot submit a filesystem path."""
    import tkinter as tk
    from tkinter import filedialog
    root=tk.Tk();root.withdraw()
    try:
        selected=filedialog.askdirectory(parent=root,title='选择此K包求解后的文件夹（保留原K文件和binout）')
        return Path(selected).resolve() if selected else None
    finally:root.destroy()
