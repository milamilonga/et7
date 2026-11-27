"""Verifica que la app de ET7comparte funciona.

Corre los flujos de servidor (endpoints, autenticación, subida, reportes,
moderación) contra una base de prueba creada desde aula7.sql en la carpeta
temporal, para no tocar la base de datos real.
"""
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from werkzeug.datastructures import MultiDict

BASE = Path(__file__).resolve().parent
TEST_DIR = Path(tempfile.gettempdir()) / "aula7_tests"
TEST_DB = TEST_DIR / "aula7_test_copy.db"
TEST_UPLOAD = TEST_DIR / "aula7_test_uploads"

TEST_DB.parent.mkdir(parents=True, exist_ok=True)
shutil.rmtree(TEST_UPLOAD, ignore_errors=True)
TEST_UPLOAD.mkdir(parents=True, exist_ok=True)
if TEST_DB.exists():
    TEST_DB.unlink()
db_setup = sqlite3.connect(TEST_DB)
db_setup.executescript((BASE / "aula7.sql").read_text(encoding="utf-8"))
db_setup.close()

os.environ["AULA7_DATABASE"] = str(TEST_DB)
os.environ["AULA7_UPLOAD_DIR"] = str(TEST_UPLOAD)
os.environ["AULA7_SECRET_KEY"] = "test-secret-key-aula7"

sys.path.insert(0, str(BASE))

from app import app  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

app.config["TESTING"] = True
client = app.test_client()

PASS = []
FAIL = []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print("  OK   %s" % name)
    else:
        FAIL.append(name)
        print("  FAIL %s  %s" % (name, detail))


def csrf():
    return client.get("/api/session").get_json()["csrf_token"]


def api_json(path, method="GET", data=None, headers=None, json_body=False, content_type=None):
    kwargs = {"headers": dict(headers or {})}
    if data is not None:
        if json_body:
            kwargs["json"] = data
        else:
            kwargs["data"] = data
    if content_type:
        kwargs["content_type"] = content_type
    resp = client.open(path, method=method, **kwargs)
    try:
        body = resp.get_json()
    except Exception:
        body = None
    return resp, body


def main():
    print("== página principal ==")
    resp = client.get("/")
    check("GET / devuelve 200", resp.status_code == 200, str(resp.status_code))
    check("GET / devuelve index.html", b"AULA 7" in resp.data)

    print("== /api/session anónimo ==")
    resp, body = api_json("/api/session")
    check("session 200", resp.status_code == 200)
    check("user es null", isinstance(body, dict) and body.get("user") is None)
    check("csrf_token presente", bool(body.get("csrf_token")))

    resp, _ = api_json("/api/admin/publications")
    check("anónimo no ve moderación (401)", resp.status_code == 401, str(resp.status_code))
    resp, _ = api_json("/api/comments")
    check("anónimo no ve la comunidad (401)", resp.status_code == 401, str(resp.status_code))
    resp, _ = api_json("/api/students")
    check("anónimo no ve los alumnos (401)", resp.status_code == 401, str(resp.status_code))

    print("== /api/catalog ==")
    resp, body = api_json("/api/catalog")
    check("catalog 200", resp.status_code == 200)
    check("years 1..6", [y["number"] for y in body["years"]] == [1, 2, 3, 4, 5, 6])
    year1 = next(y for y in body["years"] if y["number"] == 1)
    year2 = next(y for y in body["years"] if y["number"] == 2)
    divs_year1 = [d for d in body["divisions"] if d["year_id"] == year1["id"]]
    check("el año 1 tiene 6 divisiones", len(divs_year1) == 6, str(len(divs_year1)))
    shift_names = {shift["id"]: shift["name"] for shift in body["shifts"]}
    for year in body["years"]:
        divs = [d for d in body["divisions"] if d["year_id"] == year["id"]]
        check("%dº año tiene todas sus divisiones con turno" % year["number"],
              all(d["shift_id"] in shift_names for d in divs), str(divs))
        morning = sum(1 for d in divs if shift_names.get(d["shift_id"]) == "Mañana")
        afternoon = sum(1 for d in divs if shift_names.get(d["shift_id"]) == "Tarde")
        check("%dº año se reparte mitad Mañana y mitad Tarde" % year["number"],
              morning == afternoon == len(divs) // 2, "mañana=%d tarde=%d total=%d" % (morning, afternoon, len(divs)))
    subjects_year1 = [s for s in body["subjects"] if s["year_id"] == year1["id"]]
    check("Matemática está en 1ro", any(s["name"] == "Matemática" for s in subjects_year1))
    check("turnos Mañana/Tarde", {s["name"] for s in body["shifts"]} == {"Mañana", "Tarde"})
    for year in body["years"]:
        names = [s["name"] for s in body["subjects"] if s["year_id"] == year["id"]]
        check("%dº año tiene al menos 10 materias" % year["number"], len(names) >= 10, str(len(names)))
        check("materias sin repetir en %dº año" % year["number"],
              len(names) == len({name.strip().lower() for name in names}), str(names))
    all_names = {s["name"] for s in body["subjects"]}
    tecnicas = {"Dibujo Técnico", "Informática", "Prácticas Profesionalizantes", "Inglés Técnico"}
    check("materias técnicas de la ET7 presentes", tecnicas <= all_names, str(sorted(tecnicas - all_names)))
    div1_id = divs_year1[0]["id"]
    subject1_id = next(s["id"] for s in subjects_year1 if s["name"] == "Matemática")
    subject2_id = next(s["id"] for s in body["subjects"] if s["year_id"] == year2["id"] and s["name"] == "Matemática")

    print("== /api/publications (vacío, requiere sesión) ==")
    resp, _ = api_json("/api/publications")
    check("publications anónimo -> 401", resp.status_code == 401, str(resp.status_code))
    resp, _ = api_json("/api/login", "POST",
                       {"email": "alumno.et7@gmail.com", "password": "AlumnoET7.2026"},
                       {"X-CSRF-Token": csrf()}, json_body=True)
    check("login del alumno demo para ver el repositorio", resp.status_code == 200, str(resp.status_code))
    resp, body = api_json("/api/publications")
    check("publications 200 con sesión", resp.status_code == 200 and isinstance(body, list), str(resp.status_code))
    check("lista vacía", len(body) == 0)

    print("== datos de prueba en la DB ==")
    db = sqlite3.connect(TEST_DB)
    db.commit()
    db.close()

    print("== usuarios de prueba ==")
    for email, password, role in (
        ("admin.et7@gmail.com", "AdminET7.2026", "admin"),
        ("alumno.et7@gmail.com", "AlumnoET7.2026", "student"),
    ):
        resp, body = api_json("/api/login", "POST",
                              {"email": email, "password": password},
                              {"X-CSRF-Token": csrf()}, json_body=True)
        check("login de prueba %s" % email,
              resp.status_code == 200 and body.get("user", {}).get("role") == role,
              "%s %s" % (resp.status_code, body))
        resp, _ = api_json("/api/logout", "POST", None, {"X-CSRF-Token": csrf()})
        check("logout de prueba %s" % email, resp.status_code == 200, str(resp.status_code))

    def register(email, first_name, policy_accepted=True):
        return api_json("/api/register", "POST", {
            "first_name": first_name, "last_name": "Test", "email": email,
            "password": "1234567890", "year_id": year1["id"], "division_id": div1_id,
            "policy_accepted": policy_accepted,
        }, {"X-CSRF-Token": csrf()}, json_body=True)

    print("== registro (sin código de acceso) ==")
    resp, body = register("luis1.et7@test.local", "Luis")
    check("registro sin código 201", resp.status_code == 201, "%s %s" % (resp.status_code, body))
    user1 = body["user"]
    check("usuario activo", user1["account_status"] == "active")
    check("usuario tipo alumno", user1["role"] == "student")

    resp, body = register("luis2.et7@test.local", "Pilar")
    check("segundo registro 201", resp.status_code == 201, str(resp.status_code))
    user2 = body["user"]

    resp, _ = register("luis1.et7@test.local", "Luis")
    check("registro duplicado -> 409", resp.status_code == 409, str(resp.status_code))

    resp, _ = register("sinpolitica.et7@test.local", "Sin", policy_accepted=False)
    check("registro sin aceptar políticas -> 400", resp.status_code == 400, str(resp.status_code))

    resp, body = register("sinet7@test.local", "SinEt7")
    check("registro sin .et7 en el correo -> 400", resp.status_code == 400, str(resp.status_code))
    check("el error pide incluir .et7",
          ".et7" in str(body.get("error", "")) if isinstance(body, dict) else False, str(body))
    resp, body = register("nuevo.et7@test.local", "Nuevo")
    check("registro con .et7 en el correo -> 201", resp.status_code == 201, str(resp.status_code))
    check("la cuenta creada conserva el correo .et7",
          isinstance(body, dict) and body["user"]["email"] == "nuevo.et7@test.local", str(body))
    resp, _ = api_json("/api/logout", "POST", None, {"X-CSRF-Token": csrf()})
    check("logout tras el registro de prueba", resp.status_code == 200, str(resp.status_code))

    sql_seed = (BASE / "aula7.sql").read_text(encoding="utf-8")
    check("las cuentas de prueba incluyen .et7",
          "admin.et7@gmail.com" in sql_seed and "alumno.et7@gmail.com" in sql_seed)

    print("== login ==")
    resp, body = api_json("/api/login", "POST",
                          {"email": "luis1.et7@test.local", "password": "1234567890"},
                          {"X-CSRF-Token": csrf()}, json_body=True)
    check("login luis1 ok", resp.status_code == 200 and body["user"]["id"] == user1["id"], str(resp.status_code))

    resp, _ = api_json("/api/login", "POST",
                       {"email": "luis1.et7@test.local", "password": "contraseña-mal"},
                       {"X-CSRF-Token": csrf()}, json_body=True)
    check("login sin contraseña -> 401", resp.status_code == 401, str(resp.status_code))

    resp, _ = api_json("/api/login", "POST",
                       {"email": "noexiste@test.local", "password": "1234567890"},
                       {"X-CSRF-Token": csrf()}, json_body=True)
    check("login email desconocido -> 401", resp.status_code == 401, str(resp.status_code))

    print("== subida de material ==")
    pdf_bytes = b"%PDF-1.4\n% un pdf de prueba\n"

    def upload_dict():
        return {
            "file": (io.BytesIO(pdf_bytes), "apuntes.pdf", "application/pdf"),
            "year_id": str(year1["id"]),
            "division_id": str(div1_id),
            "shift_id": "1",
            "subject_id": str(subject1_id),
            "title": "Apuntes completos de Matemática para primer año " * 4,
        }

    resp, _ = api_json("/api/publications", "POST", upload_dict(), None, content_type="multipart/form-data")
    check("POST sin CSRF -> 400", resp.status_code == 400, str(resp.status_code))

    resp, pub = api_json("/api/publications", "POST", upload_dict(), {"X-CSRF-Token": csrf()},
                         content_type="multipart/form-data")
    check("POST subir material -> 201", resp.status_code == 201, "%s %s" % (resp.status_code, pub))
    check("publicación está pendiente", isinstance(pub, dict) and pub["status"] == "pending")
    check("publicación tiene archivo", isinstance(pub, dict) and pub["file_url"].startswith("/api/files/"))
    check("publicación tiene materia", isinstance(pub, dict) and pub["subject"] == "Matemática")
    check("publicación tiene año 1", isinstance(pub, dict) and pub["year"] == 1)
    check("publicación guarda el turno elegido", isinstance(pub, dict) and pub["shift"] == "Mañana", str(pub))
    check("acepta títulos de más de 90 caracteres",
          isinstance(pub, dict) and len(pub["title"]) > 90, str(len(pub.get("title", ""))))
    check("publicación tiene autor Luis T.", isinstance(pub, dict) and pub["author"] == "Luis T.", str(pub))
    pub_id = pub["id"]
    storage_key = pub["file_url"].rsplit("/", 1)[-1]

    duplicate_title_upload = MultiDict(upload_dict().items())
    duplicate_title_upload.add("title", "Un segundo título")
    resp, _ = api_json("/api/publications", "POST", duplicate_title_upload,
                       {"X-CSRF-Token": csrf()}, content_type="multipart/form-data")
    check("se rechazan dos títulos en una publicación -> 400", resp.status_code == 400, str(resp.status_code))

    bad = {"file": (io.BytesIO(b"PK"), "programa.exe"),
           "year_id": str(year1["id"]), "division_id": str(div1_id), "shift_id": "1",
           "subject_id": str(subject1_id)}
    resp, _ = api_json("/api/publications", "POST", bad, {"X-CSRF-Token": csrf()},
                       content_type="multipart/form-data")
    check("extensión .exe rechazada -> 400", resp.status_code == 400, str(resp.status_code))

    resp, _ = api_json("/api/publications", "POST", {
        "file": (io.BytesIO(pdf_bytes), "x.pdf", "application/pdf"),
    }, {"X-CSRF-Token": csrf()}, content_type="multipart/form-data")
    check("faltan campos obligatorios -> 400", resp.status_code == 400, str(resp.status_code))

    resp, _ = api_json("/api/publications", "POST", {
        "file": (io.BytesIO(pdf_bytes), "x.pdf", "application/pdf"),
        "year_id": str(year1["id"]), "division_id": str(div1_id), "shift_id": "1",
        "subject_id": str(subject2_id),
    }, {"X-CSRF-Token": csrf()}, content_type="multipart/form-data")
    check("materia de otro año rechazada -> 400", resp.status_code == 400, str(resp.status_code))

    bad_shift = upload_dict()
    bad_shift["shift_id"] = "999"
    resp, _ = api_json("/api/publications", "POST", bad_shift, {"X-CSRF-Token": csrf()},
                       content_type="multipart/form-data")
    check("turno inexistente rechazado -> 400", resp.status_code == 400, str(resp.status_code))

    wrong_shift = upload_dict()
    wrong_shift["shift_id"] = "2"
    resp, _ = api_json("/api/publications", "POST", wrong_shift, {"X-CSRF-Token": csrf()},
                       content_type="multipart/form-data")
    check("división de otro turno rechazada -> 400", resp.status_code == 400, str(resp.status_code))

    print("== autor no reporta su propia publicación (luis1) ==")
    resp, _ = api_json("/api/publications/%s/reports" % pub_id, "POST", {"reason": "other"},
                       {"X-CSRF-Token": csrf()}, json_body=True)
    check("autor reporta su propia -> 404", resp.status_code == 404, str(resp.status_code))

    print("== descarga como autor (luis1) ==")
    resp = client.get("/api/files/" + storage_key)
    check("autor descarga su material (200)", resp.status_code == 200, str(resp.status_code))
    check("contenido del archivo es el PDF", resp.data == pdf_bytes)

    print("== login alumno 2 (luis2) ==")
    resp, _ = api_json("/api/login", "POST",
                       {"email": "luis2.et7@test.local", "password": "1234567890"},
                       {"X-CSRF-Token": csrf()}, json_body=True)
    check("login luis2 ok", resp.status_code == 200, str(resp.status_code))

    print("== permisos de moderación como alumno ==")
    resp, _ = api_json("/api/admin/publications")
    check("alumno ve moderación -> 403", resp.status_code == 403, str(resp.status_code))

    print("== luis2 no descarga material pendiente ==")
    resp = client.get("/api/files/" + storage_key)
    check("luis2 no descarga (pendiente) -> 404", resp.status_code == 404, str(resp.status_code))

    print("== login y moderación como admin ==")
    db = sqlite3.connect(TEST_DB)
    db.execute("INSERT INTO users (first_name, last_name, email, password_hash, role, account_status) VALUES (?, ?, ?, ?, 'admin', 'active')",
               ("Admin", "Sistema", "admin@test.local", generate_password_hash("adminpassword123")))
    db.commit()
    db.close()
    resp, body = api_json("/api/login", "POST",
                          {"email": "admin@test.local", "password": "adminpassword123"},
                          {"X-CSRF-Token": csrf()}, json_body=True)
    check("login admin ok",
          resp.status_code == 200 and isinstance(body, dict) and body.get("user", {}).get("role") == "admin",
          "%s" % resp.status_code)

    admin_token = csrf()
    resp, body = api_json("/api/admin/publications?status=pending")
    check("1 pendiente", isinstance(body, list) and len(body) == 1, str(body))

    resp, body = api_json("/api/admin/publications/%s" % pub_id, "PATCH", {"status": "approved"},
                          {"X-CSRF-Token": admin_token}, json_body=True)
    check("aprobar publicación -> 200", resp.status_code == 200, "%s %s" % (resp.status_code, body))

    resp, body = api_json("/api/admin/publications?status=pending")
    check("ya no hay pendientes", isinstance(body, list) and len(body) == 0, str(body))

    print("== botón rechazar ==")
    resp, body = api_json("/api/admin/publications?status=rejected")
    check("sin rechazados al inicio", isinstance(body, list) and len(body) == 0, str(body))

    rejected_upload = upload_dict()
    rejected_upload["title"] = "Material de prueba para rechazar"
    resp, rejected_pub = api_json("/api/publications", "POST", rejected_upload,
                                  {"X-CSRF-Token": csrf()}, content_type="multipart/form-data")
    check("subida para rechazar -> 201", resp.status_code == 201, str(resp.status_code))
    rejected_id = rejected_pub["id"]

    resp, body = api_json("/api/admin/publications/%s" % rejected_id, "PATCH",
                          {"status": "rejected", "rejection_reason": "No es material de estudio"},
                          {"X-CSRF-Token": admin_token}, json_body=True)
    check("rechazar publicación -> 200", resp.status_code == 200, "%s %s" % (resp.status_code, body))

    resp, body = api_json("/api/admin/publications?status=rejected")
    rejected = next((p for p in body if p["id"] == rejected_id), None)
    check("el rechazado queda registrado", rejected is not None, str(body))
    check("guarda el motivo del rechazo",
          rejected is not None and rejected.get("rejection_reason") == "No es material de estudio",
          str(rejected))

    resp, body = api_json("/api/publications")
    check("el rechazado no aparece en el repositorio",
          all(p["id"] != rejected_id for p in body), str(body))

    resp, body = api_json("/api/admin/publications?status=pending")
    check("el rechazado sale de pendientes", isinstance(body, list) and len(body) == 0, str(body))

    resp, body = api_json("/api/publications")
    check("repositorio incluye material aprobado",
          any(p["id"] == pub_id for p in body), str(body))

    print("== luis2 descarga el material aprobado ==")
    resp, _ = api_json("/api/login", "POST",
                       {"email": "luis2.et7@test.local", "password": "1234567890"},
                       {"X-CSRF-Token": csrf()}, json_body=True)
    check("relogin luis2 ok", resp.status_code == 200, str(resp.status_code))
    resp = client.get("/api/files/" + storage_key)
    check("luis2 descarga material aprobado (200)", resp.status_code == 200, str(resp.status_code))
    check("contenido correcto", resp.data == pdf_bytes)

    print("== vista previa para cualquier usuario con sesión ==")
    resp = client.get("/api/files/" + storage_key + "/preview")
    check("vista previa del PDF (200)", resp.status_code == 200, str(resp.status_code))
    check("la vista previa muestra el archivo", resp.data == pdf_bytes)
    check("la vista previa no se descarga como adjunto",
          "attachment" not in (resp.headers.get("Content-Disposition") or ""),
          str(resp.headers.get("Content-Disposition")))

    print("== reportes de luis2 ==")
    resp, body = api_json("/api/publications/%s/reports" % pub_id, "POST",
                          {"reason": "not_educational"}, {"X-CSRF-Token": csrf()}, json_body=True)
    check("reporte de alumno 2 -> 201", resp.status_code == 201, "%s %s" % (resp.status_code, body))
    report_id = body.get("id") if isinstance(body, dict) else None

    resp, _ = api_json("/api/publications/%s/reports" % pub_id, "POST",
                       {"reason": "not_educational"}, {"X-CSRF-Token": csrf()}, json_body=True)
    check("segundo reporte mismo alumno -> 409", resp.status_code == 409, str(resp.status_code))

    resp, _ = api_json("/api/publications/%s/reports" % pub_id, "POST",
                       {"reason": "bogus"}, {"X-CSRF-Token": csrf()}, json_body=True)
    check("motivo inválido -> 400", resp.status_code == 400, str(resp.status_code))

    resp, _ = api_json("/api/publications/%s/reports" % pub_id, "POST",
                       {"reason": "other", "details": "x" * 1001}, {"X-CSRF-Token": csrf()}, json_body=True)
    check("detalle de >1000 caracteres -> 400", resp.status_code == 400, str(resp.status_code))

    resp, _ = api_json("/api/publications/999/reports", "POST", {"reason": "other"},
                       {"X-CSRF-Token": csrf()}, json_body=True)
    check("publicación inexistente -> 404", resp.status_code == 404, str(resp.status_code))

    resp, body = api_json("/api/publications/mine")
    check("mi lista como luis2 es vacía", resp.status_code == 200 and isinstance(body, list) and len(body) == 0,
          str(body))

    print("== admin revisa el reporte ==")
    resp, _ = api_json("/api/login", "POST",
                       {"email": "admin@test.local", "password": "adminpassword123"},
                       {"X-CSRF-Token": csrf()}, json_body=True)
    check("relogin admin ok", resp.status_code == 200, str(resp.status_code))
    admin_token = csrf()
    resp, body = api_json("/api/admin/reports")
    check("1 reporte", isinstance(body, list) and len(body) == 1, str(body))
    report = body[0]
    check("reporte con label", report.get("reason_label") == "No relacionado con el estudio", str(report))
    check("reporte con reporter", report.get("reporter_name") == "Pilar T.", str(report))

    resp, body = api_json("/api/admin/reports/%s" % report["id"], "PATCH", {"status": "reviewed"},
                          {"X-CSRF-Token": admin_token}, json_body=True)
    check("marcar reporte revisado -> 200", resp.status_code == 200, str(resp.status_code))

    resp, _ = api_json("/api/admin/reports/%s" % report["id"], "PATCH", {"status": "reviewed"},
                       {"X-CSRF-Token": admin_token}, json_body=True)
    check("reporte ya revisado -> 404", resp.status_code == 404, str(resp.status_code))

    resp, body = api_json("/api/admin/publications?status=all")
    check("admin ve el material aprobado en total",
          any(p["id"] == pub_id and p["status"] == "approved" for p in body), str(body))

    resp = client.get("/api/files/" + storage_key)
    check("admin descarga el material (200)", resp.status_code == 200, str(resp.status_code))

    print("== filtros y errores de API ==")
    resp, _ = api_json("/api/publications?year_id=abc")
    check("year_id inválido -> 400", resp.status_code == 400, str(resp.status_code))

    resp, _ = api_json("/api/publications?limit=abc")
    check("limit inválido -> 400", resp.status_code == 400, str(resp.status_code))

    resp, body = api_json("/api/publications?subject_id=999999")
    check("subject_id inexistente -> 200 []", resp.status_code == 200 and isinstance(body, list) and len(body) == 0,
          str(resp.status_code))

    resp, body = api_json("/api/publications?shift_id=1")
    check("filtro turno Mañana incluye el material", any(p["id"] == pub_id for p in body), str(body))
    resp, body = api_json("/api/publications?shift_id=2")
    check("filtro turno Tarde no incluye el material", all(p["id"] != pub_id for p in body), str(body))

    print("== apuntes compartidos ==")
    resp, _ = api_json("/api/login", "POST",
                       {"email": "luis2.et7@test.local", "password": "1234567890"},
                       {"X-CSRF-Token": csrf()}, json_body=True)
    check("relogin luis2 para ver apuntes compartidos", resp.status_code == 200, str(resp.status_code))
    global_upload = upload_dict()
    global_upload["title"] = "Material de Pilar para apuntes compartidos"
    resp, pilar_pub = api_json("/api/publications", "POST", global_upload,
                               {"X-CSRF-Token": csrf()}, content_type="multipart/form-data")
    check("luis2 sube material -> 201", resp.status_code == 201, str(resp.status_code))
    resp, body = api_json("/api/publications/shared")
    check("lista compartida 200", resp.status_code == 200 and isinstance(body, list), str(resp.status_code))
    ids = {p["id"] for p in body}
    authors = {p["author_id"] for p in body}
    check("lista compartida incluye materiales de ambos usuarios",
          pub_id in ids and pilar_pub["id"] in ids, str(ids))
    check("lista compartida no filtra por autor", len(authors) >= 2, str(authors))
    check("lista compartida trae autor y estado",
          all(p.get("author") and p.get("status") for p in body), str(body))
    resp, body = api_json("/api/publications/mine")
    check("el filtro 'solo las mías' sigue siendo personal",
          resp.status_code == 200 and all(p["author_id"] == user2["id"] for p in body), str(body))

    print("== comunidad: chat de estudiantes ==")
    resp, body = api_json("/api/comments")
    check("GET comentarios 200 con sesión", resp.status_code == 200 and isinstance(body, list),
          "%s %s" % (resp.status_code, type(body)))
    check("hay charlas de ejemplo entre alumnos", len(body) >= 4, str(len(body)))
    check("los mensajes traen autor, texto y fecha",
          all(m.get("author") and m.get("body") and m.get("created_at") for m in body), str(body[:2]))
    check("participan varios estudiantes en el chat",
          len({m["author_id"] for m in body}) >= 2, str({m["author_id"] for m in body}))
    resp, created = api_json("/api/comments", "POST",
                             {"body": "Mensaje de prueba de un alumno."},
                             {"X-CSRF-Token": csrf()}, json_body=True)
    check("un alumno puede enviar un mensaje -> 201", resp.status_code == 201,
          "%s %s" % (resp.status_code, created))
    resp, body = api_json("/api/comments")
    check("el mensaje enviado aparece en la comunidad",
          any(m.get("body") == "Mensaje de prueba de un alumno." for m in body), str(body[-2:]))
    comment_id = created["id"] if isinstance(created, dict) else None
    resp, _ = api_json("/api/comments", "POST", {"body": "   "},
                       {"X-CSRF-Token": csrf()}, json_body=True)
    check("mensaje vacío -> 400", resp.status_code == 400, str(resp.status_code))
    resp, _ = api_json("/api/comments", "POST", {"body": "x" * 501},
                       {"X-CSRF-Token": csrf()}, json_body=True)
    check("mensaje demasiado largo -> 400", resp.status_code == 400, str(resp.status_code))
    resp, _ = api_json("/api/comments/%s" % comment_id, "DELETE", None,
                       {"X-CSRF-Token": csrf()})
    check("un alumno NO puede eliminar mensajes -> 403", resp.status_code == 403, str(resp.status_code))
    resp, students_list = api_json("/api/students")
    victim_id = students_list[0]["id"]
    resp, _ = api_json("/api/students/%s" % victim_id, "DELETE", None,
                       {"X-CSRF-Token": csrf()})
    check("un alumno NO puede eliminar alumnos -> 403", resp.status_code == 403, str(resp.status_code))

    print("== alumnos registrados ==")
    resp, body = api_json("/api/students")
    check("GET alumnos 200 con sesión", resp.status_code == 200 and isinstance(body, list),
          str(resp.status_code))
    check("la lista trae a los alumnos de prueba", len(body) >= 12, str(len(body)))
    check("los alumnos traen nombre, año y estado",
          all(s.get("name") and s.get("status") for s in body), str(body[:2]))
    check("un alumno no ve los correos de los demás",
          all("email" not in s for s in body), str(body[:2]))

    print("== el alumno no puede eliminar publicaciones ==")
    resp, _ = api_json("/api/admin/publications/%s" % pilar_pub["id"], "DELETE", None,
                       {"X-CSRF-Token": csrf()})
    check("un alumno no elimina publicaciones -> 403", resp.status_code == 403, str(resp.status_code))

    print("== el admin elimina publicaciones ==")
    resp, _ = api_json("/api/login", "POST",
                       {"email": "admin@test.local", "password": "adminpassword123"},
                       {"X-CSRF-Token": csrf()}, json_body=True)
    check("relogin admin para moderar publicaciones", resp.status_code == 200, str(resp.status_code))
    admin_token = csrf()

    resp, body = api_json("/api/students")
    check("el admin ve los correos de los alumnos",
          resp.status_code == 200 and all("email" in s for s in body), str(body[:2]))

    print("== el admin elimina alumnos registrados ==")
    db = sqlite3.connect(TEST_DB)
    db.execute(
        "INSERT INTO users (first_name, last_name, email, password_hash, role, account_status, "
        "current_year_id) VALUES (?, ?, ?, ?, 'student', 'active', 1)",
        ("Alumno", "Borrable", "borrable.et7@test.local",
         generate_password_hash("borrarpassword123")),
    )
    db.commit()
    deletable_id = db.execute(
        "SELECT id FROM users WHERE email = ?", ("borrable.et7@test.local",)
    ).fetchone()[0]
    admin_id = db.execute(
        "SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    with_publications_id = pilar_pub["author_id"]
    db.close()

    resp, body = api_json("/api/students")
    check("el alumno nuevo aparece en la lista",
          any(s["id"] == deletable_id for s in body), str(deletable_id))
    resp, _ = api_json("/api/students/%s" % deletable_id, "DELETE", None,
                       {"X-CSRF-Token": admin_token})
    check("el admin elimina un alumno -> 200", resp.status_code == 200, str(resp.status_code))
    resp, body = api_json("/api/students")
    check("el alumno eliminado ya no aparece",
          all(s["id"] != deletable_id for s in body), str(deletable_id))
    resp, _ = api_json("/api/students/%s" % deletable_id, "DELETE", None,
                       {"X-CSRF-Token": admin_token})
    check("eliminar un alumno inexistente -> 404", resp.status_code == 404, str(resp.status_code))
    resp, _ = api_json("/api/students/%s" % admin_id, "DELETE", None,
                       {"X-CSRF-Token": admin_token})
    check("no se puede eliminar a un administrador -> 404", resp.status_code == 404,
          str(resp.status_code))
    resp, _ = api_json("/api/students/%s" % with_publications_id, "DELETE", None,
                       {"X-CSRF-Token": admin_token})
    check("un alumno con publicaciones no se elimina -> 409", resp.status_code == 409,
          str(resp.status_code))

    resp, _ = api_json("/api/comments/%s" % comment_id, "DELETE", None,
                       {"X-CSRF-Token": admin_token})
    check("el admin elimina un mensaje de la comunidad -> 200", resp.status_code == 200,
          str(resp.status_code))
    resp, body = api_json("/api/comments")
    check("el mensaje eliminado ya no aparece",
          all(m.get("id") != comment_id for m in body), str(body[-2:]))
    resp, _ = api_json("/api/comments/999999", "DELETE", None, {"X-CSRF-Token": admin_token})
    check("eliminar un mensaje inexistente -> 404", resp.status_code == 404, str(resp.status_code))

    pilar_key = pilar_pub["file_url"].rsplit("/", 1)[-1]
    resp, _ = api_json("/api/admin/publications/%s" % pilar_pub["id"], "DELETE", None,
                       {"X-CSRF-Token": admin_token})
    check("el admin elimina una publicación -> 200", resp.status_code == 200, str(resp.status_code))
    resp, body = api_json("/api/publications/shared")
    check("la publicación eliminada sale de apuntes compartidos",
          all(p["id"] != pilar_pub["id"] for p in body), str(body))
    resp = client.get("/api/files/" + pilar_key)
    check("el archivo de la publicación eliminada ya no existe -> 404",
          resp.status_code == 404, str(resp.status_code))
    resp, body = api_json("/api/admin/publications?status=all")
    check("la publicación eliminada no queda en moderación",
          all(p["id"] != pilar_pub["id"] for p in body), str(body))

    print("== título opcional y único ==")
    optional_title_upload = upload_dict()
    optional_title_upload.pop("title")
    resp, untitled_pub = api_json("/api/publications", "POST", optional_title_upload,
                                  {"X-CSRF-Token": admin_token}, content_type="multipart/form-data")
    check("se puede publicar sin título -> 201", resp.status_code == 201, str(resp.status_code))
    check("sin título usa el nombre del archivo",
          isinstance(untitled_pub, dict) and untitled_pub.get("title") == "apuntes.pdf", str(untitled_pub))
    resp, _ = api_json("/api/admin/publications/%s" % untitled_pub["id"], "DELETE", None,
                       {"X-CSRF-Token": admin_token})
    check("el apunte sin título se puede eliminar tras la prueba", resp.status_code == 200, str(resp.status_code))

    print("== consistente entre index.html y app.js ==")
    html = (BASE / "index.html").read_text(encoding="utf-8")
    js = (BASE / "app.js").read_text(encoding="utf-8")
    html_ids = set(re.findall(r'\bid="([^"]+)"', html))
    used_ids = set(re.findall(r'(?:querySelector|querySelectorAll|getElementById)\(\s*"#([A-Za-z][\w-]*)"', js))
    missing = sorted(i for i in used_ids if i not in html_ids)
    check("todos los ids referenciados en app.js existen en index.html", not missing, str(missing))

    for name in ("subject", "title", "year", "division", "file"):
        check("formulario #uploadForm tiene name=%r" % name,
              re.search(r'name="%s"' % re.escape(name), html) is not None)

    check("sin año no se muestran todas las materias",
          "Elegí un año para ver sus materias" in js and "if (!year) {" in js)
    check("el filtro de materias se deshabilita sin año", "select.disabled = true" in js)
    check("las materias se deduplican por nombre", "uniqueSubjectsByName" in js)
    check("el hint inicial pide elegir un año",
          "Elegí un año para ver sus materias" in html)

    check("sin campo de código de acceso", 'name="access_code"' not in html)
    check("sin lógica de código de acceso en app.js", "access_code" not in js)
    check("accesos de prueba visibles",
          "admin.et7@gmail.com" in html and "alumno.et7@gmail.com" in html)
    check("contraseñas de prueba visibles",
          "AdminET7.2026" in html and "AlumnoET7.2026" in html)
    check("botón Usar completa el login", "data-demo-email" in html and "data-demo-email" in js)
    check("el turno está disponible sin asignación previa",
          "El administrador debe asignar el turno" not in js and "uploadShift.disabled = false;" in js)
    check("el formulario pide turno antes que división",
          html.index('id="uploadShift"') < html.index('id="uploadDivision"'))
    check("la división se filtra por turno",
          "updateUploadDivisions" in js and "uploadDivision.disabled = !ready;" in js)
    check("las divisiones muestran su turno",
          "shift.name" in js and "· ${escapeHTML(shift.name)}" in js)

    app_py = (BASE / "app.py").read_text(encoding="utf-8")
    check("moderación muestra materiales rechazados",
          'id="adminRejected"' in html and "renderRejectedList" in js)
    check("el botón rechazar funciona y guarda el motivo",
          'data-review="rejected"' in js and "rejection_reason" in js)
    check("el rechazo usa un formulario propio y no un prompt del navegador",
          'id="rejectModal"' in html and "openRejectModal" in js and "window.prompt" not in js)
    check("el login no usa event.currentTarget después del await",
          "formElement.reset()" in js and "event.currentTarget.reset()" not in js)
    check("el título no tiene límite en el formulario", 'maxlength="90"' not in html)
    check("el título no tiene límite en el servidor", "90 caracteres" not in app_py)
    check("límite de archivo en 100 MB",
          "100 MB" in html and "MAX_FILE_SIZE = 100 * 1024 * 1024" in app_py)
    check("mensaje de inicio de sesión en español", "Inicio de sesión correcto" in js)
    check("validación del login en español", "setSpanishValidation" in js)
    check("el login es la primera pantalla",
          'id="authGate"' in html and 'id="appShell" hidden' in html, "falta la pantalla de acceso")
    check("no queda una cuenta de invitado",
          "Invitado" not in html and "Invitado" not in js, "aparece 'Invitado'")
    check("hay apartado de comunidad (chat) en la interfaz",
          'id="communityView"' in html and 'id="commentForm"' in html and "/api/comments" in js)
    check("solo el admin puede eliminar mensajes en la interfaz",
          'data-delete-comment' in js and 'currentUser?.role === "admin"' in js)
    check("hay apartado de alumnos registrados",
          'id="studentsView"' in html and 'id="studentGrid"' in html and "/api/students" in js)
    check("solo el admin puede eliminar alumnos en la interfaz",
          'data-delete-student' in js and "api/students/${studentId}" in js
          and 'currentUser?.role === "admin"' in js)
    check("el registro pide .et7 en la interfaz",
          'pattern=".*\\.et7.*"' in html and 'email:pattern' in js and ".et7" in app_py)
    check("el título de los apuntes es opcional y tiene un solo campo",
          'name="title" type="text"' in html and '(opcional, máximo uno)' in html
          and 'name="title" type="text" required' not in html)
    check("el servidor rechaza más de un título",
          'request.form.getlist("title")' in app_py and "Solo podés indicar un título." in app_py)
    sql = (BASE / "aula7.sql").read_text(encoding="utf-8")
    check("el esquema crea la tabla de la comunidad",
          "CREATE TABLE IF NOT EXISTS comments" in sql and "INSERT OR IGNORE INTO comments" in sql)
    check("solo el admin ve el botón de eliminar publicación",
          'id="deleteMaterial"' in html and 'currentUser?.role !== "admin"' in js
          and "api/admin/publications/${publicationId}" in js)
    check("la vista previa está integrada al detalle",
          'id="detailPreview"' in html and "renderDetailPreview" in js and "preview_url" in js)
    check("los campos del login no autocompletan otras cuentas",
          html.count('autocomplete="off"') >= 3)
    check("los accesos de prueba se completan desde el login",
          "applyDemoCredentials" in js and "data-demo-role" in html)

    cuentas_md = BASE / "cuentas.md"
    check("existe el archivo de cuentas sin tocar la base", cuentas_md.exists())
    cuentas_text = cuentas_md.read_text(encoding="utf-8") if cuentas_md.exists() else ""
    check("el archivo de cuentas trae los accesos de prueba",
          "admin.et7@gmail.com" in cuentas_text and "alumno.et7@gmail.com" in cuentas_text
          and "AdminET7.2026" in cuentas_text and "AlumnoET7.2026" in cuentas_text)

    css = (BASE / "styles.css").read_text(encoding="utf-8")
    check("styles.css llaves balanceadas", css.count("{") == css.count("}"),
          "abiertas=%d cerradas=%d" % (css.count("{"), css.count("}")))

    print()
    print("RESULTADO: %d pasadas, %d fallidas" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FALLAS:")
        for name in FAIL:
            print("  - %s" % name)
        sys.exit(1)


if __name__ == "__main__":
    main()
