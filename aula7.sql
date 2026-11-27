-- AULA 7 - SQLite schema for DB Browser for SQLite
-- In DB Browser: open/create a database, open this file in "Execute SQL",
-- run it, then click "Write Changes".
-- The academic subjects below are demonstration data and must be checked
-- against the school's official curriculum before production use.

PRAGMA foreign_keys = ON;
BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS academic_years (
    id              INTEGER PRIMARY KEY,
    year_number     INTEGER NOT NULL UNIQUE CHECK (year_number BETWEEN 1 AND 6),
    name            TEXT NOT NULL UNIQUE,
    planned_divisions INTEGER NOT NULL CHECK (planned_divisions > 0)
);

CREATE TABLE IF NOT EXISTS shifts (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE CHECK (name IN ('Mañana', 'Tarde'))
);

CREATE TABLE IF NOT EXISTS divisions (
    id                  INTEGER PRIMARY KEY,
    academic_year_id    INTEGER NOT NULL,
    division_number     INTEGER NOT NULL CHECK (division_number > 0),
    shift_id            INTEGER,
    UNIQUE (academic_year_id, division_number),
    UNIQUE (id, academic_year_id),
    FOREIGN KEY (academic_year_id) REFERENCES academic_years(id) ON DELETE RESTRICT,
    FOREIGN KEY (shift_id) REFERENCES shifts(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS subjects (
    id                  INTEGER PRIMARY KEY,
    academic_year_id    INTEGER NOT NULL,
    name                TEXT NOT NULL CHECK (length(trim(name)) > 0),
    is_active           INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    UNIQUE (academic_year_id, name),
    UNIQUE (id, academic_year_id),
    FOREIGN KEY (academic_year_id) REFERENCES academic_years(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY,
    first_name          TEXT NOT NULL CHECK (length(trim(first_name)) > 0),
    last_name           TEXT NOT NULL CHECK (length(trim(last_name)) > 0),
    email               TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash       TEXT NOT NULL,
    role                TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('student', 'admin')),
    account_status      TEXT NOT NULL DEFAULT 'pending'
                        CHECK (account_status IN ('pending', 'active', 'suspended', 'inactive')),
    current_year_id     INTEGER,
    policy_accepted_at  TEXT,
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (current_year_id) REFERENCES academic_years(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS files (
    id                  INTEGER PRIMARY KEY,
    original_name       TEXT NOT NULL CHECK (length(trim(original_name)) > 0),
    storage_key         TEXT NOT NULL UNIQUE,
    extension           TEXT NOT NULL
                        CHECK (lower(extension) IN ('pdf', 'jpg', 'jpeg', 'png', 'docx', 'pptx')),
    mime_type           TEXT NOT NULL CHECK (mime_type IN (
                            'application/pdf',
                            'image/jpeg',
                            'image/png',
                            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                            'application/vnd.openxmlformats-officedocument.presentationml.presentation'
                        )),
    size_bytes          INTEGER NOT NULL CHECK (size_bytes BETWEEN 1 AND 104857600),
    sha256              TEXT CHECK (sha256 IS NULL OR length(sha256) = 64),
    uploaded_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (lower(extension) = 'pdf' AND mime_type = 'application/pdf')
        OR (lower(extension) IN ('jpg', 'jpeg') AND mime_type = 'image/jpeg')
        OR (lower(extension) = 'png' AND mime_type = 'image/png')
        OR (lower(extension) = 'docx' AND mime_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        OR (lower(extension) = 'pptx' AND mime_type = 'application/vnd.openxmlformats-officedocument.presentationml.presentation')
    )
);

CREATE TABLE IF NOT EXISTS publications (
    id                  INTEGER PRIMARY KEY,
    author_id           INTEGER NOT NULL,
    academic_year_id    INTEGER NOT NULL,
    division_id         INTEGER NOT NULL,
    subject_id          INTEGER NOT NULL,
    shift_id            INTEGER,
    file_id             INTEGER NOT NULL UNIQUE,
    title               TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected', 'withdrawn')),
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_by         INTEGER,
    reviewed_at         TEXT,
    rejection_reason    TEXT,
    FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (division_id, academic_year_id)
        REFERENCES divisions(id, academic_year_id) ON DELETE RESTRICT,
    FOREIGN KEY (subject_id, academic_year_id)
        REFERENCES subjects(id, academic_year_id) ON DELETE RESTRICT,
    FOREIGN KEY (shift_id) REFERENCES shifts(id) ON DELETE RESTRICT,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE RESTRICT,
    FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL,
    CHECK (
        (status = 'pending' AND reviewed_at IS NULL AND reviewed_by IS NULL)
        OR (status IN ('approved', 'rejected') AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)
        OR (status = 'withdrawn' AND reviewed_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS publication_reports (
    id              INTEGER PRIMARY KEY,
    publication_id  INTEGER NOT NULL,
    reporter_id     INTEGER NOT NULL,
    reason          TEXT NOT NULL
                    CHECK (reason IN (
                        'not_educational',
                        'private_information',
                        'misclassified',
                        'inappropriate',
                        'other'
                    )),
    details         TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'reviewed', 'dismissed', 'action_taken')),
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_by     INTEGER,
    reviewed_at     TEXT,
    UNIQUE (publication_id, reporter_id),
    FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE RESTRICT,
    FOREIGN KEY (reporter_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL,
    CHECK (details IS NULL OR length(details) <= 1000)
);

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id              INTEGER PRIMARY KEY,
    admin_user_id   INTEGER,
    action          TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_id       INTEGER,
    details         TEXT,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- Comunidad: chat de mensajes entre estudiantes. Solo el admin los controla.
CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    body        TEXT NOT NULL CHECK (length(trim(body)) > 0 AND length(body) <= 1000),
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_divisions_year ON divisions(academic_year_id);
CREATE INDEX IF NOT EXISTS idx_subjects_year_active ON subjects(academic_year_id, is_active);
CREATE INDEX IF NOT EXISTS idx_users_status_role ON users(account_status, role);
CREATE INDEX IF NOT EXISTS idx_publications_status_created ON publications(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_publications_year_division_subject
    ON publications(academic_year_id, division_id, subject_id);
CREATE INDEX IF NOT EXISTS idx_publications_shift ON publications(shift_id);
CREATE INDEX IF NOT EXISTS idx_reports_status_created ON publication_reports(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);

INSERT OR IGNORE INTO academic_years (id, year_number, name, planned_divisions) VALUES
    (1, 1, '1.º año', 6),
    (2, 2, '2.º año', 4),
    (3, 3, '3.º año', 4),
    (4, 4, '4.º año', 4),
    (5, 5, '5.º año', 4),
    (6, 6, '6.º año', 4);

INSERT OR IGNORE INTO shifts (id, name) VALUES
    (1, 'Mañana'),
    (2, 'Tarde');

INSERT OR IGNORE INTO divisions (academic_year_id, division_number, shift_id)
SELECT academic_years.id, division_numbers.division_number,
       CASE
           WHEN division_numbers.division_number <= academic_years.planned_divisions / 2 THEN 1
           ELSE 2
       END
FROM academic_years
JOIN (
    SELECT 1 AS division_number UNION ALL
    SELECT 2 UNION ALL
    SELECT 3 UNION ALL
    SELECT 4 UNION ALL
    SELECT 5 UNION ALL
    SELECT 6
) AS division_numbers
    ON division_numbers.division_number <= academic_years.planned_divisions;

-- Example subjects matching the prototype; replace/complete with the official curriculum.
INSERT OR IGNORE INTO subjects (academic_year_id, name) VALUES
    (1, 'Matemática'), (1, 'Prácticas del Lenguaje'), (1, 'Historia'), (1, 'Inglés'), (1, 'Educación Tecnológica'),
    (2, 'Matemática'), (2, 'Física'), (2, 'Química'), (2, 'Historia'), (2, 'Inglés'),
    (3, 'Matemática'), (3, 'Física'), (3, 'Química'), (3, 'Historia'), (3, 'Inglés'),
    (4, 'Matemática'), (4, 'Física'), (4, 'Química'), (4, 'Lengua'), (4, 'Inglés'),
    (5, 'Matemática'), (5, 'Física'), (5, 'Química'), (5, 'Literatura'), (5, 'Inglés'),
    (6, 'Matemática'), (6, 'Física'), (6, 'Química'), (6, 'Proyecto'), (6, 'Inglés');

-- Materias del ciclo básico y del ciclo técnico de la Escuela Técnica N.º 7.
INSERT OR IGNORE INTO subjects (academic_year_id, name) VALUES
    (1, 'Geografía'), (1, 'Biología'), (1, 'Educación Artística'), (1, 'Educación Física'), (1, 'Construcción de Ciudadanía'),
    (2, 'Geografía'), (2, 'Biología'), (2, 'Educación Artística'), (2, 'Educación Física'), (2, 'Construcción de Ciudadanía'), (2, 'Educación Tecnológica'),
    (3, 'Geografía'), (3, 'Biología'), (3, 'Lengua y Literatura'), (3, 'Educación Artística'), (3, 'Educación Física'), (3, 'Construcción de Ciudadanía'),
    (4, 'Historia'), (4, 'Geografía'), (4, 'Inglés Técnico'), (4, 'Educación Física'), (4, 'Ciudadanía y Participación'), (4, 'Dibujo Técnico'), (4, 'Informática'), (4, 'Sistemas Tecnológicos'),
    (5, 'Historia'), (5, 'Geografía'), (5, 'Inglés Técnico'), (5, 'Educación Física'), (5, 'Ciudadanía y Participación'), (5, 'Dibujo Técnico'), (5, 'Informática'), (5, 'Sistemas Digitales'), (5, 'Prácticas Profesionalizantes'),
    (6, 'Historia'), (6, 'Geografía'), (6, 'Literatura'), (6, 'Inglés Técnico'), (6, 'Educación Física'), (6, 'Ciudadanía y Participación'), (6, 'Dibujo Técnico'), (6, 'Informática'), (6, 'Tecnología de los Materiales'), (6, 'Prácticas Profesionalizantes'), (6, 'Emprendimientos Productivos');

-- Usuarios de prueba: las credenciales se muestran en Mi perfil para iniciar sesión rápido.
INSERT OR IGNORE INTO users
    (first_name, last_name, email, password_hash, role, account_status, current_year_id, policy_accepted_at)
VALUES
    ('Admin', 'ET7', 'admin.et7@gmail.com',
     'scrypt:32768:8:1$vZNt1nTCM91Y9AcS$05bc64a5d88a40521b62021498125856a1d6dc68d8612245385dbc613ac9b76fa47c0947cbf335ff2823c98b81a6d372f195c5e61d8ded631789586ccdaaa142',
     'admin', 'active', NULL, CURRENT_TIMESTAMP),
    ('Lucía', 'Pérez', 'alumno.et7@gmail.com',
     'scrypt:32768:8:1$VcpYE6YsoAK3Cc6K$3ee95dd8e1393572da9eded23330c5db185b648552f8f72f234b9f57b9fd838b91c286e9ce0e3b511c72b348e8974518491f2b04a12a3722f46c28544f6203b4',
     'student', 'active', 1, CURRENT_TIMESTAMP),
    ('Mateo', 'Gómez', 'mateo.et7@gmail.com',
     'scrypt:32768:8:1$FSWxetWrcjuYAWLm$a53353c02a8f918fc09ed24c75afa488190ce9f10db54adb04f473675bd4dae27f6490d1997a0d0165926d545ee89cf0e75d52702cf0a903a5f7f251d4068cdc',
     'student', 'active', 2, CURRENT_TIMESTAMP),
    ('Sofía', 'Rodríguez', 'sofia.et7@gmail.com',
     'scrypt:32768:8:1$KDfjHj04ekTfSzAL$86e0e15240ea71bb5ae2ab53f444181936e26f95e619a7a6d92350c1b1d7c1d5abc7e9001cd1b18efb266e9059120ee634b059a9c7d210201407015cacbfb08a',
     'student', 'active', 3, CURRENT_TIMESTAMP),
    ('Julián', 'Fernández', 'julian.et7@gmail.com',
     'scrypt:32768:8:1$NU6g86gKrxOaZWqa$c94e3eb1e974323d030bece9228ba21de3a9217fb096918234b7da6899295dcea35a5b8a2d8bfaa5a9480034ff727a689c8904e9f2dfb0edb3ed75d1e01504bb',
     'student', 'active', 2, CURRENT_TIMESTAMP),
    ('Valentina', 'López', 'valentina.et7@gmail.com',
     'scrypt:32768:8:1$VcpYE6YsoAK3Cc6K$3ee95dd8e1393572da9eded23330c5db185b648552f8f72f234b9f57b9fd838b91c286e9ce0e3b511c72b348e8974518491f2b04a12a3722f46c28544f6203b4',
     'student', 'active', 1, CURRENT_TIMESTAMP),
    ('Santiago', 'Martínez', 'santiago.et7@gmail.com',
     'scrypt:32768:8:1$VcpYE6YsoAK3Cc6K$3ee95dd8e1393572da9eded23330c5db185b648552f8f72f234b9f57b9fd838b91c286e9ce0e3b511c72b348e8974518491f2b04a12a3722f46c28544f6203b4',
     'student', 'active', 2, CURRENT_TIMESTAMP),
    ('Martina', 'Díaz', 'martina.et7@gmail.com',
     'scrypt:32768:8:1$VcpYE6YsoAK3Cc6K$3ee95dd8e1393572da9eded23330c5db185b648552f8f72f234b9f57b9fd838b91c286e9ce0e3b511c72b348e8974518491f2b04a12a3722f46c28544f6203b4',
     'student', 'active', 3, CURRENT_TIMESTAMP),
    ('Tomás', 'Álvarez', 'tomas.et7@gmail.com',
     'scrypt:32768:8:1$VcpYE6YsoAK3Cc6K$3ee95dd8e1393572da9eded23330c5db185b648552f8f72f234b9f57b9fd838b91c286e9ce0e3b511c72b348e8974518491f2b04a12a3722f46c28544f6203b4',
     'student', 'active', 4, CURRENT_TIMESTAMP),
    ('Camila', 'Romero', 'camila.et7@gmail.com',
     'scrypt:32768:8:1$VcpYE6YsoAK3Cc6K$3ee95dd8e1393572da9eded23330c5db185b648552f8f72f234b9f57b9fd838b91c286e9ce0e3b511c72b348e8974518491f2b04a12a3722f46c28544f6203b4',
     'student', 'active', 5, CURRENT_TIMESTAMP),
    ('Nicolás', 'Benítez', 'nicolas.et7@gmail.com',
     'scrypt:32768:8:1$VcpYE6YsoAK3Cc6K$3ee95dd8e1393572da9eded23330c5db185b648552f8f72f234b9f57b9fd838b91c286e9ce0e3b511c72b348e8974518491f2b04a12a3722f46c28544f6203b4',
     'student', 'active', 6, CURRENT_TIMESTAMP),
    ('Agustina', 'Silva', 'agustina.et7@gmail.com',
     'scrypt:32768:8:1$VcpYE6YsoAK3Cc6K$3ee95dd8e1393572da9eded23330c5db185b648552f8f72f234b9f57b9fd838b91c286e9ce0e3b511c72b348e8974518491f2b04a12a3722f46c28544f6203b4',
     'student', 'active', 1, CURRENT_TIMESTAMP),
    ('Francisco', 'Acosta', 'francisco.et7@gmail.com',
     'scrypt:32768:8:1$VcpYE6YsoAK3Cc6K$3ee95dd8e1393572da9eded23330c5db185b648552f8f72f234b9f57b9fd838b91c286e9ce0e3b511c72b348e8974518491f2b04a12a3722f46c28544f6203b4',
     'student', 'active', 2, CURRENT_TIMESTAMP);

-- Charlas de ejemplo entre estudiantes (se muestran en la Comunidad).
INSERT OR IGNORE INTO comments (id, user_id, body, created_at)
SELECT 1, id, '¡Hola a todos! ¿Alguien tiene el resumen de Física de la semana pasada?', '2026-11-24 18:02:11'
FROM users WHERE email = 'alumno.et7@gmail.com';
INSERT OR IGNORE INTO comments (id, user_id, body, created_at)
SELECT 2, id, 'Sí, lo subí al repositorio. Está en 2.º año, materia Física.', '2026-11-24 18:07:45'
FROM users WHERE email = 'mateo.et7@gmail.com';
INSERT OR IGNORE INTO comments (id, user_id, body, created_at)
SELECT 3, id, '¡Gracias, Mateo! ¿Alguien sabe si el TP de Matemática es para el viernes?', '2026-11-25 15:30:02'
FROM users WHERE email = 'sofia.et7@gmail.com';
INSERT OR IGNORE INTO comments (id, user_id, body, created_at)
SELECT 4, id, 'Sí, es para el viernes. Yo subí mis apuntes por si les sirven.', '2026-11-25 15:41:33'
FROM users WHERE email = 'alumno.et7@gmail.com';
INSERT OR IGNORE INTO comments (id, user_id, body, created_at)
SELECT 5, id, 'Recuerden que el lunes es feriado y no hay clases.', '2026-11-26 08:10:19'
FROM users WHERE email = 'julian.et7@gmail.com';
INSERT OR IGNORE INTO comments (id, user_id, body, created_at)
SELECT 6, id, 'Buenísimo, entonces nos vemos el martes. ¡Éxitos con el TP!', '2026-11-26 08:15:47'
FROM users WHERE email = 'mateo.et7@gmail.com';

COMMIT;
