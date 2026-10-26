"""Generated-only closed-loop verification available in source and frozen builds."""
from pathlib import Path
import json
from PySide6.QtWidgets import QApplication


def verify(window, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    name=output/'中文 样品 1600转.txt'
    potentials=[i/10 for i in range(11)]+[i/10 for i in range(9,-1,-1)]
    raw='SYNTHETIC DESKTOP SMOKE - NO MEASURED DATA\nHigh E (V) = 1\nLow E (V) = 0\nPotential/V,Current/A\n'
    raw+='\n'.join(f'{e},{-0.001*(1+e)}' for e in potentials)
    name.write_text(raw,encoding='utf-8')
    assert window.import_paths([name])==1
    ident=next(iter(window.workspace.state.traces))
    assert window.workspace.state.configs[ident]['pH']==13
    assert window.workspace.state.configs[ident]['rpm']==1600
    window.fields['pH'].setText('12');window.stage_field('pH');window.apply()
    assert window.workspace.state.configs[ident]['pH']==12
    assert window.workspace.state.configs[ident]['parameter_sources']['pH']=='用户输入（桌面端）'
    window.segment.setCurrentIndex(window.segment.findData(2));window.apply()
    result=window.calculate()
    assert result['outputs'][ident]['segment']['segment']==2
    for name in ('polarization_plot.csv','polarization.png','polarization.svg'):
        window.export_file(name,output/name);assert (output/name).stat().st_size>10
    project=output/'中文 项目.orrproj';window.save_project(project);window.open_project(project)
    assert window.workspace.state.configs[ident]['pH']==12
    window.calculate();window.show();QApplication.processEvents()
    assert window.grab().save(str(output/'desktop.png'))
    report=dict(passed=True,real_data_read=False,native_window=True,imports=1,manual_segment=2,
        csv_png_svg=True,project_roundtrip=True,clean_machine=False)
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
