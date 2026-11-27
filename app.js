const documents = [];
const documentIndex = new Map();
let myDocuments = [];
let sharedDocuments = [];
let selectedDemo = "student";
let showOnlyMine = false;
let catalog = { years: [], divisions: [], subjects: [], shifts: [] };
let currentUser = null;
let csrfToken = "";
let toastTimer;
let lastFocusedElement;
let activeDetailDocId = null;
let pendingRejectId = null;
let publicationRequestId = 0;

const yearGrid = document.querySelector("#yearGrid");
const repositorySearch = document.querySelector("#repositorySearch");
const globalSearch = document.querySelector("#globalSearch");
const yearFilter = document.querySelector("#yearFilter");
const divisionFilter = document.querySelector("#divisionFilter");
const shiftFilter = document.querySelector("#shiftFilter");
const subjectFilter = document.querySelector("#subjectFilter");
const authGate = document.querySelector("#authGate");
const appShell = document.querySelector("#appShell");
const uploadModal = document.querySelector("#uploadModal");
const detailModal = document.querySelector("#detailModal");
const rejectModal = document.querySelector("#rejectModal");
const rejectForm = document.querySelector("#rejectForm");
const uploadForm = document.querySelector("#uploadForm");
const reportForm = document.querySelector("#reportForm");
const uploadYear = document.querySelector("#uploadYear");
const uploadDivision = document.querySelector("#uploadDivision");
const uploadShift = document.querySelector("#uploadShift");
const toast = document.querySelector("#toast");
const subjectBrowse = document.querySelector("#subjectBrowse");

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (options.method && options.method !== "GET") {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  const payload = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    if (response.status === 401 && currentUser) {
      currentUser = null;
      updateAuthUI();
      showAuthGate();
    }
    throw new Error(payload?.error || "No se pudo completar la solicitud.");
  }
  return payload;
}

function icon(id, className = "icon") {
  return `<svg class="${className}" aria-hidden="true"><use href="#${id}"></use></svg>`;
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

function setSpanishValidation(form, messages = {}) {
  form.addEventListener("invalid", (event) => {
    const field = event.target;
    if (!field.matches("input, select, textarea")) return;
    let message = messages[field.name] || "Completá este campo.";
    if (field.validity.typeMismatch && field.type === "email") {
      message = "Ingresá un correo válido.";
    } else if (field.validity.patternMismatch) {
      message = messages[`${field.name}:pattern`] || "Revisá el formato del campo.";
    } else if (field.validity.tooShort) {
      message = `Usá al menos ${field.minLength} caracteres.`;
    }
    field.setCustomValidity(message);
  }, true);
  form.addEventListener("input", (event) => event.target.setCustomValidity(""), true);
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 4200);
}

async function runAction(action) {
  try {
    return await action();
  } catch (error) {
    showToast(error.message);
    return null;
  }
}

function renderYearCards() {
  yearGrid.innerHTML = catalog.years.map((year) => `
    <button class="year-card" type="button" data-year="${year.id}" aria-label="Abrir ${year.number}º año">
      <span class="year-card-top"><span class="year-number">${year.number}º año</span><span class="year-icon">${icon("i-book")}</span></span>
      <span class="year-meta"><strong>${year.divisions} divisiones</strong> <span>·</span> Explorá sus materias</span>
    </button>
  `).join("");
}

function documentMarkup(doc, mine = false, admin = false, global = false) {
  const fileClass = doc.type === "PDF" ? "pdf" : doc.type === "PPTX" ? "ppt" : "doc";
  const status = admin
    ? '<span class="status-pill">Pendiente de revisión</span>'
    : (mine || global)
      ? `<span class="status-pill status-${escapeHTML(doc.status)}">${escapeHTML(statusLabel(doc.status))}</span>`
      : `<span class="document-tag">${doc.year}º año · ${escapeHTML(doc.division)}</span>`;
  const rejectionNote = (mine || global) && doc.status === "rejected" && doc.rejection_reason
    ? `<small class="rejection-note">Motivo del rechazo: ${escapeHTML(doc.rejection_reason)}</small>`
    : "";
  const details = global
    ? `${escapeHTML(doc.subject)} · ${doc.year}º año · ${escapeHTML(doc.division)} · ${escapeHTML(doc.author)} · ${escapeHTML(doc.date)}`
    : `${escapeHTML(doc.subject)} · ${doc.year}º año · ${escapeHTML(doc.date)}`;
  const row = `
    <button class="document-row${admin ? " admin-document-row" : ""}" type="button" data-document-id="${doc.id}"
      title="${escapeHTML(doc.title)}" aria-label="Ver detalle: ${escapeHTML(doc.title)}">
      <span class="document-icon ${fileClass}">${icon("i-file")}</span>
      <span class="document-info"><strong>${escapeHTML(doc.title)}</strong><small>${details}</small>${rejectionNote}</span>
      ${status}
      <span class="document-type">${escapeHTML(doc.type)}</span>
      ${icon("i-chevron", "icon row-arrow")}
    </button>`;
  if (!admin) return row;
  const actions = `<div class="moderation-actions">
    <button type="button" class="approve-button" data-review="approved" data-id="${doc.id}">Aprobar</button>
    <button type="button" class="reject-button" data-review="rejected" data-id="${doc.id}">Rechazar</button>
    <button type="button" class="delete-button" data-delete-publication="${doc.id}">Eliminar</button>
  </div>`;
  return `<div class="admin-entry">${row}${actions}</div>`;
}

function statusLabel(status) {
  return { pending: "Pendiente", approved: "Aprobada", rejected: "Rechazada", withdrawn: "Retirada" }[status] || status;
}

function renderDocumentList(target, list, options = {}) {
  list.forEach((doc) => documentIndex.set(String(doc.id), doc));
  if (!list.length) {
    target.innerHTML = `<div class="empty-state"><strong>${escapeHTML(options.emptyTitle || "No encontramos materiales")}</strong>${escapeHTML(options.emptyMessage || "Probá con otra búsqueda o cambiá los filtros.")}</div>`;
    return;
  }
  target.innerHTML = list.map((doc) => documentMarkup(doc, options.mine, options.admin, options.global)).join("");
}

function renderRejectedList(target, list) {
  list.forEach((doc) => documentIndex.set(String(doc.id), doc));
  if (!list.length) {
    target.innerHTML = '<div class="empty-state"><strong>No hay materiales rechazados</strong>Los materiales que rechaces quedarán registrados acá.</div>';
    return;
  }
  target.innerHTML = list.map((doc) => `
    <article class="rejected-row">
      <div>
        <strong>${escapeHTML(doc.title)}</strong>
        <small>${escapeHTML(doc.subject)} · ${doc.year}º año · ${escapeHTML(doc.division)} · ${escapeHTML(doc.author)} · ${escapeHTML(doc.date)}</small>
        <p>${doc.rejection_reason ? `Motivo: ${escapeHTML(doc.rejection_reason)}` : "Rechazado sin motivo indicado."}</p>
      </div>
      <div class="rejected-actions">
        <span class="status-pill status-rejected">Rechazada</span>
        <button type="button" class="delete-button" data-delete-publication="${doc.id}">Eliminar</button>
      </div>
    </article>
  `).join("");
}

function populateYearOptions(select, placeholder) {
  select.innerHTML = `<option value="">${placeholder}</option>` + catalog.years
    .map((year) => `<option value="${year.id}">${year.number}º año</option>`).join("");
}

function divisionsForYear(yearId) {
  return catalog.divisions.filter((division) => !yearId || String(division.year_id) === String(yearId));
}

function populateDivisionOptions(select, yearId, placeholder, includeAllYears = false, shiftId = "") {
  if (!includeAllYears && !yearId) {
    select.innerHTML = '<option value="">Elegí un año primero</option>';
    select.disabled = true;
    return;
  }
  const divisions = divisionsForYear(yearId).filter(
    (division) => !shiftId || String(division.shift_id) === String(shiftId)
  );
  select.innerHTML = `<option value="">${placeholder}</option>` + divisions.map((division) => {
    const year = catalog.years.find((item) => item.id === division.year_id);
    const shift = catalog.shifts.find((item) => String(item.id) === String(division.shift_id));
    return `<option value="${division.id}">${year.number}º año · División ${division.number}${shift ? ` · ${escapeHTML(shift.name)}` : ""}</option>`;
  }).join("");
  select.disabled = false;
}

function subjectsForYear(yearId) {
  return catalog.subjects.filter((subject) => !yearId || String(subject.year_id) === String(yearId));
}

function uniqueSubjectsByName(subjects) {
  const seen = new Set();
  return subjects.filter((subject) => {
    const key = subject.name.trim().toLocaleLowerCase("es");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function renderSubjectBrowse(subjects, selectedId) {
  const hint = document.querySelector("#subjectBrowseHint");
  const year = catalog.years.find((item) => String(item.id) === String(yearFilter.value));
  if (!year) {
    hint.textContent = "Elegí un año para ver sus materias";
    subjectBrowse.innerHTML = "";
    return;
  }
  hint.textContent = `Materias de ${year.number}º año · ${uniqueSubjectsByName(subjects).length}`;
  subjectBrowse.innerHTML = [
    `<button class="subject-chip${selectedId ? "" : " active"}" type="button" data-subject-choice="">Todas</button>`,
    ...uniqueSubjectsByName(subjects).map((subject) => `<button class="subject-chip${String(selectedId) === String(subject.id) ? " active" : ""}" type="button" data-subject-choice="${subject.id}">${escapeHTML(subject.name)}</button>`)
  ].join("");
}

function populateSubjectOptions(yearId, select, placeholder) {
  if (!yearId) {
    select.innerHTML = '<option value="">Elegí un año primero</option>';
    select.disabled = true;
    return;
  }
  select.innerHTML = `<option value="">${placeholder}</option>` + uniqueSubjectsByName(subjectsForYear(yearId))
    .map((subject) => `<option value="${subject.id}">${escapeHTML(subject.name)}</option>`).join("");
  select.disabled = false;
}

function populateShiftOptions(select, selectedShiftId = "", placeholder = "Seleccioná un turno") {
  select.innerHTML = `<option value="">${placeholder}</option>` + catalog.shifts
    .map((shift) => `<option value="${shift.id}">${escapeHTML(shift.name)}</option>`).join("");
  if (selectedShiftId) select.value = String(selectedShiftId);
}

function updateUploadDivisions() {
  const yearId = uploadYear.value;
  const shiftId = uploadShift.value;
  const ready = Boolean(yearId && shiftId);
  const divisions = ready
    ? divisionsForYear(yearId).filter((division) => String(division.shift_id) === String(shiftId))
    : [];
  uploadDivision.innerHTML = `<option value="">${ready ? "Seleccioná una división" : "Elegí turno primero"}</option>`
    + divisions.map((division) => `<option value="${division.id}">División ${division.number}</option>`).join("");
  uploadDivision.disabled = !ready;
}

function updateUploadShift() {
  updateUploadDivisions();
  document.querySelector("#uploadShiftHelp").textContent = uploadShift.value
    ? "Las divisiones se filtran según el turno elegido."
    : "Elegí el turno para habilitar las divisiones.";
}

function renderCatalog() {
  renderYearCards();
  populateYearOptions(yearFilter, "Todos los años");
  populateYearOptions(uploadYear, "Seleccioná un año");
  populateYearOptions(document.querySelector("#registerYear"), "Seleccioná un año");
  populateDivisionOptions(divisionFilter, "", "Todas las divisiones", true);
  populateDivisionOptions(document.querySelector("#registerDivision"), "", "Seleccioná una división");
  populateSubjectOptions("", subjectFilter, "Todas las materias");
  populateSubjectOptions("", uploadForm.elements.subject, "Seleccioná una materia");
  populateShiftOptions(shiftFilter, "", "Todos los turnos");
  populateShiftOptions(uploadShift);
  uploadShift.disabled = false;
  updateUploadDivisions();
  renderSubjectBrowse(subjectsForYear(""), "");
}

async function refreshPublications() {
  const requestId = ++publicationRequestId;
  const query = repositorySearch.value.trim();
  const params = new URLSearchParams();
  if (query) params.set("q", query);
  if (yearFilter.value) params.set("year_id", yearFilter.value);
  if (divisionFilter.value) params.set("division_id", divisionFilter.value);
  if (shiftFilter.value) params.set("shift_id", shiftFilter.value);
  if (subjectFilter.value) params.set("subject_id", subjectFilter.value);
  params.set("limit", "200");
  const rows = await api(`/api/publications?${params}`);
  if (requestId !== publicationRequestId) return;
  documents.splice(0, documents.length, ...rows);
  renderDocumentList(document.querySelector("#repositoryDocuments"), documents);
  document.querySelector("#resultCount").textContent = `${documents.length} ${documents.length === 1 ? "material" : "materiales"}`;
  const recent = await api("/api/publications?limit=4");
  if (requestId !== publicationRequestId) return;
  renderDocumentList(document.querySelector("#recentDocuments"), recent, {
    emptyTitle: "Todavía no hay materiales aprobados",
    emptyMessage: "Cuando un administrador apruebe una publicación, aparecerá acá."
  });
}

async function refreshMine() {
  const target = document.querySelector("#myDocuments");
  if (!currentUser) {
    renderDocumentList(target, [], {
      emptyTitle: "Iniciá sesión para ver tus publicaciones",
      emptyMessage: "Entrá a Mi perfil para acceder a tu cuenta."
    });
    document.querySelector("#publicationCount").textContent = "";
    return;
  }
  myDocuments = await api("/api/publications/mine");
  renderDocumentList(target, myDocuments, {
    mine: true,
    emptyTitle: "Todavía no compartiste materiales",
    emptyMessage: "Podés elegir un año, una materia y un archivo para compartir tus apuntes."
  });
  document.querySelector("#publicationCount").textContent =
    `${myDocuments.length} ${myDocuments.length === 1 ? "publicación tuya" : "publicaciones tuyas"}`;
}

async function refreshSharedPublications() {
  if (showOnlyMine) return refreshMine();
  const target = document.querySelector("#myDocuments");
  sharedDocuments = await api("/api/publications/shared");
  renderDocumentList(target, sharedDocuments, {
    global: true,
    emptyTitle: "Todavía no hay publicaciones",
    emptyMessage: "Cuando se compartan apuntes, aparecerán acá."
  });
  document.querySelector("#publicationCount").textContent =
    `${sharedDocuments.length} ${sharedDocuments.length === 1 ? "apunte compartido" : "apuntes compartidos"}`;
}

async function refreshAdmin() {
  const target = document.querySelector("#adminDocuments");
  const pending = await api("/api/admin/publications?status=pending");
  const rejected = await api("/api/admin/publications?status=rejected");
  const reports = await api("/api/admin/reports");
  renderDocumentList(target, pending, {
    admin: true,
    emptyTitle: "No hay publicaciones pendientes",
    emptyMessage: "Las nuevas publicaciones aparecerán aquí para su revisión."
  });
  renderRejectedList(document.querySelector("#adminRejected"), rejected);
  document.querySelector("#rejectedCount").textContent = `${rejected.length} ${rejected.length === 1 ? "rechazado" : "rechazados"}`;
  document.querySelector("#pendingCount").textContent = `${pending.length} ${pending.length === 1 ? "publicación pendiente" : "publicaciones pendientes"} · ${reports.length} ${reports.length === 1 ? "reporte" : "reportes"}`;
  renderAdminReports(reports);
}

function renderAdminReports(reports) {
  const target = document.querySelector("#adminReports");
  if (!reports.length) {
    target.innerHTML = '<div class="empty-state"><strong>No hay reportes pendientes</strong>Los reportes de estudiantes aparecerán acá.</div>';
    return;
  }
  target.innerHTML = reports.map((report) => `
    <article class="report-row">
      <div><strong>${escapeHTML(report.publication_title)}</strong><small>${escapeHTML(report.reason_label)} · ${escapeHTML(report.reporter_name)} · ${escapeHTML(report.created_at)}</small>${report.details ? `<p>${escapeHTML(report.details)}</p>` : ""}</div>
      <button class="secondary-button resolve-report" type="button" data-report-id="${report.id}">Marcar revisado</button>
    </article>
  `).join("");
}

function formatChatDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!match) return String(value || "");
  return `${match[3]}/${match[2]}/${match[1]} · ${match[4]}:${match[5]}`;
}

function roleLabel(role) {
  return role === "admin" ? "Administrador" : "Alumno";
}

function renderComments(comments) {
  const target = document.querySelector("#communityMessages");
  document.querySelector("#commentCount").textContent =
    `${comments.length} ${comments.length === 1 ? "mensaje" : "mensajes"}`;
  if (!comments.length) {
    target.innerHTML = '<div class="empty-state"><strong>Todavía no hay mensajes</strong>¡Escribí el primero para romper el hielo!</div>';
    return;
  }
  target.innerHTML = comments.map((comment) => {
    const mine = currentUser && comment.author_id === currentUser.id;
    const initial = (comment.author || "?").trim().charAt(0).toUpperCase();
    const deleteButton = currentUser?.role === "admin"
      ? `<button type="button" class="chat-delete" data-delete-comment="${comment.id}">Eliminar</button>`
      : "";
    return `
      <article class="chat-message${mine ? " mine" : ""}">
        <div class="avatar chat-avatar">${escapeHTML(initial)}</div>
        <div class="chat-bubble">
          <div class="chat-meta">
            <strong>${escapeHTML(comment.author)}</strong>
            <span class="role-chip${comment.role === "admin" ? " role-admin" : ""}">${roleLabel(comment.role)}</span>
            <time datetime="${escapeHTML(comment.created_at)}">${formatChatDate(comment.created_at)}</time>
            ${deleteButton}
          </div>
          <p>${escapeHTML(comment.body)}</p>
        </div>
      </article>`;
  }).join("");
  target.scrollTop = target.scrollHeight;
}

async function refreshComments() {
  const comments = await api("/api/comments");
  renderComments(comments);
}

async function deleteComment(commentId) {
  if (!window.confirm("¿Eliminar este mensaje de la comunidad? Solo el administrador puede controlar los mensajes.")) {
    return false;
  }
  await api(`/api/comments/${commentId}`, { method: "DELETE" });
  showToast("Mensaje eliminado.");
  await refreshComments();
  return true;
}

function renderStudents(students) {
  const target = document.querySelector("#studentGrid");
  document.querySelector("#studentCount").textContent =
    `${students.length} ${students.length === 1 ? "alumno" : "alumnos"}`;
  if (!students.length) {
    target.innerHTML = '<div class="empty-state"><strong>No hay alumnos registrados</strong>Las nuevas cuentas aparecerán acá.</div>';
    return;
  }
  target.innerHTML = students.map((student) => {
    const year = student.year ? `${student.year}.º año` : "Sin año asignado";
    const email = student.email ? `<small class="student-email">${escapeHTML(student.email)}</small>` : "";
    const statusClass = student.status === "active" ? "status-approved"
      : student.status === "pending" ? "" : "status-withdrawn";
    const deleteButton = currentUser?.role === "admin"
      ? `<button class="student-delete" type="button" data-delete-student="${student.id}" data-student-name="${escapeHTML(student.name)}">Eliminar</button>`
      : "";
    return `
      <article class="student-card">
        <div class="avatar student-avatar">${escapeHTML((student.first_name || "?").charAt(0).toUpperCase())}</div>
        <div class="student-info">
          <strong>${escapeHTML(student.name)}</strong>
          <small>${escapeHTML(year)} · Alumno</small>
          ${email}
        </div>
        <div class="student-actions">
          <span class="status-pill ${statusClass}">${escapeHTML(student.status_label || student.status)}</span>
          ${deleteButton}
        </div>
      </article>`;
  }).join("");
}

async function refreshStudents() {
  const students = await api("/api/students");
  renderStudents(students);
}

async function deleteStudent(studentId, studentName) {
  if (!window.confirm(`¿Eliminar la cuenta de ${studentName}? También se borrarán sus mensajes de la Comunidad. Esta acción no se puede deshacer.`)) {
    return false;
  }
  await api(`/api/students/${studentId}`, { method: "DELETE" });
  showToast(`${studentName} fue eliminado de los alumnos.`);
  await Promise.all([refreshStudents(), refreshComments()]);
  return true;
}

function showAuthGate() {
  authGate.hidden = false;
  appShell.hidden = true;
  document.body.style.overflow = "";
  switchAuthTab("login");
}

function enterApp() {
  authGate.hidden = true;
  appShell.hidden = false;
}

function updateAuthUI() {
  const isLoggedIn = Boolean(currentUser);
  const mineToggle = document.querySelector("#onlyMineToggle");
  mineToggle.closest("label").hidden = !isLoggedIn;
  if (!isLoggedIn) {
    mineToggle.checked = false;
    showOnlyMine = false;
  }
  document.querySelector("#signedInPanel").hidden = !isLoggedIn;
  document.querySelector("#profileNote").hidden = isLoggedIn;
  document.querySelector("#adminNav").hidden = currentUser?.role !== "admin";
  const initial = currentUser ? currentUser.first_name[0].toUpperCase() : "E";
  document.querySelector("#profileInitial").textContent = initial;
  document.querySelector("#sidebarAvatar").textContent = initial;
  document.querySelector("#chatAvatar").textContent = initial;
  document.querySelector("#profileName").textContent = currentUser ? `${currentUser.first_name} ${currentUser.last_name}` : "";
  document.querySelector("#profileEmail").textContent = currentUser?.email || "";
  document.querySelector("#profileRole").textContent = currentUser?.role === "admin" ? "Administrador" : "Alumno";
  document.querySelector(".profile-mini strong").textContent = currentUser ? currentUser.first_name : "Estudiante";
  document.querySelector(".profile-mini small").textContent = currentUser ? (currentUser.role === "admin" ? "Administrador" : "Alumno") : "Sesión activa";
  document.querySelector("#greetingTitle").innerHTML =
    `Hola, ${escapeHTML(currentUser?.first_name || "estudiante")} <span class="wave">✦</span>`;
  document.querySelectorAll(".profile-button").forEach((button) => {
    button.textContent = initial;
  });
}

function applyDemoCredentials(demo) {
  const emailInput = document.querySelector("#loginForm input[name='email']");
  const passwordInput = document.querySelector("#loginForm input[name='password']");
  emailInput.value = demo.email;
  passwordInput.value = demo.password;
  selectedDemo = demo.role;
  document.querySelectorAll(".demo-account").forEach((row) => {
    row.classList.toggle("selected", row.dataset.demoRole === demo.role);
  });
}

function demoCredentials(role) {
  return role === "admin"
    ? { role: "admin", email: "admin.et7@gmail.com", password: "AdminET7.2026" }
    : { role: "student", email: "alumno.et7@gmail.com", password: "AlumnoET7.2026" };
}

function switchAuthTab(tab) {
  const login = tab === "login";
  document.querySelector("#loginTab").classList.toggle("active", login);
  document.querySelector("#registerTab").classList.toggle("active", !login);
  document.querySelector("#loginTab").setAttribute("aria-selected", String(login));
  document.querySelector("#registerTab").setAttribute("aria-selected", String(!login));
  document.querySelector("#loginForm").hidden = !login;
  document.querySelector("#registerForm").hidden = login;
}

function switchSection(section) {
  const sections = {
    home: "homeView", repository: "repositoryView", mine: "mineView",
    community: "communityView", students: "studentsView", profile: "profileView", admin: "adminView"
  };
  if (!sections[section] || (section === "admin" && currentUser?.role !== "admin")) return;
  Object.entries(sections).forEach(([key, id]) => {
    const view = document.getElementById(id);
    const active = key === section;
    view.classList.toggle("active", active);
    view.hidden = !active;
  });
  document.querySelectorAll(".nav-link[data-section]").forEach((button) => {
    button.classList.toggle("active", button.dataset.section === section);
  });
  document.querySelector("#breadcrumbCurrent").textContent = {
    home: "Inicio", repository: "Repositorio", mine: "Apuntes compartidos",
    community: "Comunidad", students: "Alumnos", profile: "Mi perfil", admin: "Moderación"
  }[section];
  document.querySelector("#sidebar").classList.remove("open");
  document.querySelector("#menuToggle").setAttribute("aria-expanded", "false");
  if (section === "repository") runAction(refreshPublications);
  if (section === "mine") runAction(refreshSharedPublications);
  if (section === "admin") runAction(refreshAdmin);
  if (section === "community") runAction(refreshComments);
  if (section === "students") runAction(refreshStudents);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function openModal() {
  if (!currentUser) {
    showAuthGate();
    showToast("Iniciá sesión para compartir un material.");
    document.querySelector("#loginForm input[name='email']").focus();
    return;
  }
  lastFocusedElement = document.activeElement;
  uploadModal.hidden = false;
  document.body.style.overflow = "hidden";
  uploadYear.focus();
}

function closeModal() {
  const returnFocus = lastFocusedElement;
  uploadModal.hidden = true;
  document.body.style.overflow = "";
  uploadForm.reset();
  document.querySelector("#fileName").textContent = "Elegí un archivo para compartir";
  populateSubjectOptions("", uploadForm.elements.subject, "Seleccioná una materia");
  updateUploadShift();
  returnFocus?.focus();
}

function renderDetailPreview(doc, canViewFile) {
  const preview = document.querySelector("#detailPreview");
  preview.replaceChildren();
  preview.hidden = true;
  if (!canViewFile) return;
  const source = doc.preview_url || doc.file_url;
  if (["JPG", "JPEG", "PNG"].includes(doc.type)) {
    const image = document.createElement("img");
    image.src = source;
    image.alt = `Vista previa de ${doc.title}`;
    image.loading = "lazy";
    preview.append(image);
    preview.hidden = false;
  } else if (doc.type === "PDF") {
    const frame = document.createElement("iframe");
    frame.src = source;
    frame.title = `Vista previa de ${doc.title}`;
    preview.append(frame);
    preview.hidden = false;
  } else {
    const note = document.createElement("p");
    note.className = "preview-note";
    note.textContent = `La vista previa no está disponible para archivos ${doc.type}. Descargá el material para abrirlo.`;
    preview.append(note);
    preview.hidden = false;
  }
}

function openDetail(doc) {
  if (!doc) return;
  lastFocusedElement = document.activeElement;
  activeDetailDocId = doc.id;
  document.querySelector("#detailTitle").textContent = doc.title;
  const metadata = document.querySelector("#detailMeta");
  metadata.replaceChildren();
  [
    ["Materia", doc.subject], ["Año", `${doc.year}º año`], ["División", doc.division],
    ["Turno", doc.shift], ["Formato", doc.type], ["Compartido", doc.date], ["Autor", doc.author]
  ].forEach(([label, value]) => {
    const item = document.createElement("div");
    const term = document.createElement("small");
    const description = document.createElement("strong");
    term.textContent = label;
    description.textContent = value;
    item.append(term, description);
    metadata.append(item);
  });
  const download = document.querySelector("#downloadMaterial");
  const canViewFile = Boolean(currentUser && doc.file_url && (
    doc.status === "approved" || doc.author_id === currentUser.id || currentUser.role === "admin"
  ));
  download.hidden = !canViewFile;
  download.href = canViewFile ? doc.file_url : "#";
  renderDetailPreview(doc, canViewFile);
  const deleteButton = document.querySelector("#deleteMaterial");
  deleteButton.hidden = currentUser?.role !== "admin";
  deleteButton.dataset.id = doc.id;
  document.querySelector("#downloadNote").hidden = canViewFile || !doc.file_url || !currentUser;
  document.querySelector("#reportToggle").hidden = !currentUser || doc.status === "pending" || doc.status === "rejected";
  document.querySelector(".detail-demo-note").hidden = Boolean(doc.file_url);
  reportForm.hidden = true;
  reportForm.reset();
  detailModal.hidden = false;
  document.body.style.overflow = "hidden";
  document.querySelector("[data-close-detail]").focus();
}

function closeDetail() {
  const returnFocus = lastFocusedElement;
  detailModal.hidden = true;
  document.body.style.overflow = "";
  activeDetailDocId = null;
  document.querySelector("#detailPreview").replaceChildren();
  document.querySelector("#detailPreview").hidden = true;
  reportForm.reset();
  reportForm.hidden = true;
  returnFocus?.focus();
}

async function deletePublication(publicationId) {
  const doc = documentIndex.get(String(publicationId)) || [...documents, ...myDocuments, ...sharedDocuments].find(
    (item) => String(item.id) === String(publicationId)
  );
  const label = doc ? `“${doc.title}”` : "esta publicación";
  if (!window.confirm(`¿Eliminar ${label}? Se borrarán el archivo y sus reportes. Esta acción no se puede deshacer.`)) {
    return false;
  }
  await api(`/api/admin/publications/${publicationId}`, { method: "DELETE" });
  showToast("Publicación eliminada.");
  if (String(activeDetailDocId) === String(publicationId)) closeDetail();
  await Promise.all([refreshAdmin(), refreshPublications(), refreshSharedPublications()]);
  return true;
}

function openRejectModal(publicationId) {
  pendingRejectId = publicationId;
  lastFocusedElement = document.activeElement;
  rejectForm.reset();
  rejectModal.hidden = false;
  document.body.style.overflow = "hidden";
  rejectForm.elements.reason.focus();
}

function closeRejectModal() {
  const returnFocus = lastFocusedElement;
  rejectModal.hidden = true;
  document.body.style.overflow = "";
  pendingRejectId = null;
  returnFocus?.focus();
}

async function loadInitialData() {
  const sessionData = await api("/api/session");
  csrfToken = sessionData.csrf_token;
  currentUser = sessionData.user;
  const initialCatalog = await api("/api/catalog");
  catalog = initialCatalog;
  renderCatalog();
  updateAuthUI();
  document.querySelector("#connectionLabel").textContent = "Conectado";
  if (!currentUser) {
    showAuthGate();
    return;
  }
  enterApp();
  await refreshPublications();
}

document.addEventListener("click", (event) => {
  const sectionButton = event.target.closest("[data-section]");
  if (sectionButton) {
    event.preventDefault();
    switchSection(sectionButton.dataset.section);
  }
  if (event.target.closest("[data-open-upload]")) openModal();
  if (event.target.closest("[data-close-modal]")) closeModal();
  if (event.target.closest("[data-close-detail]")) closeDetail();
  const demoAccount = event.target.closest("[data-demo-email]");
  if (demoAccount) {
    switchAuthTab("login");
    applyDemoCredentials({
      role: demoAccount.dataset.demoRole,
      email: demoAccount.dataset.demoEmail,
      password: demoAccount.dataset.demoPassword
    });
    document.querySelector("#loginForm button[type='submit']").focus();
    showToast("Credenciales de prueba completadas. Tocá “Iniciar sesión”.");
  } else {
    const demoRow = event.target.closest(".demo-account[data-demo-role]");
    if (demoRow) {
      switchAuthTab("login");
      applyDemoCredentials(demoCredentials(demoRow.dataset.demoRole));
      showToast("Perfil de prueba seleccionado. Tocá “Iniciar sesión”.");
    }
  }
  const deletePublicationButton = event.target.closest("[data-delete-publication]");
  if (deletePublicationButton) {
    runAction(() => deletePublication(deletePublicationButton.dataset.deletePublication));
  }
  const deleteCommentButton = event.target.closest("[data-delete-comment]");
  if (deleteCommentButton) {
    runAction(() => deleteComment(deleteCommentButton.dataset.deleteComment));
  }
  const deleteStudentButton = event.target.closest("[data-delete-student]");
  if (deleteStudentButton) {
    runAction(() => deleteStudent(
      deleteStudentButton.dataset.deleteStudent,
      deleteStudentButton.dataset.studentName
    ));
  }
  const documentButton = event.target.closest("[data-document-id]");
  if (documentButton) {
    openDetail(documentIndex.get(documentButton.dataset.documentId));
  }
  const yearCard = event.target.closest("[data-year]");
  if (yearCard) {
    yearFilter.value = yearCard.dataset.year;
    yearFilter.dispatchEvent(new Event("change"));
    switchSection("repository");
  }
  const subjectChip = event.target.closest("[data-subject-choice]");
  if (subjectChip) {
    subjectFilter.value = subjectChip.dataset.subjectChoice;
    renderSubjectBrowse(subjectsForYear(yearFilter.value), subjectFilter.value);
    runAction(refreshPublications);
  }
  const reviewButton = event.target.closest("[data-review]");
  if (reviewButton) {
    if (reviewButton.dataset.review === "rejected") {
      openRejectModal(reviewButton.dataset.id);
    } else {
      runAction(async () => {
        await api(`/api/admin/publications/${reviewButton.dataset.id}`, {
          method: "PATCH",
          body: JSON.stringify({ status: "approved" })
        });
        showToast("Publicación aprobada.");
        await refreshAdmin();
        await refreshPublications();
      });
    }
  }
  const reportButton = event.target.closest("[data-report-id]");
  if (reportButton) {
    runAction(async () => {
      await api(`/api/admin/reports/${reportButton.dataset.reportId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "reviewed" })
      });
      showToast("Reporte marcado como revisado.");
      await refreshAdmin();
    });
  }
});

document.querySelector("#menuToggle").addEventListener("click", () => {
  const sidebar = document.querySelector("#sidebar");
  const isOpen = sidebar.classList.toggle("open");
  document.querySelector("#menuToggle").setAttribute("aria-expanded", String(isOpen));
});

document.querySelector("#globalSearchForm").addEventListener("submit", (event) => {
  event.preventDefault();
  repositorySearch.value = globalSearch.value;
  switchSection("repository");
});
document.querySelector("#repositorySearchForm").addEventListener("submit", (event) => event.preventDefault());
repositorySearch.addEventListener("input", () => runAction(refreshPublications));
yearFilter.addEventListener("change", () => {
  populateDivisionOptions(divisionFilter, yearFilter.value, "Todas las divisiones", true, shiftFilter.value);
  populateSubjectOptions(yearFilter.value, subjectFilter, "Todas las materias");
  renderSubjectBrowse(subjectsForYear(yearFilter.value), "");
  runAction(refreshPublications);
});
divisionFilter.addEventListener("change", () => runAction(refreshPublications));
shiftFilter.addEventListener("change", () => {
  populateDivisionOptions(divisionFilter, yearFilter.value, "Todas las divisiones", true, shiftFilter.value);
  runAction(refreshPublications);
});
subjectFilter.addEventListener("change", () => {
  renderSubjectBrowse(subjectsForYear(yearFilter.value), subjectFilter.value);
  runAction(refreshPublications);
});

document.querySelector("#clearFilters").addEventListener("click", () => {
  repositorySearch.value = "";
  yearFilter.value = "";
  divisionFilter.value = "";
  shiftFilter.value = "";
  subjectFilter.value = "";
  populateDivisionOptions(divisionFilter, "", "Todas las divisiones", true);
  populateSubjectOptions("", subjectFilter, "Todas las materias");
  renderSubjectBrowse(subjectsForYear(""), "");
  runAction(refreshPublications);
  repositorySearch.focus();
});

document.querySelector("#onlyMineToggle").addEventListener("change", (event) => {
  showOnlyMine = event.target.checked;
  sharedDocuments = [];
  runAction(refreshSharedPublications);
});

document.querySelector("#loginTab").addEventListener("click", () => switchAuthTab("login"));
document.querySelector("#registerTab").addEventListener("click", () => switchAuthTab("register"));

const loginEmailInput = document.querySelector("#loginForm input[name='email']");
const loginPasswordInput = document.querySelector("#loginForm input[name='password']");
[loginEmailInput, loginPasswordInput].forEach((field) => {
  field.addEventListener("focus", () => {
    if (authGate.hidden) return;
    if (!loginEmailInput.value.trim() && !loginPasswordInput.value.trim()) {
      applyDemoCredentials(demoCredentials(selectedDemo));
      document.querySelector("#authDemoHint").textContent =
        "Datos de prueba completados. Podés iniciar sesión o escribir otra cuenta.";
    }
  });
});
document.querySelector("#deleteMaterial").addEventListener("click", () => {
  const publicationId = document.querySelector("#deleteMaterial").dataset.id;
  if (publicationId) runAction(() => deletePublication(publicationId));
});
setSpanishValidation(document.querySelector("#loginForm"), {
  email: "Ingresá tu correo electrónico.",
  password: "Ingresá tu contraseña."
});
setSpanishValidation(document.querySelector("#registerForm"), {
  first_name: "Ingresá tu nombre.",
  last_name: "Ingresá tu apellido.",
  email: "Ingresá tu correo electrónico.",
  "email:pattern": "El correo debe incluir .et7 (ejemplo: alumno.et7@gmail.com).",
  password: "Ingresá una contraseña.",
  year_id: "Elegí un año.",
  division_id: "Elegí una división.",
  policy_accepted: "Tenés que aceptar las normas de convivencia."
});
setSpanishValidation(document.querySelector("#uploadForm"), {
  year: "Elegí un año.",
  shift_id: "Elegí un turno.",
  division: "Elegí una división.",
  subject: "Elegí una materia.",
  file: "Elegí un archivo para compartir."
});
document.querySelector("#registerYear").addEventListener("change", () => {
  populateDivisionOptions(document.querySelector("#registerDivision"), document.querySelector("#registerYear").value, "Seleccioná una división");
});

document.querySelector("#loginForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  runAction(async () => {
    const form = Object.fromEntries(new FormData(formElement));
    const response = await api("/api/login", { method: "POST", body: JSON.stringify(form) });
    csrfToken = response.csrf_token;
    currentUser = response.user;
    updateAuthUI();
    formElement.reset();
    enterApp();
    await refreshPublications();
    showToast("Inicio de sesión correcto. ¡Hola, " + currentUser.first_name + "!");
    switchSection("home");
  });
});

document.querySelector("#registerForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  runAction(async () => {
    const form = new FormData(formElement);
    const response = await api("/api/register", {
      method: "POST",
      body: JSON.stringify({
        first_name: form.get("first_name"),
        last_name: form.get("last_name"),
        email: form.get("email"),
        password: form.get("password"),
        year_id: form.get("year_id"),
        division_id: form.get("division_id"),
        policy_accepted: form.get("policy_accepted") === "on"
      })
    });
    csrfToken = response.csrf_token;
    currentUser = response.user;
    updateAuthUI();
    formElement.reset();
    enterApp();
    await refreshPublications();
    showToast("Tu cuenta quedó creada.");
    switchSection("home");
  });
});

document.querySelector("#logoutButton").addEventListener("click", () => runAction(async () => {
  const response = await api("/api/logout", { method: "POST" });
  csrfToken = response.csrf_token;
  currentUser = null;
  myDocuments = [];
  updateAuthUI();
  showToast("Cerraste sesión.");
  switchSection("home");
  showAuthGate();
}));

document.querySelector("#notificationButton").addEventListener("click", () => {
  showToast(currentUser ? "Las notificaciones se mostrarán cuando haya novedades." : "Iniciá sesión para ver tus novedades.");
});
document.querySelector("#reportToggle").addEventListener("click", () => {
  reportForm.hidden = false;
  reportForm.elements.reason.focus();
});
document.querySelector("#cancelReport").addEventListener("click", () => {
  reportForm.reset();
  reportForm.hidden = true;
  document.querySelector("#reportToggle").focus();
});
reportForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!reportForm.reportValidity() || !activeDetailDocId) return;
  runAction(async () => {
    await api(`/api/publications/${activeDetailDocId}/reports`, {
      method: "POST",
      body: JSON.stringify({
        reason: reportForm.elements.reason.value,
        details: reportForm.elements.details.value
      })
    });
    closeDetail();
    showToast("Reporte enviado al equipo administrador.");
  });
});

uploadYear.addEventListener("change", () => {
  populateSubjectOptions(uploadYear.value, uploadForm.elements.subject, "Seleccioná una materia");
  updateUploadDivisions();
});
uploadShift.addEventListener("change", updateUploadShift);
document.querySelector("#uploadFile").addEventListener("change", (event) => {
  document.querySelector("#fileName").textContent = event.target.files[0]?.name || "Elegí un archivo para compartir";
});

uploadForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!uploadForm.reportValidity()) return;
  const file = document.querySelector("#uploadFile").files[0];
  if (!file) return;
  if (!uploadShift.value) {
    showToast("Elegí el turno en el que cursa la división.");
    return;
  }
  const form = new FormData();
  form.set("file", file);
  form.set("year_id", uploadYear.value);
  form.set("division_id", uploadDivision.value);
  form.set("shift_id", uploadShift.value);
  form.set("subject_id", uploadForm.elements.subject.value);
  form.set("title", uploadForm.elements.title.value);
  runAction(async () => {
    await api("/api/publications", { method: "POST", body: form });
    closeModal();
    await refreshSharedPublications();
    showToast("Material enviado. Quedó pendiente de revisión.");
    switchSection("mine");
  });
});

document.querySelector("#uploadModal").addEventListener("click", (event) => {
  if (event.target === uploadModal) closeModal();
});
detailModal.addEventListener("click", (event) => {
  if (event.target === detailModal) closeDetail();
});
rejectModal.addEventListener("click", (event) => {
  if (event.target === rejectModal) closeRejectModal();
});
document.querySelector("#cancelReject").addEventListener("click", closeRejectModal);
document.querySelector("#cancelRejectTop").addEventListener("click", closeRejectModal);
rejectForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!pendingRejectId) return;
  const publicationId = pendingRejectId;
  const reason = rejectForm.elements.reason.value.trim();
  runAction(async () => {
    await api(`/api/admin/publications/${publicationId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "rejected", rejection_reason: reason })
    });
    closeRejectModal();
    showToast("Publicación rechazada.");
    await refreshAdmin();
    await refreshPublications();
  });
});
document.addEventListener("keydown", (event) => {
  const openModal = !rejectModal.hidden ? rejectModal
    : !detailModal.hidden ? detailModal
      : !uploadModal.hidden ? uploadModal : null;
  if (!openModal) return;
  if (event.key === "Escape") {
    event.preventDefault();
    if (openModal === rejectModal) closeRejectModal();
    else if (openModal === detailModal) closeDetail();
    else closeModal();
    return;
  }
  if (event.key === "Tab") {
    const focusable = [...openModal.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]:not([hidden])')]
      .filter((element) => !element.hidden && element.getClientRects().length);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});

document.querySelector("#commentForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  const body = formElement.elements.body.value.trim();
  if (!body) {
    showToast("Escribí un mensaje antes de enviarlo.");
    return;
  }
  runAction(async () => {
    await api("/api/comments", { method: "POST", body: JSON.stringify({ body }) });
    formElement.reset();
    document.querySelector("#chatAvatar").textContent = currentUser?.first_name?.[0]?.toUpperCase() || "E";
    await refreshComments();
    showToast("Mensaje enviado.");
    formElement.elements.body.focus();
  });
});

setInterval(() => {
  if (!currentUser) return;
  const communityView = document.getElementById("communityView");
  if (communityView && !communityView.hidden) runAction(refreshComments);
}, 12000);

loadInitialData().catch((error) => {
  console.error(error);
  document.querySelector("#connectionLabel").textContent = "Sin conexión";
  showToast("No se pudo conectar con Flask. Iniciá el servidor y abrí http://127.0.0.1:5000.");
  document.querySelector("#repositoryDocuments").innerHTML =
    '<div class="empty-state"><strong>No hay conexión con el servidor</strong>Iniciá Flask desde la carpeta del proyecto y volvé a cargar esta página.</div>';
});
