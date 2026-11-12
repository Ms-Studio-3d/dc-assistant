"""Checks used by the Windows build, isolated from user project data."""
from pathlib import Path
import json
import traceback


def self_test(report_path, data_dir):
    report_path=Path(report_path)
    report_path.parent.mkdir(parents=True,exist_ok=True)
    try:
        import tkinter as tk
        import openpyxl
        from pypdf import PdfWriter,PdfReader
        from pdfminer.high_level import extract_text
        from .core import Store, NamingRule, write_xlsx
        from . import __version__
        data_dir=Path(data_dir);data_dir.mkdir(parents=True,exist_ok=True)
        root=tk.Tk();root.withdraw();root.update_idletasks();root.destroy()
        store=Store(data_dir/'self-test.sqlite3')
        project=store.save_project('Self test','000075',{})
        assert store.get_project(project)['code']=='000075'
        store.close()
        path=data_dir/'self-test.xlsx'
        write_xlsx(path,{'Check':[['Code'],['000075']]})
        wb=openpyxl.load_workbook(path)
        assert wb.active['A2'].value=='000075';wb.close()
        pdf_path=data_dir/'self-test.pdf'
        writer=PdfWriter();writer.add_blank_page(600,400)
        with pdf_path.open('wb') as stream:writer.write(stream)
        assert len(PdfReader(pdf_path).pages)==1
        assert not extract_text(str(pdf_path),page_numbers={0}).strip()
        report={'passed':True,'version':__version__,'checks':['tkinter','sqlite','project persistence','xlsx export/import','PDF write/read','alternate PDF reader']}
        exit_code=0
    except Exception:
        report={'passed':False,'error':traceback.format_exc()};exit_code=1
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return exit_code
