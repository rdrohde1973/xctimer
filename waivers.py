"""Waivers: district templates + a no-login parent e-sign link, kept per athlete.

Mirrors the 321Draw pattern: a district admin writes a waiver template once; for an
athlete you generate a tokenized public link (no login) emailed to the parent; the
parent reviews the text, types their name + relationship, draws a signature, and
consents. We record name / signature image / timestamp / IP / user-agent and a hash
of the exact text signed, and can render an audit certificate PDF. Medical forms are
intentionally left as a future placeholder (avoiding HIPAA scope for now).
"""
import base64
import hashlib
import io
import os
import secrets
from datetime import datetime, timezone

from markupsafe import escape
from flask import Blueprint, request, redirect, g, abort, jsonify, Response

from . import db, ai
from .auth import login_required, send_email
from .tenancy import active_district_id
from .ui import CSS, BRAND_HTML, HEAD_EXTRA

bp = Blueprint("waivers", __name__)

# Placeholders filled per athlete when a waiver is sent. Shown as a hint to admins.
PLACEHOLDER_HINT = ("{{athlete_name}}, {{school}}, {{grade}}, {{district}}, "
                    "{{date}}, {{parent_name}}")


def _merge(body, athlete, district_name, today):
    """Substitute {{merge fields}} with this athlete's values (used at send time)."""
    repl = {
        "athlete_name": athlete["name"] or "",
        "athlete": athlete["name"] or "",
        "school": athlete["sname"] or "",
        "grade": str(athlete["grade"]) if athlete["grade"] is not None else "",
        "gender": athlete["gender"] or "",
        "district": district_name or "",
        "date": today,
        "parent_name": (athlete["parent_name"] or "____________________"),
    }
    out = body or ""
    for k, v in repl.items():
        out = out.replace("{{" + k + "}}", v).replace("{{ " + k + " }}", v)
    return out


# ------------------------------- helpers -------------------------------
def _district_for(principal):
    """District whose template the principal manages (their own, or the switcher)."""
    if principal.role == "district_admin":
        return principal.district_id
    return active_district_id()


def _active_template(conn, did):
    return conn.execute(
        "SELECT * FROM waiver_templates WHERE district_id=? AND active=1 "
        "ORDER BY id DESC LIMIT 1", (did,)).fetchone()


def _athlete_or_403(conn, aid):
    a = conn.execute(
        "SELECT a.*, s.district_id, s.name AS sname FROM athletes a "
        "JOIN schools s ON s.id=a.school_id WHERE a.id=?", (aid,)).fetchone()
    if not a:
        abort(404)
    p = g.principal
    if not p or p.meet_scope or p.role == "timer":
        abort(403)
    if p.is_super:
        return a
    if p.district_id != a["district_id"]:
        abort(403)
    if p.role == "district_admin":
        return a
    if p.role == "coach" and a["school_id"] in p.school_ids():
        return a
    abort(403)


def _client_ip():
    return (request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr or "")


# ------------------------------- dashboard template card -------------------------------
def dashboard_card(principal):
    """Waiver-template editor embedded on the dashboard (district/super admin)."""
    if principal.role not in ("district_admin", "super_admin"):
        return ""
    did = _district_for(principal)
    if not did:
        return ('<div class="card"><h2>📝 Waiver template</h2>'
                '<p class="muted">Pick a district in the header to set up its waiver.</p></div>')
    conn = db.connect()
    t = _active_template(conn, did)
    signed = conn.execute(
        "SELECT COUNT(*) FROM athlete_waivers w JOIN athletes a ON a.id=w.athlete_id "
        "JOIN schools s ON s.id=a.school_id WHERE s.district_id=? AND w.status='signed'",
        (did,)).fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM athlete_waivers w JOIN athletes a ON a.id=w.athlete_id "
        "JOIN schools s ON s.id=a.school_id WHERE s.district_id=? AND w.status='pending'",
        (did,)).fetchone()[0]
    conn.close()
    title = escape(t["title"]) if t else "Team Participation Waiver"
    body = escape(t["body"]) if t else (
        "Enter your waiver text here. Parents will read this and sign electronically.\n\n"
        "Example: I give permission for my child to participate in cross-country and "
        "track & field, and I release the school district from liability for injuries "
        "sustained during practices and meets…")
    status = (f'<p class="muted">Current template: <b>{escape(t["title"])}</b> · '
              f'{signed} signed · {pending} pending</p>' if t else
              '<p class="muted">No template yet — save one below to start sending waivers.</p>')
    verb = "Update" if t else "Save"
    card = f"""
<div class="card"><h2>📝 Waiver template</h2>
{status}
<div style="background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:.8rem 1rem;margin:.4rem 0 1rem">
  <b>✨ Import from a document</b>
  <p class="muted" style="margin:.3rem 0 .5rem">Upload your existing waiver (PDF, Word, or text) and
  AI turns the athlete-specific bits into fill-in fields for you to review.</p>
  <input type="file" id="wtplfile" accept=".pdf,.docx,.txt,.csv,.tsv">
  <button type="button" onclick="importWaiver()" style="margin-top:.5rem">Import &amp; auto-field</button>
  <span id="wtplmsg" class="muted"></span>
</div>
<form method="post" action="/waivers/template">
  <label>Title</label>
  <input id="wtpl_title" name="title" value="{title}" required>
  <label>Waiver text (parents read &amp; sign this)</label>
  <textarea id="wtpl_body" name="body" rows="10" required style="font:inherit">{body}</textarea>
  <p class="muted" style="margin:.4rem 0">Fields filled in per athlete when a waiver is sent:
  <code>{PLACEHOLDER_HINT}</code></p>
  <button type="submit">{verb} waiver template</button>
  <span class="muted">Saving keeps prior signed waivers intact — new links use the latest text.</span>
</form></div>"""
    script = """
<script>
async function importWaiver(){
  const f=document.getElementById('wtplfile').files[0];
  const msg=document.getElementById('wtplmsg');
  if(!f){ alert('Choose a file first'); return; }
  msg.textContent=' Reading & auto-fielding…';
  const fd=new FormData(); fd.append('file', f);
  try{
    const r=await fetch('/waivers/template/import', {method:'POST', body:fd});
    const j=await r.json(); if(!r.ok) throw new Error(j.error||'Import failed');
    document.getElementById('wtpl_title').value=j.title||'';
    document.getElementById('wtpl_body').value=j.body||'';
    msg.textContent=' Imported — review the {{fields}}, then Save.';
  }catch(e){ msg.textContent=''; alert(e.message); }
}
</script>"""
    return card + script


@bp.post("/waivers/template/import")
@login_required
def import_template():
    """Upload an existing waiver doc; AI returns a template with {{merge fields}}."""
    p = g.principal
    if p.role not in ("district_admin", "super_admin") or not _district_for(p) or p.is_demo:
        abort(403)
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="No file uploaded"), 400
    try:
        text = ai.extract_text(f.filename, f.read())
        tpl = ai.waiver_template_from_text(text)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Could not read that file: {e}"), 400
    if not tpl.get("body"):
        return jsonify(error="Couldn't find waiver text in that file."), 400
    return jsonify(title=tpl["title"], body=tpl["body"])


@bp.post("/waivers/template")
@login_required
def save_template():
    p = g.principal
    did = _district_for(p)
    if p.role not in ("district_admin", "super_admin") or not did or p.is_demo:
        abort(403)
    title = (request.form.get("title") or "Team Waiver").strip()
    body = (request.form.get("body") or "").strip()
    if not body:
        abort(400)
    conn = db.connect()
    conn.execute("UPDATE waiver_templates SET active=0 WHERE district_id=?", (did,))
    conn.execute("INSERT INTO waiver_templates (district_id, title, body, active) VALUES (?,?,?,1)",
                 (did, title, body))
    conn.commit()
    conn.close()
    return redirect("/dashboard")


# ------------------------------- send a waiver -------------------------------
@bp.post("/athletes/<int:aid>/waiver/send")
@login_required
def send_waiver(aid):
    conn = db.connect()
    a = _athlete_or_403(conn, aid)
    if g.principal.is_demo:
        conn.close()
        abort(403)
    t = _active_template(conn, a["district_id"])
    if not t:
        conn.close()
        return jsonify(error="No waiver template yet — a district admin can create one on the dashboard."), 400
    to = (a["parent_email"] or a["email"] or "").strip()
    if not to:
        conn.close()
        return jsonify(error="No parent email on file for this athlete — add one under Edit info first."), 400
    dname = conn.execute("SELECT name FROM districts WHERE id=?",
                         (a["district_id"],)).fetchone()
    today = datetime.now(timezone.utc).date().isoformat()
    body = _merge(t["body"], a, dname["name"] if dname else "", today)
    token = secrets.token_urlsafe(24)
    h = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    conn.execute(
        "INSERT INTO athlete_waivers (athlete_id, template_id, token, status, doc_title, "
        "doc_body, doc_hash, sent_to, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
        (aid, t["id"], token, "pending", t["title"], body, h, to, g.principal.id))
    conn.commit()
    conn.close()
    base = os.environ.get("XC_PUBLIC_URL", request.host_url.rstrip("/"))
    url = f"{base}/waiver/{token}"
    html = (f"<p>Hello,</p><p>Please review and electronically sign the "
            f"<b>{escape(t['title'])}</b> for <b>{escape(a['name'])}</b>.</p>"
            f'<p><a href="{url}">Review &amp; sign the waiver</a> — no account needed.</p>'
            f'<p style="color:#888;font-size:12px">{url}</p>')
    sent = send_email(to, f"Please sign the waiver for {a['name']}", html)
    return jsonify(ok=True, sent=bool(sent), to=to, url=url)


# ------------------------------- public signing page -------------------------------
def _doc_html(body):
    paras = "".join(f"<p>{escape(p)}</p>" for p in (body or "").split("\n") if p.strip())
    return paras or "<p></p>"


@bp.get("/waiver/<token>")
def sign_page(token):
    conn = db.connect()
    w = conn.execute(
        "SELECT w.*, a.name AS aname, s.name AS sname FROM athlete_waivers w "
        "JOIN athletes a ON a.id=w.athlete_id JOIN schools s ON s.id=a.school_id "
        "WHERE w.token=?", (token,)).fetchone()
    conn.close()
    if not w:
        abort(404)
    signed = w["status"] == "signed"
    doc = _doc_html(w["doc_body"])
    if signed:
        inner = (f'<div class="signed">✅ Signed by <b>{escape(w["signer_name"] or "")}</b> '
                 f'({escape(w["signer_relationship"] or "")}) on {escape((w["signed_at"] or "")[:10])}.</div>'
                 f'<p class="muted">Thank you — this waiver is complete. You can close this page.</p>')
    else:
        inner = f"""
<div class="sigwrap">
  <label>Your full name</label>
  <input id="nm" autocomplete="name" placeholder="Parent / guardian name">
  <label>Relationship to athlete</label>
  <input id="rel" placeholder="e.g. Mother, Father, Guardian">
  <div class="med">
    <div class="medh">Medical info <span class="opt">— optional, in case of an injury on meet day</span></div>
    <label>Family physician</label>
    <input id="doc" placeholder="Physician or clinic name">
    <label>Physician phone</label>
    <input id="docph" inputmode="tel" placeholder="Phone">
    <label>Health insurance provider</label>
    <input id="ins" placeholder="Insurance company">
    <label>Policy / member #</label>
    <input id="pol" placeholder="Policy number">
  </div>
  <label>Draw your signature</label>
  <div class="pad"><canvas id="sig" width="600" height="180"></canvas></div>
  <button type="button" class="clear" onclick="clearSig()">Clear signature</button>
  <label class="agree"><input type="checkbox" id="consent">
    I am the parent/guardian of {escape(w['aname'])} and agree that this electronic
    signature has the same legal effect as a handwritten signature.</label>
  <button type="button" id="go" onclick="submitSig()">Sign &amp; submit</button>
  <div id="err" class="err"></div>
</div>"""
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Sign waiver · XCTimer</title>{HEAD_EXTRA}<style>{CSS}
body{{background:var(--bg);color:var(--fg);margin:0;padding:1.2rem;max-width:720px;margin:0 auto}}
.wbrand{{font-size:1.3rem;font-weight:800;margin-bottom:.4rem}}
.doc{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:1.1rem 1.2rem;
  max-height:44vh;overflow:auto;margin:.6rem 0 1.2rem}}
.doc p{{margin:.4rem 0}}
.sigwrap label{{margin-top:.9rem}}
.pad{{background:#fff;border-radius:10px;margin-top:.3rem}}
.pad canvas{{width:100%;height:180px;touch-action:none;display:block}}
.clear{{background:transparent;color:var(--mut);border:1px solid var(--line);margin-top:.5rem}}
.agree{{display:flex;gap:.6rem;align-items:flex-start;margin-top:1rem;font-size:.95rem;color:var(--fg)}}
.agree input{{width:auto;margin-top:.2rem}}
.med{{border:1px solid var(--line);border-radius:10px;padding:.6rem .9rem 1rem;margin-top:1rem}}
.medh{{font-weight:700;margin-bottom:.2rem}}
.opt{{color:var(--mut);font-weight:400;font-size:.9rem}}
#go{{margin-top:1.2rem;width:100%;padding:.9rem;font-size:1.1rem}}
.err{{color:var(--err);margin-top:.6rem}}
.signed{{background:rgba(63,191,127,.12);color:var(--ok);border:1px solid rgba(63,191,127,.3);
  padding:1rem;border-radius:10px;font-size:1.1rem}}
</style></head><body>
<div class="wbrand">{BRAND_HTML}</div>
<h1>{escape(w['doc_title'] or 'Waiver')}</h1>
<p class="sub">{escape(w['aname'])} · {escape(w['sname'])}</p>
<div class="doc">{doc}</div>
{inner}
<script>
const TOKEN={_js(token)};
const c=document.getElementById('sig');
if(c){{
  const ctx=c.getContext('2d'); ctx.lineWidth=2.5; ctx.lineCap='round'; ctx.strokeStyle='#0a2a4a';
  let drawing=false, dirty=false;
  function pos(e){{const r=c.getBoundingClientRect(); const t=e.touches?e.touches[0]:e;
    return [(t.clientX-r.left)*c.width/r.width,(t.clientY-r.top)*c.height/r.height];}}
  function down(e){{drawing=true; dirty=true; const [x,y]=pos(e); ctx.beginPath(); ctx.moveTo(x,y); e.preventDefault();}}
  function move(e){{if(!drawing)return; const [x,y]=pos(e); ctx.lineTo(x,y); ctx.stroke(); e.preventDefault();}}
  function up(){{drawing=false;}}
  c.addEventListener('mousedown',down); c.addEventListener('mousemove',move); window.addEventListener('mouseup',up);
  c.addEventListener('touchstart',down); c.addEventListener('touchmove',move); c.addEventListener('touchend',up);
  window.clearSig=function(){{ctx.clearRect(0,0,c.width,c.height); dirty=false;}};
  window._sigDirty=()=>dirty;
}}
async function submitSig(){{
  const nm=document.getElementById('nm').value.trim();
  const rel=document.getElementById('rel').value.trim();
  const consent=document.getElementById('consent').checked;
  const err=document.getElementById('err');
  if(!nm||!rel){{err.textContent='Please enter your name and relationship.';return;}}
  if(!window._sigDirty||!window._sigDirty()){{err.textContent='Please draw your signature above.';return;}}
  if(!consent){{err.textContent='Please check the consent box to sign.';return;}}
  const sig=document.getElementById('sig').toDataURL('image/png');
  const gv=id=>{{const el=document.getElementById(id);return el?el.value.trim():'';}};
  document.getElementById('go').disabled=true;
  try{{
    const r=await fetch('/waiver/'+TOKEN+'/sign',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{name:nm,relationship:rel,consent:true,signature:sig,
        physician_name:gv('doc'),physician_phone:gv('docph'),
        insurance_provider:gv('ins'),insurance_policy:gv('pol')}})}});
    const j=await r.json(); if(!r.ok) throw new Error(j.error||'Error');
    document.body.innerHTML='<div class="wbrand">{BRAND_HTML}</div>'
      +'<div class="signed" style="margin-top:1rem">✅ Thank you — the waiver for {esc_js(w['aname'])} is signed.</div>';
  }}catch(e){{err.textContent=e.message; document.getElementById('go').disabled=false;}}
}}
</script>
</body></html>"""


@bp.post("/waiver/<token>/sign")
def sign_submit(token):
    conn = db.connect()
    w = conn.execute("SELECT * FROM athlete_waivers WHERE token=?", (token,)).fetchone()
    if not w:
        conn.close()
        abort(404)
    if w["status"] == "signed":
        conn.close()
        return jsonify(error="This waiver has already been signed."), 400
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    rel = (data.get("relationship") or "").strip()
    if not name or not rel or not data.get("consent"):
        conn.close()
        return jsonify(error="Name, relationship, and consent are required."), 400
    sig_path = None
    sig = data.get("signature") or ""
    if sig.startswith("data:image/png;base64,"):
        try:
            raw = base64.b64decode(sig.split(",", 1)[1])
        except Exception:  # noqa: BLE001
            raw = b""
        if len(raw) > 200:
            d = os.path.join(os.path.dirname(__file__), "static", "signatures")
            os.makedirs(d, exist_ok=True)
            fn = f"waiver_{w['id']}_{secrets.token_hex(4)}.png"
            with open(os.path.join(d, fn), "wb") as f:
                f.write(raw)
            sig_path = f"/static/signatures/{fn}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    med = {k: (str(data.get(k) or "").strip() or None) for k in
           ("physician_name", "physician_phone", "insurance_provider", "insurance_policy")}
    conn.execute(
        "UPDATE athlete_waivers SET status='signed', signer_name=?, signer_relationship=?, "
        "signer_sig_path=?, signed_at=?, signed_ip=?, signed_ua=?, physician_name=?, "
        "physician_phone=?, insurance_provider=?, insurance_policy=? WHERE id=?",
        (name, rel, sig_path, now, _client_ip(), request.headers.get("User-Agent", "")[:300],
         med["physician_name"], med["physician_phone"], med["insurance_provider"],
         med["insurance_policy"], w["id"]))
    conn.commit()
    conn.close()
    if w["sent_to"]:
        send_email(w["sent_to"], "Waiver signed — confirmation",
                   f"<p>Thank you. The waiver was electronically signed by "
                   f"<b>{escape(name)}</b> on {now[:10]}.</p>")
    return jsonify(ok=True)


# ------------------------------- audit certificate PDF -------------------------------
@bp.get("/waiver/<int:wid>/cert.pdf")
@login_required
def cert_pdf(wid):
    conn = db.connect()
    w = conn.execute(
        "SELECT w.*, a.name AS aname FROM athlete_waivers w JOIN athletes a ON a.id=w.athlete_id "
        "WHERE w.id=?", (wid,)).fetchone()
    if not w:
        conn.close()
        abort(404)
    _athlete_or_403(conn, w["athlete_id"])  # access scope
    conn.close()
    if w["status"] != "signed":
        abort(404)
    return Response(_cert_bytes(w), mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="waiver-{wid}.pdf"'})


def _cert_bytes(w):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
                                    HRFlowable)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.8 * inch, bottomMargin=0.8 * inch)
    ss = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8.5, textColor="#555")
    story = [Paragraph(escape(w["doc_title"] or "Waiver"), ss["Title"]),
             Paragraph(f"Athlete: <b>{escape(w['aname'])}</b>", ss["Normal"]),
             Spacer(1, 10), HRFlowable(width="100%", color="#ccc"), Spacer(1, 10)]
    for p in (w["doc_body"] or "").split("\n"):
        if p.strip():
            story.append(Paragraph(escape(p), ss["Normal"]))
            story.append(Spacer(1, 4))
    story += [Spacer(1, 16), HRFlowable(width="100%", color="#ccc"), Spacer(1, 10),
              Paragraph("<b>Electronic signature</b>", ss["Heading3"])]
    sp = w["signer_sig_path"]
    if sp:
        fp = os.path.join(os.path.dirname(__file__), sp.lstrip("/"))
        if os.path.exists(fp):
            try:
                story.append(RLImage(fp, width=2.6 * inch, height=0.78 * inch))
            except Exception:  # noqa: BLE001
                pass
    story += [
        Paragraph(f"Signed by <b>{escape(w['signer_name'] or '')}</b> "
                  f"({escape(w['signer_relationship'] or '')})", ss["Normal"]),
        Spacer(1, 8),
        Paragraph(f"Timestamp (UTC): {escape(w['signed_at'] or '')}<br/>"
                  f"IP address: {escape(w['signed_ip'] or '')}<br/>"
                  f"Document hash: {escape(w['doc_hash'] or '')}<br/>"
                  f"User agent: {escape((w['signed_ua'] or '')[:160])}", small),
    ]
    doc.build(story)
    return buf.getvalue()


# small JS-string escapers for inlining values into the signing page script
def _js(s):
    import json
    return json.dumps(str(s))


def esc_js(s):
    return escape(str(s)).replace("'", "\\'")
