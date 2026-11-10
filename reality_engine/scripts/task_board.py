"""The ticket tracker."""
from __future__ import annotations
import argparse, contextlib, datetime, json, os, re, subprocess, sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[2]
LIVE_RELATIVE = Path("tasks") / "TASKS.md"
DONE_RELATIVE = Path("tasks") / "TASKS_DONE.md"
JSONL_RELATIVE = Path("tasks") / "tickets.jsonl"
LOCK_RELATIVE = Path(".tmp") / "task_board.lock"
SECTIONS = ("Workspace","Data","OCR and extraction","Schema and question map","Bank","Research","Machines")
PRIORITIES = ("P1","P2","P3")
OPEN_STATUSES = ("OPEN","LOOKING","DOING","WAITING")
CARD_LIMIT = 600
STALE_DAYS = 3
ROW_ID = re.compile(r"^T-\d+$")
OPENED = re.compile(r"^opened (\d{4}-\d{2}-\d{2})$")
DONE_MARK = re.compile(r"^done ([0-9a-f]{7,}) (\d{4}-\d{2}-\d{2})$")
DROPPED_MARK = re.compile(r"^dropped \d{4}-\d{2}-\d{2}$")
TICKET_IN_MESSAGE = re.compile(r"\bT-\d+\b")
NO_TICKET_IN_MESSAGE = re.compile(r"(?im)^\s*No-ticket:\s*\S")
RULE_TITLE = re.compile(r"\b(always|never|every worker must)\b", re.I)
class BoardError(Exception): pass
@dataclass
class Row:
    id: str; status: str; priority: str; title: str; accept: str; source: str; opened: str
    tail: str = ""; section: str = ""; why: str = ""; close_when: str = ""; owner: str = ""
    links: list[str] = field(default_factory=list); history: list[dict[str, Any]] = field(default_factory=list)
    @property
    def word(self) -> str: return self.status.split(" ",1)[0].upper()
    @property
    def resolved_owner(self) -> str:
        if self.owner.strip(): return self.owner.strip()
        return self.status.split(" ",1)[1].strip() if " " in self.status else ""
    def line(self) -> str:
        return (f"- {self.id} | {self.status} | {self.priority} | {self.title} | "
                f"accept: {self.accept} | from: {self.source} | opened {self.opened}"
                + (f" | {self.tail}" if self.tail else ""))
    def to_json(self) -> dict[str, Any]:
        return {"id":self.id,"status":self.status,"priority":self.priority,"title":self.title,
                "accept":self.accept,"source":self.source,"opened":self.opened,"tail":self.tail,
                "section":self.section,"why":self.why,"close_when":self.close_when,"owner":self.owner,
                "links":list(self.links),"history":list(self.history)}
    @classmethod
    def from_json(cls, obj): 
        return cls(id=obj["id"],status=obj["status"],priority=obj["priority"],title=obj["title"],
                   accept=obj["accept"],source=obj.get("source",""),opened=obj["opened"],
                   tail=obj.get("tail",""),section=obj.get("section",""),why=obj.get("why",""),
                   close_when=obj.get("close_when",""),owner=obj.get("owner",""),
                   links=list(obj.get("links") or []),history=list(obj.get("history") or []))
    @property
    def last_change(self) -> str:
        if self.history: return str(self.history[-1].get("when","") or self.opened)
        return self.opened
def _today() -> str: return datetime.date.today().isoformat()
def _path(root, relative): return Path(root)/relative if root is not None else ROOT/relative
def _read(path):
    try: return path.read_text(encoding="utf-8",errors="replace")
    except OSError as exc: raise BoardError(f"{path} cannot be read: {exc}") from exc
def _plain(value,name):
    text=(value or "").strip()
    if not text: raise BoardError(f"{name} must not be empty")
    if "|" in text: raise BoardError(f"{name} must not contain '|': pipes separate the row fields")
    if "\n" in text or "\r" in text: raise BoardError(f"{name} must be one line")
    return text
def _jsonl_path(root): return _path(root, JSONL_RELATIVE)
def _looks_like_rule(title): return bool(RULE_TITLE.search(title or ""))
def _valid_accept(accept, root):
    a=(accept or "").strip(); low=a.lower()
    if low.startswith("shivam"): return True
    if not a: return False
    if not any(tok in low for tok in ("python","pytest","npm","cargo","go ","make","sh ","bash")): return False
    for token in a.split():
        tok=token.strip("\"'")
        if tok.endswith(".py"):
            p=Path(tok)
            if not p.is_absolute(): p=(_path(root,Path(".")) if root is not None else ROOT)/tok
            if not p.exists(): return False
    return True
def parse_row(line, *, done_file=False):
    body=line[2:] if line.startswith("- ") else line
    parts=[p.strip() for p in body.split(" | ")]
    if len(parts) not in (7,8): raise BoardError(f"expected 7 fields, found {len(parts)}")
    row_id,status,priority,title,accept,source,opened=parts[:7]
    if not ROW_ID.match(row_id): raise BoardError(f"id {row_id!r} is not T-<digits>")
    if priority not in PRIORITIES: raise BoardError(f"priority {priority!r} invalid")
    if not title: raise BoardError("title is empty")
    if not accept.startswith("accept: ") or not accept[8:].strip(): raise BoardError("accept field")
    if not source.startswith("from: ") or not source[6:].strip(): raise BoardError("from field")
    if not OPENED.match(opened): raise BoardError("opened field")
    word,_,owner=status.partition(" ")
    if done_file:
        if word not in ("DONE","DROPPED"): raise BoardError("done-file row")
    elif word in ("OPEN","LOOKING") and not owner: pass
    elif word in ("DOING","WAITING") and owner: pass
    elif (word=="DONE" and not owner) or (word=="DROPPED" and owner): pass
    else: raise BoardError("status invalid")
    tail=parts[7] if len(parts)==8 else ""
    if tail and not (DONE_MARK.match(tail) or DROPPED_MARK.match(tail)): raise BoardError("tail")
    opened_match=OPENED.match(opened)
    assert opened_match is not None
    return Row(row_id,status,priority,title,accept[8:].strip(),source[6:].strip(),opened_match.group(1),tail)
def _load_legacy(root):
    live=[]; section=""
    lp=_path(root,LIVE_RELATIVE)
    if not lp.exists():
        raise BoardError(f"{LIVE_RELATIVE} cannot be read: missing")
    for number,line in enumerate(_read(lp).splitlines(),1):
        if line.startswith("## "): section=line[3:].strip(); continue
        if line.startswith("- "):
            try: row=parse_row(line)
            except BoardError as exc: raise BoardError(f"{LIVE_RELATIVE}:{number}: malformed row ({exc})") from exc
            if not section: raise BoardError(f"{LIVE_RELATIVE}:{number}: row outside section")
            row.section=section; live.append(row)
    done=[]
    dp=_path(root,DONE_RELATIVE)
    if dp.exists():
        for number,line in enumerate(_read(dp).splitlines(),1):
            if line.startswith("- "):
                try: done.append(parse_row(line,done_file=True))
                except BoardError as exc: raise BoardError(f"{DONE_RELATIVE}:{number}: malformed row ({exc})") from exc
    return live,done
def _load_all(root):
    jp=_jsonl_path(root)
    if jp.exists():
        rows=[]
        for line in jp.read_text(encoding="utf-8").splitlines():
            line=line.strip()
            if line: rows.append(Row.from_json(json.loads(line)))
        return rows
    live,done=_load_legacy(root)
    return live+done
def load_rows(root=None):
    if _jsonl_path(root).exists():
        allr=_load_all(root)
        return [r for r in allr if r.word not in ("DONE","DROPPED")],[r for r in allr if r.word in ("DONE","DROPPED")]
    return _load_legacy(root)
def _save_all(root,rows):
    jp=_jsonl_path(root); jp.parent.mkdir(parents=True,exist_ok=True)
    jp.write_text("".join(json.dumps(r.to_json(),ensure_ascii=False)+"\n" for r in rows),encoding="utf-8")
    live=[r for r in rows if r.word not in ("DONE","DROPPED")]
    done=[r for r in rows if r.word in ("DONE","DROPPED")]
    _regenerate_markdown(root,live,done)
def _regenerate_markdown(root,live,done):
    by_section={s:[] for s in SECTIONS}
    for r in live:
        sec=r.section if r.section in by_section else "Workspace"
        by_section.setdefault(sec,[]).append(r)
    lines=["# Tickets","","One row per line, kept in its section.",""]
    for section in SECTIONS:
        lines.extend([f"## {section}",""])
        for r in by_section.get(section,[]): lines.append(r.line())
        lines.append("")
    _path(root,LIVE_RELATIVE).write_text("\n".join(lines),encoding="utf-8")
    done_lines=["# Done tickets"]
    for r in done: done_lines.append(r.line())
    _path(root,DONE_RELATIVE).write_text("\n".join(done_lines)+"\n",encoding="utf-8")
def lint_problems(root=None, include_advisory=True):
    """Board defects. Structural ones (duplicates, closed rows left live, missing close marks) block a
    commit through doc_gate; advisory ones (missing why/close_when, non-runnable accept, rule-like title,
    stale DOING/OPEN) are reported by `lint` but never block, so legacy rows can be backfilled gradually."""
    problems=[]
    try: live,done=load_rows(root)
    except BoardError as exc: return [str(exc)]
    seen={}
    for row,where in [(r,LIVE_RELATIVE.as_posix()) for r in live]+[(r,DONE_RELATIVE.as_posix()) for r in done]:
        if row.id in seen: problems.append(f"{row.id} appears in both {seen[row.id]} and {where}")
        else: seen[row.id]=where
    for row in live:
        if row.word in ("DONE","DROPPED"): problems.append(f"{row.id} is {row.word} in {LIVE_RELATIVE}; move it to {DONE_RELATIVE}")
    for row in done:
        if row.word=="DONE" and not DONE_MARK.match(row.tail): problems.append(f"{row.id} is DONE with no commit hash")
        if row.word=="DROPPED" and row.status.strip()=="DROPPED": problems.append(f"{row.id} is DROPPED with no reason")
    if not include_advisory:
        return problems
    for row in live+done:
        if not row.why or len(row.why)<30: problems.append(f"{row.id} missing why (>=30 chars)")
        if not row.close_when: problems.append(f"{row.id} missing close_when")
        if not _valid_accept(row.accept,root): problems.append(f"{row.id} accept not runnable: {row.accept}")
        if _looks_like_rule(row.title): problems.append(f"{row.id} title reads as a rule (use ruling add)")
    today=datetime.date.today()
    for row in live:
        age=None
        try: age=(today-datetime.date.fromisoformat(row.last_change)).days
        except ValueError: age=None
        if row.word=="DOING" and age is not None and age>=1: problems.append(f"{row.id} DOING owned by a session not seen for 24h")
        if row.word=="OPEN" and age is not None and age>=7: problems.append(f"{row.id} OPEN with no activity for 7 days")
    return problems
@contextlib.contextmanager
def file_lock(root=None):
    path=_path(root,LOCK_RELATIVE); path.parent.mkdir(parents=True,exist_ok=True)
    with open(path,"a+b") as handle:
        if os.name=="nt":
            import msvcrt
            if handle.seek(0,os.SEEK_END)==0:
                handle.write(b"x"); handle.flush()
            handle.seek(0); msvcrt.locking(handle.fileno(),msvcrt.LK_LOCK,1)
            try: yield
            finally:
                handle.seek(0); msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
def _next_id(live,done):
    highest=max((int(row.id[2:]) for row in live+done),default=0)
    return f"T-{highest+1:03d}"
def add(*,section,title,accept,source="manual",priority="P2",status="OPEN",root=None,
        why="",close_when="",owner="",links=None,history=None,allow_rule_title=False):
    section=_plain(section,"section"); title=_plain(title,"title"); accept=_plain(accept,"accept")
    source=_plain(source,"from"); priority=_plain(priority,"priority")
    if section not in SECTIONS: raise BoardError(f"section must be one of {', '.join(SECTIONS)}")
    if priority not in PRIORITIES: raise BoardError(f"priority must be one of {', '.join(PRIORITIES)}")
    if len(why.strip())<30: raise BoardError("why must be at least 30 characters: name the failure or request that opened it")
    if not close_when.strip(): raise BoardError("close_when must not be empty: name the check that closes it")
    if not _valid_accept(accept,root): raise BoardError(f"accept is not runnable: {accept}")
    if _looks_like_rule(title) and not allow_rule_title: raise BoardError("title reads as a rule; use 'ruling add'")
    close_when=_plain(close_when,"close_when"); why=why.strip()
    status=" ".join(_plain(status,"status").split())
    word,_,st_owner=status.partition(" ")
    if word.upper() not in OPEN_STATUSES or (word.upper() in ("DOING","WAITING") and not (st_owner or owner)):
        raise BoardError("status invalid")
    status=word.upper()+(f" {st_owner or owner}" if (st_owner or owner) else "")
    if word.upper() in ("DOING","WAITING") and not owner: owner=st_owner
    if links is None: links=[]
    if history is None: history=[{"when":_today(),"who":"system","from":"","to":status,"reason":"opened"}]
    with file_lock(root):
        rows=_load_all(root)
        live=[r for r in rows if r.word not in ("DONE","DROPPED")]
        done=[r for r in rows if r.word in ("DONE","DROPPED")]
        row=Row(_next_id(live,done),status,priority,title,accept,source,_today(),
                section=section,why=why,close_when=close_when,owner=owner,links=links,history=history)
        rows.append(row); _save_all(root,rows)
    return row.id
def _find(rows,row_id):
    for row in rows:
        if row.id==row_id and row.word not in ("DONE","DROPPED"): return row
    raise BoardError(f"{row_id} is not an open row")
def set_status(row_id,status,owner=None,reason=None,root=None):
    word=status.strip().upper()
    if word not in OPEN_STATUSES: raise BoardError(f"status must be one of {', '.join(OPEN_STATUSES)}")
    if word in ("DOING","WAITING") and not (owner or "").strip(): raise BoardError(f"{word} needs owner")
    if word not in ("DOING","WAITING") and (owner or "").strip(): raise BoardError(f"{word} takes no owner")
    new=word+(f" {_plain(owner,'owner')}" if (owner or "").strip() else "")
    with file_lock(root):
        rows=_load_all(root); row=_find(rows,row_id); old=row.status; row.status=new
        row.owner=(owner or "").strip() if word in ("DOING","WAITING") else ""
        row.history.append({"when":_today(),"who":(owner or "system").strip() or "system","from":old,"to":new,"reason":reason or "status changed"})
        _save_all(root,rows)
def _head(root): 
    out=_git(root,"rev-parse","--short","HEAD"); return out.strip() or "0000000"
def _git(root,*args):
    try:
        c=subprocess.run(["git","-C",str(root or ROOT),*args],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=10)
    except (OSError,subprocess.SubprocessError): return ""
    return c.stdout if c.returncode==0 else ""
def done(row_id,*,shivam=False,timeout=900.0,root=None):
    rows=_load_all(root); row=_find(rows,row_id)
    if row.accept.strip().lower().startswith("shivam"):
        if not shivam: raise BoardError(f"{row_id} closes only with 'done {row_id} --shivam'")
    else:
        try:
            result=subprocess.run(row.accept,shell=True,cwd=str(root or ROOT),capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout)
        except subprocess.TimeoutExpired as exc: raise BoardError(f"{row_id} accept timed out") from exc
        except OSError as exc: raise BoardError(f"{row_id} accept could not run: {exc}") from exc
        if result.returncode!=0:
            tail=(result.stdout+result.stderr).strip().splitlines()[-20:]
            raise BoardError(f"{row_id} accept exited {result.returncode}:\n"+"\n".join(tail))
    with file_lock(root):
        rows=_load_all(root); row=_find(rows,row_id); old=row.status
        row.status="DONE"; row.tail=f"done {_head(root)} {_today()}"
        row.history.append({"when":_today(),"who":"Shivam" if shivam else "accept","from":old,"to":"DONE","reason":"Shivam sign-off" if shivam else "accept passed"})
        _save_all(root,rows)
    return row_id
def close(row_id,*,merged=None,root=None):
    if not merged: raise BoardError("close requires --merged <commit>")
    merged=merged.strip()
    with file_lock(root):
        rows=_load_all(root); row=_find(rows,row_id); old=row.status
        row.status="DONE"; row.tail=f"done {merged} {_today()}"
        row.history.append({"when":_today(),"who":"merge","from":old,"to":"DONE","reason":f"merged {merged}"})
        _save_all(root,rows)
    return row_id
def drop(row_id,reason,root=None):
    reason=_plain(reason,"reason")
    with file_lock(root):
        rows=_load_all(root); row=_find(rows,row_id); old=row.status
        row.status=f"DROPPED {reason}"; row.tail=f"dropped {_today()}"
        row.history.append({"when":_today(),"who":"system","from":old,"to":row.status,"reason":reason})
        _save_all(root,rows)
def _untracked_commits(root):
    last=_git(root,"log","-1","--format=%H","--",LIVE_RELATIVE.as_posix(),DONE_RELATIVE.as_posix()).strip()
    if not last: return 0
    messages=[m for m in _git(root,"log","--format=%B%x00",f"{last}..HEAD").split("\x00") if m.strip()]
    return sum(1 for m in messages if not TICKET_IN_MESSAGE.search(m) and not NO_TICKET_IN_MESSAGE.search(m))
def _clip(text,limit): return text if len(text)<=limit else text[:limit-3]+"..."
def card(root=None):
    try:
        live,_=load_rows(root)
        counts=", ".join(f"{name} {sum(1 for row in live if row.section==name)}" for name in SECTIONS)
        lines=[_clip(f"OPEN {len(live)}: {counts}",150)]
        doing=[row for row in live if row.word=="DOING"]
        if doing: lines.append(_clip("DOING: "+", ".join(f"{row.id} {row.title}" for row in doing),90))
        waiting=[row for row in live if row.word=="WAITING" and row.resolved_owner.lower()=="shivam"]
        if waiting: lines.append(_clip("WAITING Shivam: "+", ".join(row.id for row in waiting),90))
    except BoardError as exc: return _clip(f"task card unavailable: {exc}",CARD_LIMIT)
    today=datetime.date.today(); stale=[]
    for row in live:
        try: age=(today-datetime.date.fromisoformat(row.opened)).days
        except ValueError: continue
        if age>STALE_DAYS: stale.append(row.id)
    if stale: lines.append(_clip("Stale >3d: "+", ".join(stale),90))
    untracked=_untracked_commits(root)
    if untracked: lines.append(_clip(f"Commits with no ticket since tracker change: {untracked}",90))
    lines.append("More: python -m reality_engine.scripts.task_board list")
    return "\n".join(lines)[:CARD_LIMIT]
def export(path,root=None):
    from openpyxl import Workbook
    live,done=load_rows(root)
    wb=Workbook(); sheet=wb.active; assert sheet is not None; sheet.title="Tickets"
    sheet.append(["id","status","priority","title","accept","from","opened","closing","section","file","why","close_when","owner","last_change","links"])
    for row in live:
        sheet.append([row.id,row.status,row.priority,row.title,row.accept,row.source,row.opened,row.tail,row.section,LIVE_RELATIVE.as_posix(),row.why,row.close_when,row.resolved_owner,row.last_change,", ".join(row.links)])
    for row in done:
        sheet.append([row.id,row.status,row.priority,row.title,row.accept,row.source,row.opened,row.tail,row.section,DONE_RELATIVE.as_posix(),row.why,row.close_when,row.resolved_owner,row.last_change,", ".join(row.links)])
    wb.save(path); return len(live)+len(done)
def _parser():
    parser=argparse.ArgumentParser(prog="python -m reality_engine.scripts.task_board")
    cmds=parser.add_subparsers(dest="command",required=True)
    addc=cmds.add_parser("add"); 
    addc.add_argument("--section",required=True,choices=SECTIONS)
    addc.add_argument("--title",required=True); addc.add_argument("--accept",required=True)
    addc.add_argument("--why",required=True); addc.add_argument("--close-when",dest="close_when",required=True)
    addc.add_argument("--from",dest="source",default="manual"); addc.add_argument("--priority",default="P2",choices=PRIORITIES)
    addc.add_argument("--status",default="OPEN"); addc.add_argument("--owner",default="")
    addc.add_argument("--links",default="")
    setc=cmds.add_parser("set"); setc.add_argument("id"); setc.add_argument("status"); setc.add_argument("owner",nargs="?"); setc.add_argument("--reason",default=None)
    donec=cmds.add_parser("done"); donec.add_argument("id"); donec.add_argument("--shivam",action="store_true"); donec.add_argument("--timeout",type=float,default=900.0)
    closec=cmds.add_parser("close"); closec.add_argument("id"); closec.add_argument("--merged",required=True)
    dropc=cmds.add_parser("drop"); dropc.add_argument("id"); dropc.add_argument("reason")
    listc=cmds.add_parser("list"); listc.add_argument("--section",choices=SECTIONS); listc.add_argument("--status")
    cmds.add_parser("card")
    exportc=cmds.add_parser("export"); exportc.add_argument("path")
    cmds.add_parser("lint")
    return parser
def main(argv=None):
    args=_parser().parse_args(argv)
    try:
        if args.command=="add":
            links=[x.strip() for x in (args.links or "").split(",") if x.strip()]
            print(add(section=args.section,title=args.title,accept=args.accept,why=args.why,close_when=args.close_when,source=args.source,priority=args.priority,status=args.status,owner=args.owner,links=links))
        elif args.command=="set": set_status(args.id,args.status,args.owner,reason=args.reason)
        elif args.command=="done": done(args.id,shivam=args.shivam,timeout=args.timeout)
        elif args.command=="close": close(args.id,merged=args.merged)
        elif args.command=="drop": drop(args.id,args.reason)
        elif args.command=="list":
            live,done_rows=load_rows()
            for row in live+done_rows:
                if args.section and row.section!=args.section: continue
                if args.status and row.word!=args.status.upper(): continue
                print(row.line())
        elif args.command=="card": print(card())
        elif args.command=="export": print(f"wrote {export(args.path)} rows to {args.path}")
        elif args.command=="lint":
            problems=lint_problems()
            for p in problems: print(p)
            print(f"tracker lint: {len(problems)} problem(s)")
            return 1 if problems else 0
    except BoardError as exc:
        print(f"task_board: {exc}",file=sys.stderr); return 1
    if args.command in ("add","set","done","drop","close"):
        from reality_engine.scripts import ticket_board_report
        ticket_board_report.sync_quietly()
    return 0
if __name__=="__main__": sys.exit(main())
