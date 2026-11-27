import hashlib
import hmac
import os
import secrets
import sqlite3
import uuid
import zipfile
from functools import wraps
from pathlib import Path

from flask import Flask, abort, g, jsonify, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("AULA7_DATABASE", BASE_DIR / "aula7.db")).resolve()
UPLOAD_DIR = Path(os.environ.get("AULA7_UPLOAD_DIR", BASE_DIR / "private_uploads")).resolve()
MAX_FILE_SIZE = 100 * 1024 * 1024
MAX_UNCOMPRESSED_SIZE = 300 * 1024 * 1024
ALLOWED_TYPES = {
    "pdf": ("application/pdf",),
    "jpg": ("image/jpeg",),
    "jpeg": ("image/jpeg",),
    "png": ("image/png",),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
}
REPORT_REASONS = {
    "not_educational",
    "private_information",
    "misclassified",
    "inappropriate",
    "other",
}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("AULA7_SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=MAX_FILE_SIZE + 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("AULA7_COOKIE_SECURE", "").lower() == "true",
)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 10000")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def api_error(message, status):
    return jsonify({"error": message}), status


def csrf_token():
    token = session.get("csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.before_request
def protect_api_mutations():
    if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected = session.get("csrf_token")
        provided = request.headers.get("X-CSRF-Token", "")
        if not expected or not hmac.compare_digest(expected, provided):
            return api_error("La sesión expiró o la solicitud no es válida. Actualizá la página.", 400)


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute(
        "SELECT id, first_name, last_name, email, role, account_status, current_year_id "
        "FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return api_error("Iniciá sesión para continuar.", 401)
        if user["account_status"] != "active":
            session.clear()
            return api_error("La cuenta no está activa. Contactá al administrador.", 403)
        g.user = user
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            return api_error("Esta acción requiere permisos de administrador.", 403)
        return view(*args, **kwargs)

    return wrapped


def user_json(user):
    if user is None:
        return None
    return {
        "id": user["id"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "email": user["email"],
        "role": user["role"],
        "account_status": user["account_status"],
        "current_year_id": user["current_year_id"],
    }


def publication_json(row):
    return {
        "id": row["id"],
        "author_id": row["author_id"],
        "title": row["title"] or row["original_name"],
        "file_name": row["original_name"],
        "subject": row["subject_name"],
        "year": row["year_number"],
        "year_id": row["academic_year_id"],
        "division": f'{row["year_number"]}.ª {row["division_number"]}.ª',
        "division_id": row["division_id"],
        "shift": row["shift_name"] or "Turno sin asignar",
        "shift_id": row["shift_id"],
        "type": row["extension"].upper(),
        "date": row["created_at"],
        "author": f'{row["first_name"]} {row["last_name"][0]}.',
        "status": row["status"],
        "rejection_reason": row["rejection_reason"],
        "file_url": f'/api/files/{row["storage_key"]}',
        "preview_url": f'/api/files/{row["storage_key"]}/preview',
    }


PUBLICATION_QUERY = """
    SELECT p.id, p.author_id, p.title, p.status, p.created_at, p.rejection_reason,
           ay.id AS academic_year_id, ay.year_number,
           d.id AS division_id, d.division_number, COALESCE(p.shift_id, d.shift_id) AS shift_id,
           sh.name AS shift_name,
           s.name AS subject_name,
           f.original_name, f.storage_key, f.extension,
           u.first_name, u.last_name
    FROM publications p
    JOIN academic_years ay ON ay.id = p.academic_year_id
    JOIN divisions d ON d.id = p.division_id AND d.academic_year_id = p.academic_year_id
    LEFT JOIN shifts sh ON sh.id = COALESCE(p.shift_id, d.shift_id)
    JOIN subjects s ON s.id = p.subject_id AND s.academic_year_id = p.academic_year_id
    JOIN files f ON f.id = p.file_id
    JOIN users u ON u.id = p.author_id
"""


def validate_upload(file_storage):
    original_name = file_storage.filename or ""
    safe_name = secure_filename(original_name)
    if not safe_name or "." not in safe_name:
        return None, "El archivo debe tener un nombre válido y una extensión permitida."
    extension = safe_name.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_TYPES:
        return None, "Formato no permitido. Usá PDF, JPG, PNG, DOCX o PPTX."
    data = file_storage.read(MAX_FILE_SIZE + 1)
    file_storage.stream.seek(0)
    if not data:
        return None, "El archivo está vacío."
    if len(data) > MAX_FILE_SIZE:
        return None, "El archivo supera el límite de 100 MB."

    detected_mime = file_storage.mimetype or ""
    if detected_mime not in ALLOWED_TYPES[extension]:
        return None, "El tipo real del archivo no coincide con su extensión."
    if extension == "pdf" and not data.startswith(b"%PDF-"):
        return None, "El contenido no parece ser un documento PDF válido."
    if extension == "png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None, "El contenido no parece ser una imagen PNG válida."
    if extension in {"jpg", "jpeg"} and not data.startswith(b"\xff\xd8\xff"):
        return None, "El contenido no parece ser una imagen JPEG válida."
    if extension in {"docx", "pptx"}:
        try:
            with zipfile.ZipFile(file_storage.stream) as archive:
                names = set(archive.namelist())
                required = "word/document.xml" if extension == "docx" else "ppt/presentation.xml"
                uncompressed_size = sum(info.file_size for info in archive.infolist())
                if "[Content_Types].xml" not in names or required not in names:
                    return None, "El documento de Office está incompleto o no es válido."
                if uncompressed_size > MAX_UNCOMPRESSED_SIZE:
                    return None, "El tamaño descomprimido del documento no es válido."
        except (OSError, zipfile.BadZipFile):
            return None, "El documento de Office está dañado o no es válido."
        finally:
            file_storage.stream.seek(0)

    return {
        "name": safe_name,
        "extension": extension,
        "mime_type": detected_mime,
        "data": data,
        "sha256": hashlib.sha256(data).hexdigest(),
    }, None


@app.get("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/<path:asset>")
def static_asset(asset):
    if asset not in {"styles.css", "app.js"}:
        abort(404)
    return send_from_directory(BASE_DIR, asset)


@app.get("/api/session")
def api_session():
    return jsonify({"csrf_token": csrf_token(), "user": user_json(current_user())})


@app.get("/api/catalog")
def api_catalog():
    db = get_db()
    years = [
        dict(row)
        for row in db.execute(
            "SELECT id, year_number AS number, name, planned_divisions AS divisions "
            "FROM academic_years ORDER BY year_number"
        )
    ]
    divisions = [
        dict(row)
        for row in db.execute(
            "SELECT d.id, d.academic_year_id AS year_id, d.division_number AS number, "
            "d.shift_id, sh.name AS shift "
            "FROM divisions d LEFT JOIN shifts sh ON sh.id = d.shift_id "
            "ORDER BY d.academic_year_id, d.division_number"
        )
    ]
    subjects = [
        dict(row)
        for row in db.execute(
            "SELECT id, academic_year_id AS year_id, name "
            "FROM subjects WHERE is_active = 1 ORDER BY academic_year_id, name"
        )
    ]
    shifts = [dict(row) for row in db.execute("SELECT id, name FROM shifts ORDER BY id")]
    return jsonify({"years": years, "divisions": divisions, "subjects": subjects, "shifts": shifts})


@app.get("/api/publications")
@login_required
def api_publications():
    db = get_db()
    clauses = ["p.status = 'approved'"]
    values = []
    for parameter, column in (
        ("year_id", "p.academic_year_id"),
        ("division_id", "p.division_id"),
        ("subject_id", "p.subject_id"),
        ("shift_id", "COALESCE(p.shift_id, d.shift_id)"),
    ):
        value = request.args.get(parameter, "").strip()
        if value:
            try:
                values.append(int(value))
            except ValueError:
                return api_error(f"El filtro {parameter} no es válido.", 400)
            clauses.append(f"{column} = ?")
    query = request.args.get("q", "").strip()
    if query:
        clauses.append(
            "(p.title LIKE ? ESCAPE '\\' OR f.original_name LIKE ? ESCAPE '\\' "
            "OR s.name LIKE ? ESCAPE '\\' OR ay.name LIKE ? ESCAPE '\\' "
            "OR CAST(d.division_number AS TEXT) LIKE ? OR sh.name LIKE ? ESCAPE '\\' "
            "OR u.first_name LIKE ? ESCAPE '\\' OR u.last_name LIKE ? ESCAPE '\\')"
        )
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        values.extend([f"%{escaped_query}%"] * 8)
    try:
        limit = min(max(int(request.args.get("limit", "100")), 1), 200)
    except ValueError:
        return api_error("El límite de resultados no es válido.", 400)
    rows = db.execute(
        PUBLICATION_QUERY + " WHERE " + " AND ".join(clauses)
        + " ORDER BY p.created_at DESC, p.id DESC LIMIT ?",
        [*values, limit],
    ).fetchall()
    return jsonify([publication_json(row) for row in rows])


@app.post("/api/register")
def api_register():
    data = request.get_json(silent=True) or {}
    first_name = str(data.get("first_name", "")).strip()
    last_name = str(data.get("last_name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    try:
        year_id = int(data.get("year_id"))
        division_id = int(data.get("division_id"))
    except (TypeError, ValueError):
        return api_error("Seleccioná un año y una división válidos.", 400)
    if not first_name or len(first_name) > 80 or not last_name or len(last_name) > 80:
        return api_error("Completá nombre y apellido (hasta 80 caracteres cada uno).", 400)
    if len(email) > 254 or "@" not in email:
        return api_error("Ingresá un correo válido.", 400)
    if ".et7" not in email:
        return api_error("El correo debe incluir .et7 (ejemplo: alumno.et7@gmail.com).", 400)
    if len(password) < 10 or len(password) > 128:
        return api_error("La contraseña debe tener entre 10 y 128 caracteres.", 400)
    if not data.get("policy_accepted"):
        return api_error("Aceptá las políticas de publicación para crear tu cuenta.", 400)

    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        division = db.execute(
            "SELECT id FROM divisions WHERE id = ? AND academic_year_id = ?",
            (division_id, year_id),
        ).fetchone()
        if division is None:
            db.rollback()
            return api_error("La división no corresponde al año seleccionado.", 400)
        db.execute(
            "INSERT INTO users (first_name, last_name, email, password_hash, role, account_status, "
            "current_year_id, policy_accepted_at) VALUES (?, ?, ?, ?, 'student', 'active', ?, CURRENT_TIMESTAMP)",
            (first_name, last_name, email, generate_password_hash(password), year_id),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return api_error("Ese correo ya está registrado.", 409)
    except sqlite3.Error:
        db.rollback()
        app.logger.exception("No se pudo completar el registro")
        return api_error("No se pudo completar el registro.", 500)

    user = db.execute(
        "SELECT id, first_name, last_name, email, role, account_status, current_year_id "
        "FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    session.clear()
    session["user_id"] = user["id"]
    csrf_token()
    return jsonify({"user": user_json(user), "csrf_token": session["csrf_token"]}), 201


@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    user = get_db().execute(
        "SELECT id, first_name, last_name, email, password_hash, role, account_status, current_year_id "
        "FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        return api_error("Correo o contraseña incorrectos.", 401)
    if user["account_status"] != "active":
        return api_error("La cuenta todavía no está activa. Contactá al administrador.", 403)
    session.clear()
    session["user_id"] = user["id"]
    csrf_token()
    return jsonify({"user": user_json(user), "csrf_token": session["csrf_token"]})


@app.post("/api/logout")
@login_required
def api_logout():
    session.clear()
    return jsonify({"user": None, "csrf_token": csrf_token()})


def comment_json(row):
    return {
        "id": row["id"],
        "body": row["body"],
        "created_at": row["created_at"],
        "author_id": row["user_id"],
        "author": "%s %s" % (row["first_name"], row["last_name"]),
        "role": row["role"],
    }


COMMENT_SELECT = (
    "SELECT c.id, c.body, c.created_at, c.user_id, u.first_name, u.last_name, u.role "
    "FROM comments c JOIN users u ON u.id = c.user_id"
)


@app.get("/api/comments")
@login_required
def api_list_comments():
    rows = get_db().execute(
        COMMENT_SELECT + " ORDER BY c.id DESC LIMIT 300"
    ).fetchall()
    return jsonify([comment_json(row) for row in reversed(rows)])


@app.post("/api/comments")
@login_required
def api_create_comment():
    data = request.get_json(silent=True) or {}
    body = str(data.get("body", "")).strip()
    if not body:
        return api_error("Escribí un mensaje antes de enviarlo.", 400)
    if len(body) > 500:
        return api_error("El mensaje no puede superar los 500 caracteres.", 400)
    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO comments (user_id, body) VALUES (?, ?)",
            (g.user["id"], body),
        )
        db.commit()
    except sqlite3.Error:
        db.rollback()
        app.logger.exception("No se pudo enviar el mensaje")
        return api_error("No se pudo enviar el mensaje.", 500)
    row = db.execute(
        COMMENT_SELECT + " WHERE c.id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return jsonify(comment_json(row)), 201


@app.delete("/api/comments/<int:comment_id>")
@admin_required
def api_delete_comment(comment_id):
    """Solo el administrador puede controlar (eliminar) los mensajes enviados."""
    db = get_db()
    cursor = db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    db.commit()
    if cursor.rowcount == 0:
        return api_error("Ese mensaje ya no existe.", 404)
    return jsonify({"deleted": comment_id})


STATUS_LABELS = {
    "active": "Activa",
    "pending": "Pendiente",
    "suspended": "Suspendida",
    "inactive": "Inactiva",
}


@app.get("/api/students")
@login_required
def api_students():
    rows = get_db().execute(
        "SELECT u.id, u.first_name, u.last_name, u.email, u.role, u.account_status, y.year_number "
        "FROM users u LEFT JOIN academic_years y ON y.id = u.current_year_id "
        "WHERE u.role = 'student' "
        "ORDER BY u.first_name COLLATE NOCASE, u.last_name COLLATE NOCASE"
    ).fetchall()
    students = []
    for row in rows:
        item = {
            "id": row["id"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "name": "%s %s" % (row["first_name"], row["last_name"]),
            "role": row["role"],
            "year": row["year_number"],
            "status": row["account_status"],
            "status_label": STATUS_LABELS.get(row["account_status"], row["account_status"]),
        }
        if g.user["role"] == "admin":
            item["email"] = row["email"]
        students.append(item)
    return jsonify(students)


@app.delete("/api/students/<int:student_id>")
@admin_required
def api_delete_student(student_id):
    """Solo el administrador puede eliminar cuentas de alumnos registrados."""
    db = get_db()
    student = db.execute(
        "SELECT id, first_name, last_name, role FROM users WHERE id = ?",
        (student_id,),
    ).fetchone()
    if student is None or student["role"] != "student":
        return api_error("Ese alumno ya no existe.", 404)
    publications = db.execute(
        "SELECT COUNT(*) FROM publications WHERE author_id = ?",
        (student_id,),
    ).fetchone()[0]
    reports = db.execute(
        "SELECT COUNT(*) FROM publication_reports WHERE reporter_id = ?",
        (student_id,),
    ).fetchone()[0]
    if publications or reports:
        return api_error(
            "El alumno tiene publicaciones o reportes. Eliminá primero ese contenido desde Moderación.",
            409,
        )
    try:
        db.execute("DELETE FROM users WHERE id = ? AND role = 'student'", (student_id,))
        db.commit()
    except sqlite3.Error:
        db.rollback()
        app.logger.exception("No se pudo eliminar al alumno")
        return api_error("No se pudo eliminar al alumno.", 500)
    return jsonify({
        "deleted": student_id,
        "name": "%s %s" % (student["first_name"], student["last_name"]),
    })


@app.post("/api/publications")
@login_required
def api_create_publication():
    if "file" not in request.files:
        return api_error("Seleccioná un archivo.", 400)
    file_storage = request.files["file"]
    validated, error = validate_upload(file_storage)
    if error:
        return api_error(error, 400)
    try:
        year_id = int(request.form.get("year_id", ""))
        division_id = int(request.form.get("division_id", ""))
        subject_id = int(request.form.get("subject_id", ""))
        shift_id = int(request.form.get("shift_id", ""))
    except ValueError:
        return api_error("Completá año, división, turno y materia.", 400)
    titles = request.form.getlist("title")
    if len(titles) > 1:
        return api_error("Solo podés indicar un título.", 400)
    title = (titles[0].strip() or None) if titles else None

    db = get_db()
    classification = db.execute(
        "SELECT d.id, d.shift_id FROM divisions d "
        "JOIN subjects s ON s.academic_year_id = d.academic_year_id "
        "WHERE d.id = ? AND d.academic_year_id = ? AND s.id = ? "
        "AND s.is_active = 1 AND d.shift_id = ?",
        (division_id, year_id, subject_id, shift_id),
    ).fetchone()
    if classification is None:
        return api_error("El turno, la división y la materia no coinciden. Elegí una división del turno seleccionado.", 400)

    storage_key = f"{uuid.uuid4().hex}.{validated['extension']}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / storage_key
    try:
        file_storage.save(destination)
        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute(
            "INSERT INTO files (original_name, storage_key, extension, mime_type, size_bytes, sha256) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                validated["name"],
                storage_key,
                validated["extension"],
                validated["mime_type"],
                len(validated["data"]),
                validated["sha256"],
            ),
        )
        file_id = cursor.lastrowid
        cursor = db.execute(
            "INSERT INTO publications (author_id, academic_year_id, division_id, subject_id, shift_id, file_id, title) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (g.user["id"], year_id, division_id, subject_id, shift_id, file_id, title),
        )
        publication_id = cursor.lastrowid
        db.commit()
    except sqlite3.Error:
        db.rollback()
        destination.unlink(missing_ok=True)
        app.logger.exception("No se pudo guardar la publicación")
        return api_error("No se pudo guardar la publicación en la base de datos.", 500)
    except OSError:
        db.rollback()
        destination.unlink(missing_ok=True)
        app.logger.exception("No se pudo guardar el archivo")
        return api_error("No se pudo guardar el archivo en el servidor.", 500)
    row = db.execute(PUBLICATION_QUERY + " WHERE p.id = ?", (publication_id,)).fetchone()
    return jsonify(publication_json(row)), 201


@app.get("/api/publications/mine")
@login_required
def api_my_publications():
    rows = get_db().execute(
        PUBLICATION_QUERY + " WHERE p.author_id = ? ORDER BY p.created_at DESC, p.id DESC",
        (g.user["id"],),
    ).fetchall()
    return jsonify([publication_json(row) for row in rows])


@app.get("/api/publications/shared")
@login_required
def api_shared_publications():
    """Feed global: todos los materiales compartidos por los usuarios."""
    rows = get_db().execute(
        PUBLICATION_QUERY + " ORDER BY p.created_at DESC, p.id DESC"
    ).fetchall()
    return jsonify([publication_json(row) for row in rows])


@app.post("/api/publications/<int:publication_id>/reports")
@login_required
def api_report_publication(publication_id):
    data = request.get_json(silent=True) or {}
    reason = str(data.get("reason", ""))
    details = str(data.get("details", "")).strip() or None
    if reason not in REPORT_REASONS:
        return api_error("Seleccioná un motivo de reporte válido.", 400)
    if details and len(details) > 1000:
        return api_error("El detalle del reporte no puede superar los 1000 caracteres.", 400)
    publication = get_db().execute(
        "SELECT id, author_id FROM publications WHERE id = ? AND status = 'approved'",
        (publication_id,),
    ).fetchone()
    if publication is None or publication["author_id"] == g.user["id"]:
        return api_error("No se puede reportar esa publicación.", 404)
    try:
        get_db().execute(
            "INSERT INTO publication_reports (publication_id, reporter_id, reason, details) "
            "VALUES (?, ?, ?, ?)",
            (publication_id, g.user["id"], reason, details),
        )
        get_db().commit()
    except sqlite3.IntegrityError as error:
        if "UNIQUE constraint failed" in str(error):
            return api_error("Ya reportaste esta publicación.", 409)
        return api_error("No se encontró la publicación para reportar.", 404)
    return jsonify({"message": "El reporte fue enviado al equipo administrador."}), 201


@app.get("/api/files/<storage_key>")
@login_required
def api_download_file(storage_key):
    db = get_db()
    row = db.execute(
        "SELECT f.storage_key, f.original_name, p.status, p.author_id "
        "FROM files f JOIN publications p ON p.file_id = f.id WHERE f.storage_key = ?",
        (storage_key,),
    ).fetchone()
    if row is None:
        abort(404)
    if row["status"] != "approved" and row["author_id"] != g.user["id"] and g.user["role"] != "admin":
        abort(404)
    path = UPLOAD_DIR / row["storage_key"]
    if not path.is_file():
        app.logger.error("Falta el archivo privado %s", row["storage_key"])
        abort(404)
    return send_file(path, as_attachment=True, download_name=row["original_name"])


@app.get("/api/files/<storage_key>/preview")
@login_required
def api_preview_file(storage_key):
    db = get_db()
    row = db.execute(
        "SELECT f.storage_key, f.original_name, f.extension, f.mime_type, p.status, p.author_id "
        "FROM files f JOIN publications p ON p.file_id = f.id WHERE f.storage_key = ?",
        (storage_key,),
    ).fetchone()
    if row is None:
        abort(404)
    if row["status"] != "approved" and row["author_id"] != g.user["id"] and g.user["role"] != "admin":
        abort(404)
    if row["extension"] not in {"pdf", "jpg", "jpeg", "png"}:
        abort(404)
    path = UPLOAD_DIR / row["storage_key"]
    if not path.is_file():
        app.logger.error("Falta el archivo privado %s", row["storage_key"])
        abort(404)
    return send_file(
        path,
        as_attachment=False,
        download_name=row["original_name"],
        mimetype=row["mime_type"],
        conditional=True,
    )


@app.get("/api/admin/publications")
@admin_required
def api_admin_publications():
    status = request.args.get("status", "pending")
    if status not in {"pending", "approved", "rejected", "withdrawn", "all"}:
        return api_error("El filtro de estado no es válido.", 400)
    where = "" if status == "all" else " WHERE p.status = ?"
    parameters = () if status == "all" else (status,)
    rows = get_db().execute(
        PUBLICATION_QUERY + where + " ORDER BY p.created_at DESC",
        parameters,
    ).fetchall()
    return jsonify([publication_json(row) for row in rows])


@app.get("/api/admin/reports")
@admin_required
def api_admin_reports():
    rows = get_db().execute(
        "SELECT r.id, r.reason, r.details, r.created_at, p.title, f.original_name, "
        "u.first_name, u.last_name "
        "FROM publication_reports r "
        "JOIN publications p ON p.id = r.publication_id "
        "JOIN files f ON f.id = p.file_id "
        "JOIN users u ON u.id = r.reporter_id "
        "WHERE r.status = 'pending' ORDER BY r.created_at DESC"
    ).fetchall()
    reason_labels = {
        "not_educational": "No relacionado con el estudio",
        "private_information": "Información privada",
        "misclassified": "Mal clasificado",
        "inappropriate": "Contenido inapropiado",
        "other": "Otro incumplimiento",
    }
    return jsonify([
        {
            "id": row["id"],
            "publication_title": row["title"] or row["original_name"],
            "reason": row["reason"],
            "reason_label": reason_labels[row["reason"]],
            "details": row["details"],
            "created_at": row["created_at"],
            "reporter_name": f'{row["first_name"]} {row["last_name"][0]}.',
        }
        for row in rows
    ])


@app.patch("/api/admin/reports/<int:report_id>")
@admin_required
def api_review_report(report_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {"reviewed", "dismissed", "action_taken"}:
        return api_error("El estado del reporte no es válido.", 400)
    db = get_db()
    cursor = db.execute(
        "UPDATE publication_reports SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND status = 'pending'",
        (status, g.user["id"], report_id),
    )
    if cursor.rowcount == 0:
        return api_error("El reporte no existe o ya fue revisado.", 404)
    db.execute(
        "INSERT INTO admin_audit_log (admin_user_id, action, entity_type, entity_id) "
        "VALUES (?, ?, 'publication_report', ?)",
        (g.user["id"], status, report_id),
    )
    db.commit()
    return jsonify({"id": report_id, "status": status})


@app.patch("/api/admin/publications/<int:publication_id>")
@admin_required
def api_review_publication(publication_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {"approved", "rejected", "withdrawn"}:
        return api_error("Estado de revisión no válido.", 400)
    db = get_db()
    publication = db.execute(
        "SELECT id, status FROM publications WHERE id = ?", (publication_id,)
    ).fetchone()
    if publication is None:
        return api_error("No se encontró la publicación.", 404)
    reason = str(data.get("rejection_reason", "")).strip() or None
    db.execute(
        "UPDATE publications SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, "
        "rejection_reason = ? WHERE id = ?",
        (status, g.user["id"], reason if status == "rejected" else None, publication_id),
    )
    db.execute(
        "INSERT INTO admin_audit_log (admin_user_id, action, entity_type, entity_id, details) "
        "VALUES (?, ?, 'publication', ?, ?)",
        (g.user["id"], status, publication_id, reason),
    )
    db.commit()
    return jsonify({"id": publication_id, "status": status})


@app.delete("/api/admin/publications/<int:publication_id>")
@admin_required
def api_delete_publication(publication_id):
    """Solo un administrador puede eliminar una publicación y su archivo."""
    db = get_db()
    publication = db.execute(
        "SELECT p.id, p.file_id, f.storage_key, f.original_name "
        "FROM publications p JOIN files f ON f.id = p.file_id WHERE p.id = ?",
        (publication_id,),
    ).fetchone()
    if publication is None:
        return api_error("No se encontró la publicación.", 404)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM publication_reports WHERE publication_id = ?", (publication_id,))
        db.execute("DELETE FROM publications WHERE id = ?", (publication_id,))
        db.execute("DELETE FROM files WHERE id = ?", (publication["file_id"],))
        db.execute(
            "INSERT INTO admin_audit_log (admin_user_id, action, entity_type, entity_id, details) "
            "VALUES (?, 'deleted', 'publication', ?, ?)",
            (g.user["id"], publication_id, publication["original_name"]),
        )
        db.commit()
    except sqlite3.Error:
        db.rollback()
        app.logger.exception("No se pudo eliminar la publicación")
        return api_error("No se pudo eliminar la publicación.", 500)
    (UPLOAD_DIR / publication["storage_key"]).unlink(missing_ok=True)
    return jsonify({"id": publication_id, "deleted": True})


@app.cli.command("create-admin")
def create_admin():
    """Create the first administrator interactively."""
    import getpass

    email = input("Correo del administrador: ").strip().lower()
    first_name = input("Nombre: ").strip()
    last_name = input("Apellido: ").strip()
    password = getpass.getpass("Contraseña (mínimo 12 caracteres): ")
    if len(password) < 12 or len(password) > 128:
        raise SystemExit("La contraseña debe tener entre 12 y 128 caracteres.")
    try:
        get_db().execute(
            "INSERT INTO users (first_name, last_name, email, password_hash, role, account_status) "
            "VALUES (?, ?, ?, ?, 'admin', 'active')",
            (first_name, last_name, email, generate_password_hash(password)),
        )
        get_db().commit()
    except sqlite3.IntegrityError as error:
        raise SystemExit("No se pudo crear el administrador: el correo ya existe o hay datos inválidos.") from error
    print("Administrador creado.")


@app.cli.command("set-division-shift")
def set_division_shift():
    """Set the official shift for a division number within an academic year."""
    year = input("Año (1-6): ").strip()
    division_number = input("Número de división: ").strip()
    shift_name = input("Turno (Mañana/Tarde): ").strip()
    db = get_db()
    try:
        year_number = int(year)
        division_number = int(division_number)
    except ValueError as error:
        raise SystemExit("El año y la división deben ser números.") from error
    division = db.execute(
        "SELECT d.id FROM divisions d JOIN academic_years ay ON ay.id = d.academic_year_id "
        "WHERE ay.year_number = ? AND d.division_number = ?",
        (year_number, division_number),
    ).fetchone()
    shift = db.execute("SELECT id FROM shifts WHERE name = ?", (shift_name,)).fetchone()
    if division is None or shift is None:
        raise SystemExit("No se encontró esa división o el turno debe ser Mañana o Tarde.")
    db.execute("UPDATE divisions SET shift_id = ? WHERE id = ?", (shift["id"], division["id"]))
    db.commit()
    print(f"Turno guardado: {year_number}º año, división {division_number}, {shift_name}.")


@app.errorhandler(413)
def request_too_large(_error):
    return api_error("La solicitud supera el tamaño permitido.", 413)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
