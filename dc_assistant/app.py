from __future__ import annotations

import argparse
import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .core import (DEFAULT_STATUSES, ROLE_LABELS, NamingRule, Store, excel_columns,
                   excel_sheets, export_results, read_register, scan_batch)


def field(parent, row, label, value="", width=60):
    ttk.Label(parent, text=label, anchor="e").grid(row=row, column=1, sticky="e", padx=8, pady=6)
    var = tk.StringVar(value=value)
    ttk.Entry(parent, textvariable=var, width=width, justify="right").grid(row=row, column=0, sticky="ew", padx=8, pady=6)
    return var


class ProjectDialog(tk.Toplevel):
    def __init__(self, app, project=None):
        super().__init__(app)
        self.app, self.project, self.result = app, project, None
        self.title("إعدادات المشروع" if project else "مشروع جديد")
        self.geometry("1000x690")
        self.minsize(850, 620)
        self.transient(app)
        self.grab_set()
        settings = project["settings"] if project else {}
        book = ttk.Notebook(self)
        book.pack(fill="both", expand=True, padx=14, pady=12)
        basic, naming, procedure = [ttk.Frame(book, padding=14) for _ in range(3)]
        book.add(basic, text="المشروع")
        book.add(naming, text="قواعد التسمية")
        book.add(procedure, text="الحالات والإجراءات")
        basic.columnconfigure(0, weight=1)
        self.name_var = field(basic, 0, "اسم المشروع *", project["name"] if project else "")
        self.code_var = field(basic, 1, "كود المشروع كما هو", project["code"] if project else "")
        self.alias_var = field(basic, 2, "بدائل كود المشروع المسموحة، مفصولة بفاصلة", ", ".join(settings.get("project_aliases", [])))
        self.exclude_var = field(basic, 3, "أسماء فولدرات تُستبعد من الفحص، مفصولة بفاصلة", ", ".join(settings.get("excluded_folders", [])))
        ttk.Label(basic, text="تسجيل المشروع يحتاج الاسم فقط. أكمل قواعد التسمية قبل فحص الملفات.", anchor="e").grid(row=4, column=0, columnspan=2, sticky="e", padx=8, pady=18)
        self.case_var = tk.BooleanVar(value=settings.get("ignore_case", False))
        ttk.Checkbutton(basic, text="السماح باختلاف الحروف الكبيرة والصغيرة عند المطابقة", variable=self.case_var).grid(row=5,column=0,columnspan=2,sticky="e",padx=8)

        naming.columnconfigure(0, weight=1)
        self.example_var = field(naming, 0, "مثال صحيح لاسم ملف لوحة", settings.get("example", ""))
        ttk.Label(naming,text="الفاصل بين أجزاء الاسم").grid(row=1,column=1,sticky="e",padx=8)
        self.separator_var=tk.StringVar(value=settings.get("separator", "-"))
        ttk.Combobox(naming,textvariable=self.separator_var,values=["-","_","."],width=8,state="readonly").grid(row=1,column=0,sticky="e",padx=8)
        ttk.Button(naming,text="عرض أجزاء المثال",command=self.build_parts).grid(row=2,column=0,columnspan=2,sticky="e",padx=8,pady=8)
        ttk.Label(naming,text="حدد وظيفة كل جزء. الأجزاء الثابتة يجب أن تظل مطابقة للمثال.",anchor="e").grid(row=3,column=0,columnspan=2,sticky="e",padx=8)
        container=ttk.Frame(naming)
        container.grid(row=4,column=0,columnspan=2,sticky="nsew",pady=8)
        naming.rowconfigure(4,weight=1)
        canvas=tk.Canvas(container,highlightthickness=0)
        scrollbar=ttk.Scrollbar(container,orient="vertical",command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right",fill="y")
        canvas.pack(side="left",fill="both",expand=True)
        self.parts_frame=ttk.Frame(canvas)
        window=canvas.create_window((0,0),window=self.parts_frame,anchor="nw")
        self.parts_frame.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",lambda e:canvas.itemconfigure(window,width=e.width))
        self.part_vars=[]
        self.optional_var=tk.BooleanVar(value=settings.get("optional_revision", True))
        ttk.Checkbutton(naming,text="السماح برقم لوحة دون إصدار عند قراءة اللوج",variable=self.optional_var).grid(row=5,column=0,columnspan=2,sticky="e",padx=8)
        self.fallback_var=tk.BooleanVar(value=settings.get("pdf_fallback",True))
        ttk.Checkbutton(naming,text="قراءة موسعة لملفات PDF المعقدة عند فشل القراءة السريعة (أبطأ)",variable=self.fallback_var).grid(row=6,column=0,columnspan=2,sticky="e",padx=8)
        if settings.get("parts"):
            self.build_parts(settings["parts"])

        ttk.Label(procedure,text="أكواد الحالات ومعانيها: كود = المعنى",anchor="e").pack(fill="x")
        self.status_text=tk.Text(procedure,height=6,wrap="word",font=("Segoe UI",11))
        self.status_text.pack(fill="x",pady=(5,16))
        self.status_text.insert("1.0","\n".join(f"{k} = {v}" for k,v in settings.get("statuses",DEFAULT_STATUSES).items()))
        ttk.Label(procedure,text="مرجع الردود والتسليمات وقواعد نطاق التقارير",anchor="e").pack(fill="x")
        self.procedure_text=tk.Text(procedure,height=10,wrap="word",font=("Segoe UI",11))
        self.procedure_text.pack(fill="both",expand=True,pady=5)
        self.procedure_text.insert("1.0",settings.get("procedure_notes", ""))
        buttons=ttk.Frame(self,padding=12)
        buttons.pack(fill="x")
        ttk.Button(buttons,text="حفظ المشروع",command=self.save).pack(side="right",padx=6)
        ttk.Button(buttons,text="إلغاء",command=self.destroy).pack(side="right",padx=6)

    def build_parts(self, existing=None):
        if existing is not None and not isinstance(existing,list): existing=None
        for child in self.parts_frame.winfo_children(): child.destroy()
        self.part_vars=[]
        example=self.example_var.get().strip()
        if example.lower().endswith((".pdf",".dwg")): example=example[:-4]
        samples=[p["sample"] for p in existing] if existing else example.split(self.separator_var.get()) if example else []
        for i,sample in enumerate(samples):
            role=existing[i]["role"] if existing else "literal"
            var=tk.StringVar(value=ROLE_LABELS[role])
            ttk.Label(self.parts_frame,text=f"{i+1}.  {sample}",width=42,anchor="e").grid(row=i,column=1,sticky="e",padx=10,pady=3)
            ttk.Combobox(self.parts_frame,textvariable=var,values=list(ROLE_LABELS.values()),state="readonly",width=24).grid(row=i,column=0,padx=10,pady=3)
            self.part_vars.append((sample,var))

    def save(self):
        try:
            reverse={v:k for k,v in ROLE_LABELS.items()}
            parts=[{"sample":sample,"role":reverse[var.get()]} for sample,var in self.part_vars]
            statuses={}
            for line in self.status_text.get("1.0","end").splitlines():
                if not line.strip(): continue
                if "=" not in line: raise ValueError("اكتب كل حالة بالشكل: A = Approved")
                key,value=line.split("=",1)
                if not key.strip() or not value.strip(): raise ValueError("كود الحالة ومعناها مطلوبان")
                statuses[key.strip()]=value.strip()
            settings={"example":self.example_var.get(),"parts":parts,"separator":self.separator_var.get(),
                      "project_aliases":[x.strip() for x in self.alias_var.get().replace("،",",").split(",") if x.strip()],
                      "excluded_folders":[x.strip() for x in self.exclude_var.get().replace("،",",").split(",") if x.strip()],
                      "ignore_case":self.case_var.get(),"optional_revision":self.optional_var.get(),"pdf_fallback":self.fallback_var.get(),"statuses":statuses,
                      "procedure_notes":self.procedure_text.get("1.0","end").strip()}
            if parts:
                rule=NamingRule(settings)
                if not rule.parse(settings["example"]): raise ValueError("مثال الاسم لا يطابق تعريف الأجزاء. اضغط عرض أجزاء المثال بعد تغييره.")
                sample=next((p["sample"] for p in parts if p["role"]=="project"),None)
                if sample and self.code_var.get() and sample!=self.code_var.get(): raise ValueError("كود المشروع في المثال مختلف عن كود المشروع المكتوب")
            self.result=self.app.store.save_project(self.name_var.get(),self.code_var.get(),settings,self.project["id"] if self.project else None)
            self.destroy()
        except Exception as exc: messagebox.showerror("راجع الإعدادات",str(exc),parent=self)


class RegisterDialog(tk.Toplevel):
    def __init__(self, app, path):
        super().__init__(app)
        self.path,self.result=path,None
        self.title("تحديد شيت وأعمدة اللوج")
        self.geometry("850x580")
        self.transient(app); self.grab_set()
        frame=ttk.Frame(self,padding=18);frame.pack(fill="both",expand=True)
        frame.columnconfigure(0,weight=1)
        self.sheet_var=tk.StringVar(value=excel_sheets(path)[0])
        ttk.Label(frame,text="الشيت").grid(row=0,column=1,sticky="e",pady=5)
        ttk.Combobox(frame,textvariable=self.sheet_var,values=excel_sheets(path),state="readonly",width=55).grid(row=0,column=0,sticky="ew",pady=5)
        self.header_var=field(frame,1,"رقم صف العناوين","1")
        self.start_var=field(frame,2,"أول صف بيانات فعلي","2")
        ttk.Button(frame,text="قراءة العناوين",command=self.load_columns).grid(row=3,column=0,sticky="e",pady=8)
        self.mapping_frame=ttk.Frame(frame);self.mapping_frame.grid(row=4,column=0,columnspan=2,sticky="ew")
        self.variables={};self.column_options={}
        ttk.Label(frame,text="الحالة اختيارية، ويجب أن تخص الإصدار المحدد في عمود الإصدار.",anchor="e").grid(row=5,column=0,columnspan=2,sticky="e",pady=14)
        ttk.Button(frame,text="استيراد اللوج",command=self.accept).grid(row=6,column=0,sticky="e",pady=10)
        self.load_columns()

    def load_columns(self):
        try:
            header=int(self.header_var.get())
            if header<1: raise ValueError("صف العناوين يبدأ من 1")
            cols=excel_columns(self.path,self.sheet_var.get(),header)
            for child in self.mapping_frame.winfo_children():child.destroy()
            self.column_options={"غير محدد":None,**{f"{i+1}: {text or '(فارغ)'}":i for i,text in cols}}
            labels={"number":"رقم المستند *","title":"عنوان المستند","revision":"الإصدار","discipline":"التخصص","area":"المنطقة","status":"حالة هذا الإصدار"}
            hints={"number":{"NAME","DRAWING NO.","DRAWING NO","SHEET NUMBER","رقم المستند"},"title":{"DESCRIPTION","DRAWING TITLE","SHEET NAME","العنوان"},"revision":{"REV","REV.","CURRENT REVISION"},"discipline":{"DISCIPLINE"},"area":{"AREA"},"status":set()}
            self.variables={}
            for row,(key,label) in enumerate(labels.items()):
                match=next((option for option,i in self.column_options.items() if i is not None and ' '.join(cols[i][1].upper().split()) in hints[key]),"غير محدد")
                var=tk.StringVar(value=match);self.variables[key]=var
                ttk.Combobox(self.mapping_frame,textvariable=var,values=list(self.column_options),state="readonly",width=60).grid(row=row,column=0,pady=5,sticky="ew")
                ttk.Label(self.mapping_frame,text=label).grid(row=row,column=1,padx=10,sticky="e")
            self.loaded_sheet=self.sheet_var.get();self.loaded_header=header
        except Exception as exc:messagebox.showerror("تعذرت قراءة العناوين",str(exc),parent=self)

    def accept(self):
        try:
            if self.sheet_var.get()!=self.loaded_sheet or int(self.header_var.get())!=self.loaded_header:raise ValueError("اضغط قراءة العناوين بعد تغيير الشيت أو صف العناوين")
            mapping={k:self.column_options[v.get()] for k,v in self.variables.items()}
            if mapping.get("number") is None:raise ValueError("حدد عمود رقم المستند")
            first=int(self.start_var.get())
            if first<=self.loaded_header:raise ValueError("أول صف بيانات يجب أن يكون بعد صف العناوين")
            mapping.update(sheet=self.loaded_sheet,header_row=self.loaded_header,data_start_row=first)
            self.result=mapping;self.destroy()
        except Exception as exc:messagebox.showerror("راجع الاختيارات",str(exc),parent=self)


class App(tk.Tk):
    def __init__(self, data_dir):
        super().__init__()
        self.title("DC Assistant - مساعد ضبط المستندات")
        self.geometry("1260x780");self.minsize(1000,650)
        style=ttk.Style(self);style.theme_use("clam")
        style.configure(".",font=("Segoe UI",10))
        style.configure("TButton",padding=(12,8));style.configure("Treeview",rowheight=29)
        self.store=Store(Path(data_dir)/"dc-assistant.sqlite3")
        self.project=None;self.results=None;self.results_settings=None;self.busy=False;self.events=queue.Queue()
        self.protocol("WM_DELETE_WINDOW",self.close)
        self.container=ttk.Frame(self,padding=18);self.container.pack(fill="both",expand=True)
        self.show_home();self.after(100,self.poll)

    def clear(self):
        for child in self.container.winfo_children():child.destroy()

    def show_home(self):
        if self.busy:return
        self.clear()
        ttk.Label(self.container,text="هتشتغل على أنهي مشروع؟",font=("Segoe UI",24),anchor="e").pack(fill="x",pady=(35,35))
        choices=ttk.Frame(self.container);choices.pack(pady=20)
        ttk.Button(choices,text="مشروع مسجل",width=30,command=self.choose_existing).grid(row=0,column=1,padx=20,ipady=25)
        ttk.Button(choices,text="مشروع جديد",width=30,command=self.new_project).grid(row=0,column=0,padx=20,ipady=25)
        ttk.Label(self.container,text=f"مكان حفظ بيانات البرنامج: {self.store.path}",anchor="e").pack(side="bottom",fill="x")

    def new_project(self):
        dlg=ProjectDialog(self);self.wait_window(dlg)
        if dlg.result:self.open_project(dlg.result)

    def choose_existing(self):
        projects=self.store.projects()
        if not projects:
            messagebox.showinfo("المشاريع","لا توجد مشاريع مسجلة. أضف مشروعًا جديدًا.",parent=self);return
        dlg=tk.Toplevel(self);dlg.title("المشاريع المسجلة");dlg.geometry("650x210");dlg.transient(self);dlg.grab_set()
        labels=[p["name"]+(" — "+p["code"] if p["code"] else "") for p in projects]
        value=tk.StringVar(value=labels[0]);ttk.Label(dlg,text="اختار المشروع").pack(pady=15)
        combo=ttk.Combobox(dlg,textvariable=value,values=labels,state="readonly",width=65);combo.pack(padx=20,pady=5)
        def choose():
            i=combo.current();dlg.destroy();self.open_project(projects[i]["id"])
        ttk.Button(dlg,text="فتح المشروع",command=choose).pack(pady=18)

    def open_project(self, project_id):
        self.project=self.store.get_project(project_id);self.results=None;self.results_settings=None
        self.show_workspace()

    def show_workspace(self):
        self.clear()
        header=ttk.Frame(self.container);header.pack(fill="x")
        ttk.Button(header,text="تغيير المشروع",command=self.show_home).pack(side="left")
        ttk.Label(header,text=self.project["name"]+"  |  "+self.project["code"],font=("Segoe UI",18),anchor="e").pack(side="right")
        tools=ttk.Frame(self.container);tools.pack(fill="x",pady=16)
        self.action_buttons=[]
        for text,command in [("إعدادات المشروع",self.edit_project),("استيراد لوج Excel",self.import_register),("فحص دفعة ملفات",self.start_scan),("دفعات سابقة",self.history),("تصدير Excel",self.export),("فتح الملف المحدد",self.open_selected)]:
            button=ttk.Button(tools,text=text,command=command);button.pack(side="right",padx=4);self.action_buttons.append(button)
        self.pdf_var=tk.BooleanVar(value=True)
        ttk.Checkbutton(self.container,text="قراءة رقم اللوحة والإصدار من نص أول صفحة PDF",variable=self.pdf_var).pack(anchor="e")
        reg=self.store.get_register(self.project["id"])
        self.info_var=tk.StringVar(value=f"اللوج المستورد: {len(reg['records'])} سجل — {reg['mapping']['sheet']}" if reg else "لم يُستورد لوج لهذا المشروع بعد")
        ttk.Label(self.container,textvariable=self.info_var,anchor="e").pack(fill="x",pady=8)
        columns=("issues","status","revision","number","file")
        grid=ttk.Frame(self.container);grid.pack(fill="both",expand=True)
        self.tree=ttk.Treeview(grid,columns=columns,show="headings",selectmode="browse")
        for key,title,width in [("issues","الملاحظات",330),("status","الحالة من اللوج",100),("revision","الإصدار",70),("number","رقم المستند",330),("file","اسم الملف",350)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width,minwidth=60,anchor="e")
        vs=ttk.Scrollbar(grid,orient="vertical",command=self.tree.yview);hs=ttk.Scrollbar(grid,orient="horizontal",command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
        self.tree.grid(row=0,column=0,sticky="nsew");vs.grid(row=0,column=1,sticky="ns");hs.grid(row=1,column=0,sticky="ew")
        grid.rowconfigure(0,weight=1);grid.columnconfigure(0,weight=1)
        self.progress=ttk.Progressbar(self.container,mode="determinate");self.progress.pack(fill="x",pady=(10,4))
        self.status_var=tk.StringVar(value="اختار اللوج أو دفعة الملفات للبدء")
        ttk.Label(self.container,textvariable=self.status_var,anchor="e").pack(fill="x")
        self.tree.bind("<Double-1>",lambda e:self.show_detail())

    def edit_project(self):
        dlg=ProjectDialog(self,self.project);self.wait_window(dlg)
        if dlg.result:self.open_project(dlg.result)

    def import_register(self):
        path=filedialog.askopenfilename(parent=self,title="اختار ملف اللوج",filetypes=[("Excel","*.xlsx")])
        if not path:return
        try:
            dlg=RegisterDialog(self,path);self.wait_window(dlg)
            if not dlg.result:return
            records,warnings=read_register(path,dlg.result)
            if warnings:raise ValueError("\n".join(warnings))
            self.store.save_register(self.project["id"],path,dlg.result,records)
            self.results=None;self.results_settings=None
            self.tree.delete(*self.tree.get_children())
            self.progress.configure(value=0)
            self.info_var.set(f"اللوج المستورد: {len(records)} سجل — {dlg.result['sheet']}")
            self.status_var.set("تم استيراد اللوج. افحص الدفعة مجددًا لعرض نتائج مرتبطة بهذه النسخة.")
        except Exception as exc:messagebox.showerror("تعذر الاستيراد",str(exc),parent=self)

    def start_scan(self):
        try:NamingRule(self.project["settings"])
        except ValueError as exc:messagebox.showinfo("قواعد التسمية",str(exc),parent=self);self.edit_project();return
        folder=filedialog.askdirectory(parent=self,title="فولدر الدفعة المراد فحصها")
        if not folder:return
        reg=self.store.get_register(self.project["id"])
        records=reg["records"] if reg else []
        settings=json.loads(json.dumps(self.project["settings"]))
        project_id=self.project["id"]
        context={"project_name":self.project["name"],"project_code":self.project["code"],"folder":folder,"register_source":reg["source"] if reg else ""}
        check_pdf=self.pdf_var.get()
        self.busy=True
        for button in self.action_buttons:button.configure(state="disabled")
        self.status_var.set("جارٍ حصر الملفات...")
        def worker():
            try:
                def progress(n,total,name):self.events.put(("progress",(n,total,name)))
                results=scan_batch(folder,settings,records,check_pdf,progress)
                results["context"]=context
                self.events.put(("done",(project_id,folder,settings,results)))
            except Exception as exc:self.events.put(("error",str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        try:
            for _ in range(100):
                kind,data=self.events.get_nowait()
                if kind=="progress":
                    n,total,name=data;self.progress.configure(maximum=max(total,1),value=n);self.status_var.set(f"{n}/{total} — {name}")
                elif kind=="done":
                    project_id,folder,settings,results=data
                    self.set_busy(False);self.display(results,settings)
                    try:self.store.save_batch(project_id,folder,settings,results)
                    except Exception as exc:messagebox.showerror("لم يُحفظ سجل الدفعة",f"النتيجة متاحة للتصدير الآن. تعذر حفظها في قاعدة البيانات:\n{exc}",parent=self)
                elif kind=="error":self.set_busy(False);messagebox.showerror("تعذر الفحص",data,parent=self)
        except queue.Empty:pass
        self.after(100,self.poll)

    def set_busy(self,value):
        self.busy=value
        for button in self.action_buttons:button.configure(state="disabled" if value else "normal")

    def display(self,results,settings=None):
        self.results=results
        self.results_settings=settings or self.project["settings"]
        if "register_source" in results.get("context",{}):
            source=results["context"]["register_source"]
            self.info_var.set("اللوج وقت هذه النتيجة: "+source if source else "هذه النتيجة أُنشئت دون لوج مستورد")
        self.tree.delete(*self.tree.get_children())
        for i,r in enumerate(results["items"]):self.tree.insert("","end",iid=str(i),values=("؛ ".join(r["issues"]),r["status"],r["revision"],r["number"],r["file"]))
        s=results["summary"]
        self.status_var.set(f"{s['files']} ملف | PDF: {s['pdf']} | DWG: {s['dwg']} | إضافية: {s.get('attachments',0)} | لها ملاحظات: {s['with_observations']} | سجلات دون PDF مطابق: {len(results['register_not_in_batch'])}")

    def selected(self):
        selection=self.tree.selection()
        return self.results["items"][int(selection[0])] if selection and self.results else None

    def open_selected(self):
        item=self.selected()
        if not item:return
        path=Path(item["path"])
        if not path.is_file():messagebox.showerror("الملف غير موجود",str(path),parent=self);return
        try:os.startfile(str(path))
        except OSError as exc:messagebox.showerror("تعذر فتح الملف",str(exc),parent=self)

    def show_detail(self):
        item=self.selected()
        if item:messagebox.showinfo("تفاصيل الملف",f"{item['path']}\n\nفحص PDF: {item['pdf_check']}\n\n"+"\n".join(item["issues"]),parent=self)

    def history(self):
        batches=self.store.batches(self.project["id"])
        if not batches:messagebox.showinfo("الدفعات","لم تُفحص دفعات لهذا المشروع بعد.",parent=self);return
        dlg=tk.Toplevel(self);dlg.title("دفعات المشروع السابقة");dlg.geometry("950x430");dlg.transient(self);dlg.grab_set()
        items=tk.Listbox(dlg,font=("Segoe UI",11));items.pack(fill="both",expand=True,padx=14,pady=14)
        for batch in batches:items.insert("end",batch["created"][:19]+" — "+batch["folder"])
        def choose():
            selected=items.curselection()
            if selected:
                batch=self.store.get_batch(self.project["id"],batches[selected[0]]["id"]);dlg.destroy();self.display(batch["results"],batch["settings"])
        ttk.Button(dlg,text="عرض النتائج",command=choose).pack(pady=10)

    def export(self):
        if not self.results:messagebox.showinfo("التصدير","افحص دفعة أو افتح نتائج دفعة سابقة أولًا.",parent=self);return
        path=filedialog.asksaveasfilename(parent=self,title="حفظ تقرير المطابقة",defaultextension=".xlsx",filetypes=[("Excel","*.xlsx")],initialfile="DC-Matching-Report.xlsx")
        if not path:return
        try:
            export_results(path,{**self.project,"settings":self.results_settings},self.results);messagebox.showinfo("تم التصدير",path,parent=self)
        except Exception as exc:messagebox.showerror("تعذر التصدير",str(exc),parent=self)

    def close(self):
        if self.busy and not messagebox.askyesno("الفحص مستمر","إغلاق البرنامج وإلغاء حفظ نتيجة الفحص الحالي؟",parent=self):return
        self.store.close();self.destroy()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-dir",default=str(Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"DCAssistant"))
    parser.add_argument("--self-test-report",default=None)
    args=parser.parse_args()
    if args.self_test_report:
        from .diagnostics import self_test
        raise SystemExit(self_test(args.self_test_report,args.data_dir))
    App(args.data_dir).mainloop()


if __name__=="__main__":main()
