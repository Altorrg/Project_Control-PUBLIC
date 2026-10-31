"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
    user: null,
    projects: [],
    project: null,
    selectedProjectId: null,
    applicationDate: null,
    activeDiscipline: null,
    scheduleView: "phases",
    scheduleFinancialPhase: null,
    ganttZoom: "daily",
    scheduleAutoCalculate: true,
    scheduleSettings: null,
    scheduleTimeline: null,
    subcontractorView: "offers",
    subcontractorSearch: "",
    subcontractorCatalog: { folders: [], subcontractors: [], categories: [] },
    workflowPanelWorkflowId: null,
    workflowPanelStep: 1,
    workflowPanelDocumentOpen: false,
    workflowPanelWidth: 460,
    matrixZoom: 1,
    financeView: "dashboard",
    settingsView: "project",
    module: "settings",
    master: null,
    engagementDisciplines: [],
    notifications: [],
    todayTasks: [],
    taskHistory: [],
    notificationsAnnounced: false,
    notificationRefreshTimer: null,
    searchTimer: null,
    performanceScope: null,
    apiRequestSequence: 0,
    navigationVersion: 0,
    viewRenderVersion: 0,
    assignmentRenderVersion: 0,
    aiAssistant: { open: false, sending: false, messages: [], lastMessage: "" },
};

const moduleLabels = {
    disciplines: ["Szakági napi adatok", "Teljesítés és ráfordítás"],
    schedule: ["Ütemterv", "Tervezési és pénzügyi mérföldkövek"],
    subcontractors: ["Alvállalkozók", "Szerződéses folyamatok"],
    finance: ["Pénzügy", "Keretek, költségek és kifizetések"],
    engagements: ["Engedélyezés", "Ügyek, partnerek és jóváhagyások"],
    settings: ["Adatok", "Adatlap és projektstruktúra"],
    admin: ["Admin központ", "Felhasználók és jóváhagyások"],
};

function beginViewRender(module) {
    if (state.module !== module || (!state.project && module !== "admin")) return null;
    return { version: ++state.viewRenderVersion, navigation: state.navigationVersion, module, projectId: state.project?.id ?? null };
}

function viewRenderIsCurrent(view) {
    return Boolean(view && view.version === state.viewRenderVersion && view.navigation === state.navigationVersion
        && view.module === state.module && view.projectId === (state.project?.id ?? null));
}

function clampAssistantPosition(position, viewport, size = 56) {
    const margin = 12;
    const maxX = Math.max(margin, viewport.width - size - margin);
    const bottomInset = viewport.width <= 620 ? 70 : margin;
    const maxY = Math.max(margin, viewport.height - size - bottomInset);
    const valid = position && Number.isFinite(position.x) && Number.isFinite(position.y);
    return { x: Math.min(maxX, Math.max(margin, valid ? position.x : maxX)),
        y: Math.min(maxY, Math.max(margin, valid ? position.y : maxY)) };
}

function wireAIFloatingButton() {
    const button = $("#ai-assistant-toggle");
    if (!button) return;
    const storageKey = "pc.ai-button-position.v1";
    let position = null;
    let gesture = null;
    let suppressClick = false;
    try { position = JSON.parse(localStorage.getItem(storageKey) || "null"); } catch (_) { /* Optional preference. */ }
    const apply = (save = false) => {
        position = clampAssistantPosition(position, { width: window.innerWidth, height: window.innerHeight });
        button.style.left = `${position.x}px`;
        button.style.top = `${position.y}px`;
        button.style.right = "auto";
        button.style.bottom = "auto";
        if (save) { try { localStorage.setItem(storageKey, JSON.stringify(position)); } catch (_) { /* Storage may be unavailable. */ } }
    };
    apply();
    button.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || !event.isPrimary) return;
        gesture = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY,
            x: position.x, y: position.y, moved: false };
        suppressClick = false;
        button.setPointerCapture(event.pointerId);
    });
    button.addEventListener("pointermove", (event) => {
        if (!gesture || event.pointerId !== gesture.pointerId) return;
        const dx = event.clientX - gesture.startX, dy = event.clientY - gesture.startY;
        if (!gesture.moved && Math.hypot(dx, dy) < 6) return;
        gesture.moved = true;
        event.preventDefault();
        position = { x: gesture.x + dx, y: gesture.y + dy };
        button.classList.add("dragging");
        apply();
    });
    const finish = (event) => {
        if (!gesture || event.pointerId !== gesture.pointerId) return;
        suppressClick = gesture.moved;
        gesture = null;
        button.classList.remove("dragging");
        if (button.hasPointerCapture(event.pointerId)) button.releasePointerCapture(event.pointerId);
        apply(true);
    };
    button.addEventListener("pointerup", finish);
    button.addEventListener("pointercancel", finish);
    button.addEventListener("lostpointercapture", finish);
    button.addEventListener("click", (event) => {
        if (suppressClick && event.detail !== 0) { suppressClick = false; event.preventDefault(); return; }
        suppressClick = false;
        setAIAssistantOpen(!state.aiAssistant.open);
    });
    button.addEventListener("keydown", (event) => {
        const direction = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
        if (event.altKey && event.key === "Home") { event.preventDefault(); position = null; apply(true); return; }
        if (!event.altKey || !direction) return;
        event.preventDefault();
        position = { x: position.x + direction[0] * 16, y: position.y + direction[1] * 16 };
        apply(true);
    });
    window.addEventListener("resize", () => apply(true));
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function cookie(name) {
    const prefix = `${name}=`;
    const item = document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith(prefix));
    return item ? decodeURIComponent(item.slice(prefix.length)) : "";
}

function toQuery(params) {
    const query = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== "" && value !== null && value !== undefined) query.set(key, value);
    });
    const text = query.toString();
    return text ? `?${text}` : "";
}

async function api(path, options = {}, retry = true) {
    state.apiRequestSequence += 1;
    const requestId = state.apiRequestSequence;
    const scope = state.performanceScope;
    if (scope) scope.apiRequests += 1;
    const timerLabel = `api:${requestId}:${path}`;
    console.time(timerLabel);
    const request = { credentials: "same-origin", ...options, headers: { ...(options.headers || {}) } };
    const method = String(request.method || "GET").toUpperCase();
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) request.headers["X-CSRF-Token"] = cookie("pc_csrf");
    if (request.body && !(request.body instanceof FormData) && typeof request.body !== "string") {
        request.headers["Content-Type"] = "application/json";
        request.body = JSON.stringify(request.body);
    }
    let response = null;
    try {
        response = await fetch(`/api${path}`, request);
        if (response.status === 401 && retry && !path.startsWith("/auth/")) {
            const refreshed = await fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin" });
            if (refreshed.ok && (await refreshed.json()).authenticated) return api(path, options, false);
        }
        const type = response.headers.get("content-type") || "";
        const payload = type.includes("application/json") ? await response.json() : await response.blob();
        if (!response.ok) {
            const detail = typeof payload?.detail === "string"
                ? payload.detail
                : Array.isArray(payload?.detail)
                    ? payload.detail.map((item) => item?.msg || item?.message || "").filter(Boolean).join(" ")
                    : "";
            const message = payload?.error || detail || `A művelet nem hajtható végre. (HTTP ${response.status})`;
            const error = new Error(message);
            error.status = response.status;
            error.detail = payload?.detail;
            throw error;
        }
        return payload;
    } finally {
        console.timeEnd(timerLabel);
        if (response) {
            console.debug("[Project Control mérés]", {
                path,
                status: response.status,
                serverTiming: response.headers.get("server-timing") || "",
                supabaseRequests: Number(response.headers.get("x-supabase-request-count") || 0),
            });
        }
    }
}

function beginPerformanceScope(name) {
    const scope = { name, apiRequests: 0, startedAt: performance.now() };
    state.performanceScope = scope;
    console.time(`betöltés:${name}`);
    return scope;
}

function endPerformanceScope(scope) {
    console.timeEnd(`betöltés:${scope.name}`);
    console.info("[Project Control modulmérés]", {
        module: scope.name,
        apiRequests: scope.apiRequests,
        durationMs: Math.round((performance.now() - scope.startedAt) * 10) / 10,
    });
    if (state.performanceScope === scope) state.performanceScope = null;
}

function toast(message, error = false) {
    const item = document.createElement("div");
    item.className = `toast${error ? " error" : ""}`;
    item.textContent = message;
    $("#toast-region").append(item);
    setTimeout(() => item.remove(), 4500);
}

function loading(text = "Adatok betöltése…") {
    $("#content").innerHTML = `<div class="empty-state"><strong>${escapeHtml(text)}</strong></div>`;
}

function empty(text) {
    return `<div class="empty-state">${escapeHtml(text)}</div>`;
}

function formatDate(value) {
    if (!value) return "–";
    const date = new Date(String(value).slice(0, 10) + "T12:00:00");
    return Number.isNaN(date.valueOf()) ? escapeHtml(value) : new Intl.DateTimeFormat("hu-HU").format(date);
}

function formatMonth(value) {
    if (!value) return "–";
    const date = new Date(String(value).slice(0, 10) + "T12:00:00");
    return Number.isNaN(date.valueOf()) ? escapeHtml(value) : new Intl.DateTimeFormat("hu-HU", { year: "numeric", month: "long" }).format(date);
}

function formatMoney(value) {
    const amount = Number(value || 0);
    return new Intl.NumberFormat("hu-HU", { style: "currency", currency: "HUF", maximumFractionDigits: 0 }).format(amount);
}

function parseMoneyNumber(value) {
    let normalized = String(value ?? "").replace(/[^0-9,.-]/g, "");
    if (normalized.includes(",")) normalized = normalized.replaceAll(".", "").replace(",", ".");
    else if ((normalized.match(/\./g) || []).length > 1 || /^-?\d{1,3}(\.\d{3})+$/.test(normalized)) normalized = normalized.replaceAll(".", "");
    return Number(normalized) || 0;
}

function statusBadge(item = {}) {
    const color = /^#[0-9a-f]{6}$/i.test(item.status_color || item.color || "") ? (item.status_color || item.color) : "#64748b";
    const icon = item.status_icon || item.icon || item.status_code || item.code || "•";
    const label = item.status_name || item.name || item.status_code || item.code || "Nincs megadva";
    return `<span class="status" style="color:${color}"><span aria-hidden="true">${escapeHtml(icon)}</span>${escapeHtml(label)}</span>`;
}

const financialPhaseColors = ["#4f6472", "#2e80bf", "#1f9d61", "#d68a16", "#7255a8", "#b84e4e"];
const planningMilestoneColors = ["#2878bd", "#1f9d61", "#7255a8", "#d68a16", "#3f718c", "#b84e4e"];

function financialPhaseColor(value) {
    const phaseNo = Number(value);
    return financialPhaseColors[Number.isInteger(phaseNo) && phaseNo >= 0 ? phaseNo % financialPhaseColors.length : 0];
}

function planningMilestoneColor(item = {}) {
    const source = String(item.id ?? item.code ?? "");
    const seed = [...source].reduce((sum, character) => sum + character.charCodeAt(0), 0);
    return planningMilestoneColors[seed % planningMilestoneColors.length];
}

function colorTint(hex, alpha = 0.1) {
    const value = /^#[0-9a-f]{6}$/i.test(hex) ? hex.slice(1) : "4f6472";
    return `rgba(${Number.parseInt(value.slice(0, 2), 16)}, ${Number.parseInt(value.slice(2, 4), 16)}, ${Number.parseInt(value.slice(4, 6), 16)}, ${alpha})`;
}

function setHeader(title, eyebrow) {
    $("#page-title").textContent = title;
    $("#page-eyebrow").textContent = eyebrow;
}

function showModal(title, eyebrow, content) {
    $("#modal-title").textContent = title;
    $("#modal-eyebrow").textContent = eyebrow || "";
    $("#modal-content").innerHTML = content;
    const modal = $("#modal");
    if (!modal.open) modal.showModal();
}

function closeModal() {
    $("#modal").close();
    $("#modal-content").innerHTML = "";
}

function formDataObject(form) {
    return Object.fromEntries(new FormData(form).entries());
}

const RESPONSIBLE_COMPANIES = ["Minta Cégcsoport Zrt.", "Minta Tervezőiroda Kft.", "Minta Partner Mérnökség"];
const PROJECT_SCALES = ["Kis", "Közepes", "Nagy"];
const PROJECT_SOURCES = ["Hazai költségvetés", "Európai uniós forrás"];

function normalizeResponsibleCompany(value) {
    return String(value || "").trim();
}

function responsibleCompanyOptions(value) {
    const normalized = normalizeResponsibleCompany(value);
    return selectOptions(RESPONSIBLE_COMPANIES, RESPONSIBLE_COMPANIES.includes(normalized) ? normalized : "");
}

function selectOptions(values, currentValue, placeholder = "Válassz") {
    const current = String(currentValue || "").trim();
    const known = values.includes(current);
    const legacyOption = current && !known
        ? `<option value="${escapeHtml(current)}" selected>Korábbi érték: ${escapeHtml(current)}</option>`
        : "";
    return `<option value="">${escapeHtml(placeholder)}</option>${legacyOption}${values.map((value) => `<option value="${escapeHtml(value)}" ${value === current ? "selected" : ""}>${escapeHtml(value)}</option>`).join("")}`;
}

function projectCreatePayload(form, idempotencyKey) {
    const raw = formDataObject(form);
    return {
        name: raw.name || "",
        idempotency_key: idempotencyKey,
        work_number: raw.work_number || "",
        responsible_company: normalizeResponsibleCompany(raw.responsible_company),
        contract_subject: valueOrNull(raw.contract_subject),
        customer: raw.customer || "",
        main_customer: raw.main_customer || "",
        status: raw.status || "Aktív",
    };
}

function valueOrNull(value) {
    return value === "" || value === undefined ? null : value;
}

function roleLabel(role) {
    return ({ admin: "Adminisztrátor", editor: "Szerkesztő" })[role] || "Szerkesztő";
}

function canEdit() {
    return Boolean(state.user);
}

function hasPermission(permission) {
    return state.user?.role === "admin" || Boolean(state.user?.permissions?.[permission]);
}

function aiAssistantResponseText(payload) {
    const candidates = [
        payload?.answer,
        payload?.message,
        payload?.response,
        payload?.text,
        payload?.valasz,
        payload?.output?.text,
        payload?.choices?.[0]?.message?.content,
    ];
    return candidates.find((value) => typeof value === "string" && value.trim())?.trim() || "Az asszisztens választ adott, de annak szövege nem értelmezhető.";
}

function buildAIAssistantHistory() {
    return state.aiAssistant.messages
        .filter((item) => item.role === "user" || item.role === "assistant")
        .slice(0, -1)
        .slice(-20)
        .map((item) => ({ role: item.role, content: item.text.slice(0, 4000) }));
}

function renderAIAssistantMessages() {
    const container = $("#ai-assistant-messages");
    if (!container) return;
    container.innerHTML = "";
    const messages = state.aiAssistant.messages.length
        ? state.aiAssistant.messages
        : [{ role: "system", text: "A Project Control dokumentációjában segítek eligazodni. Egy rövid, konkrét kérdést írj; például: Hogyan készítsek ajánlatkérést? Élő projektadatokat nem olvasok és módosításokat nem hajtok végre." }];
    messages.forEach((message) => {
        const item = document.createElement("article");
        item.className = `ai-message ${message.role}`;
        const label = document.createElement("small");
        label.textContent = message.role === "user" ? "Te" : message.role === "error" ? "Hiba" : message.role === "assistant" ? "AI Asszisztens" : "Tájékoztatás";
        const text = document.createElement("p");
        text.textContent = message.text;
        item.append(label, text);
        if (message.sources?.length) {
            const sources = document.createElement("small");
            sources.textContent = `Dokumentáció: ${message.sources.map((source) => source.label).join("; ")}`;
            item.append(sources);
        }
        container.append(item);
    });
    if (state.aiAssistant.sending) {
        const loadingItem = document.createElement("article");
        loadingItem.className = "ai-message assistant loading";
        loadingItem.textContent = "Az asszisztens válaszol…";
        container.append(loadingItem);
    }
    container.scrollTop = container.scrollHeight;
}

function setAIAssistantOpen(open) {
    state.aiAssistant.open = Boolean(open);
    const panel = $("#ai-assistant-panel");
    const backdrop = $("#ai-assistant-backdrop");
    const toggle = $("#ai-assistant-toggle");
    if (!panel || !backdrop || !toggle) return;
    panel.classList.toggle("open", state.aiAssistant.open);
    backdrop.classList.toggle("open", state.aiAssistant.open);
    panel.setAttribute("aria-hidden", String(!state.aiAssistant.open));
    backdrop.setAttribute("aria-hidden", String(!state.aiAssistant.open));
    toggle.setAttribute("aria-expanded", String(state.aiAssistant.open));
    toggle.setAttribute("aria-label", state.aiAssistant.open ? "AI asszisztens bezárása" : "AI asszisztens megnyitása");
    if (state.aiAssistant.open) {
        renderAIAssistantMessages();
        setTimeout(() => $("#ai-assistant-input")?.focus(), 180);
    } else {
        toggle.focus();
    }
}

async function sendAIAssistantMessage() {
    const input = $("#ai-assistant-input");
    const sendButton = $("#ai-assistant-send");
    const status = $("#ai-assistant-status");
    const message = input?.value.trim() || "";
    if (!message || state.aiAssistant.sending || message === state.aiAssistant.lastMessage) return;
    state.aiAssistant.sending = true;
    state.aiAssistant.lastMessage = message;
    input.value = "";
    sendButton.disabled = true;
    status.textContent = "A kis Oracle-modell válaszára várunk…";
    state.aiAssistant.messages.push({ role: "user", text: message });
    renderAIAssistantMessages();
    try {
        const payload = await api("/ai/assistant", {
            method: "POST",
            body: {
                message,
                project_id: state.project?.id ?? null,
                module: state.module || null,
                history: buildAIAssistantHistory(),
            },
        });
        state.aiAssistant.messages.push({ role: "assistant", text: aiAssistantResponseText(payload), sources: payload.sources || [] });
    } catch (error) {
        console.error("AI asszisztens hívási hiba", error);
        state.aiAssistant.messages.push({
            role: "error",
            text: error?.message || "Az AI asszisztens most nem érhető el. Próbáld meg később.",
        });
        if (!input.value) input.value = message;
    } finally {
        state.aiAssistant.sending = false;
        state.aiAssistant.lastMessage = "";
        sendButton.disabled = false;
        status.textContent = "";
        renderAIAssistantMessages();
    }
}

function wireAIAssistant() {
    wireAIFloatingButton();
    $("#ai-assistant-close")?.addEventListener("click", () => setAIAssistantOpen(false));
    $("#ai-assistant-backdrop")?.addEventListener("click", () => setAIAssistantOpen(false));
    $("#ai-assistant-form")?.addEventListener("submit", async (event) => { event.preventDefault(); await sendAIAssistantMessage(); });
    $("#ai-assistant-input")?.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("#ai-assistant-form")?.requestSubmit(); }
    });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && state.aiAssistant.open) setAIAssistantOpen(false); });
}

function showLoginView(message = "") {
    if (state.notificationRefreshTimer) {
        window.clearInterval(state.notificationRefreshTimer);
        state.notificationRefreshTimer = null;
    }
    state.navigationVersion += 1;
    state.viewRenderVersion += 1;
    state.user = null;
    state.project = null;
    state.notifications = [];
    state.todayTasks = [];
    state.taskHistory = [];
    state.notificationsAnnounced = false;
    $("#app-view").hidden = true;
    $("#login-view").hidden = false;
    $("#login-error").textContent = message;
    if (state.aiAssistant.open) setAIAssistantOpen(false);
}

function setProjectGate(projectIsOpen) {
    $("#app-view").classList.toggle("project-gate", !projectIsOpen);
    $("#module-nav").hidden = !projectIsOpen;
    $("#back-projects").disabled = !projectIsOpen;
    $("#global-search").placeholder = projectIsOpen ? "Keresés az aktuális modulban" : "Projekt keresése";
}

async function bootstrap() {
    try {
        state.user = await api("/auth/me");
    } catch (error) {
        showLoginView("A munkamenet nem nyitható meg. Jelentkezz be újra.");
        return false;
    }
    $("#login-view").hidden = true;
    $("#app-view").hidden = false;
    $("#user-name").textContent = state.user.display_name || state.user.email;
    $("#user-role").textContent = roleLabel(state.user.role);
    $("#admin-nav").hidden = !hasPermission("admin_panel");
    try {
        await refreshNotifications();
    } catch (error) {
        state.notifications = [];
        $("#notification-count").textContent = "0";
        toast(`Az értesítések most nem tölthetők be: ${error.message}`, true);
    }
    if (!state.notificationRefreshTimer) {
        state.notificationRefreshTimer = window.setInterval(() => {
            if (state.user && !document.hidden) refreshNotifications().catch(() => {});
        }, 5 * 60 * 1000);
    }
    await loadProjects();
    if (state.notifications.length && !state.notificationsAnnounced) {
        state.notificationsAnnounced = true;
        toast(`${state.notifications.length} nyitott teendő vár rád.`);
    }
    return true;
}

async function loadProjects(search = "") {
    const navigation = ++state.navigationVersion;
    state.viewRenderVersion += 1;
    const performanceScope = beginPerformanceScope("lobby");
    state.project = null;
    state.selectedProjectId = null;
    state.activeDiscipline = null;
    state.module = "settings";
    setProjectGate(false);
    $("#active-project-name").textContent = "Projektek";
    $("#active-project-meta").textContent = "Válassz munkaterületet";
    $("#global-search").value = search;
    setHeader("Projektek", "Projektportfólió");
    loading();
    try {
        const requests = [api(`/projects${toQuery({ search })}`)];
        if (hasPermission("admin_panel")) requests.push(api("/admin/application-clock").catch(() => null));
        const results = await Promise.all(requests);
        if (navigation !== state.navigationVersion) return;
        state.projects = results[0];
        state.applicationDate = results[1]?.application_date || new Date().toISOString().slice(0, 10);
        const projectList = state.projects.length ? state.projects.map((p) => `
                <article class="project-row" data-project-id="${p.id}" tabindex="0" aria-label="${escapeHtml(p.name)}">
                    <strong><small>Munkaszám</small>${escapeHtml(p.work_number || "–")}</strong>
                    <span><small>Projekt neve</small>${escapeHtml(p.name)}<small>${escapeHtml(p.main_customer || p.customer || "Nincs megbízó")}</small></span>
                    <span><small>Vállalkozó</small>${escapeHtml(normalizeResponsibleCompany(p.responsible_company) || "–")}</span>
                    <span>${escapeHtml(p.status || "Nincs állapot")}</span><button type="button" class="project-open-arrow" data-open-project="${p.id}" aria-label="${escapeHtml(p.name)} megnyitása">Megnyitás →</button>
                </article>`).join("") : `<div class="empty-state"><strong>Nincs elérhető projekt</strong><span>A felhasználói profilhoz még nincs projekt-hozzáférés rendelve.</span><button id="refresh-projects" class="secondary-button" type="button">Projektlista frissítése</button></div>`;
        $("#content").innerHTML = `
            <div class="lobby-layout">
                <section class="lobby-projects">
                    <div class="toolbar">
                        <div><strong>${state.projects.length} elérhető projekt</strong><p class="muted">Válassz egy projektet, majd nyisd meg a Megnyitás gombbal.</p></div>
                        <div class="toolbar-group">
                            <button id="new-project" class="primary-button" type="button" ${hasPermission("project_create") ? "" : 'disabled title="Nincs projektlétrehozási jogosultság"'}>Új projekt</button>
                            <button id="open-project" class="secondary-button" type="button" disabled>Megnyitás</button>
                            <button id="edit-project" class="secondary-button" type="button" data-permission-allowed="${hasPermission("project_write")}" disabled>Szerkesztés</button>
                            <button id="rename-project" class="secondary-button" type="button" data-permission-allowed="${hasPermission("project_write")}" disabled>Átnevezés</button>
                            <button id="archive-project" class="danger-button" type="button" data-permission-allowed="${hasPermission("project_delete")}" disabled>Törlés</button>
                        </div>
                    </div>
                    <div class="project-list">${projectList}</div>
                </section>
                <aside class="lobby-quick panel">
                    <div class="panel-header"><h2>Gyorsindító</h2></div>
                    <div class="lobby-stats">
                        <div><span>Elérhető projektek</span><strong>${state.projects.length}</strong><small>a jogosultságaid alapján</small></div>
                        <div><span>Értesítések</span><strong>${state.notifications.length}</strong><small>aktuális tétel</small></div>
                        <div><span>Szerepkör</span><strong>${escapeHtml(roleLabel(state.user?.role))}</strong><small>${escapeHtml(state.user?.email || "")}</small></div>
                        <div><span>Alkalmazásidő</span><strong>${formatDate(state.applicationDate)}</strong><small>értesítési számításokhoz</small></div>
                    </div>
                    <div class="lobby-actions">
                        ${hasPermission("arbevetel") ? '<button id="company-cash-flow" class="lobby-cash-flow" type="button"><span class="lobby-action-icon" aria-hidden="true">Ft</span><span><strong>Céges árbevétel</strong><small>Cash-flow áttekintés</small></span><span class="lobby-action-arrow" aria-hidden="true">→</span></button>' : ""}
                        <button id="lobby-notifications" class="secondary-button" type="button">Értesítések megnyitása</button>
                    </div>
                </aside>
            </div>`;
        $$("[data-project-id]").forEach((row) => {
            row.addEventListener("click", () => selectProject(Number(row.dataset.projectId)));
            row.addEventListener("keydown", (event) => {
                if (event.target === row && (event.key === "Enter" || event.key === " ")) {
                    event.preventDefault();
                    selectProject(Number(row.dataset.projectId));
                }
            });
            row.addEventListener("dblclick", () => {
                selectProject(Number(row.dataset.projectId));
                openSelectedProject();
            });
        });
        $$('[data-open-project]').forEach((control) => {
            const open = (event) => { event.stopPropagation(); openProject(Number(control.dataset.openProject)); };
            control.addEventListener("click", open);
        });
        $("#new-project")?.addEventListener("click", openProjectCreate);
        $("#open-project")?.addEventListener("click", openSelectedProject);
        $("#edit-project")?.addEventListener("click", openProjectEdit);
        $("#rename-project")?.addEventListener("click", openProjectRename);
        $("#archive-project")?.addEventListener("click", archiveSelectedProject);
        $("#company-cash-flow")?.addEventListener("click", () => openCompanyCashFlow());
        $("#lobby-notifications")?.addEventListener("click", openNotifications);
        $("#refresh-projects")?.addEventListener("click", () => loadProjects($("#global-search").value.trim()));
    } catch (error) {
        if (navigation !== state.navigationVersion) return;
        $("#content").innerHTML = empty(error.message);
    } finally {
        endPerformanceScope(performanceScope);
    }
}

function getSelectedProject() {
    return state.projects.find((project) => project.id === state.selectedProjectId) || null;
}

function updateProjectSelectionControls() {
    const project = getSelectedProject();
    if (!project) state.selectedProjectId = null;
    $$("[data-project-id]").forEach((row) => {
        const isSelected = Boolean(project) && Number(row.dataset.projectId) === project.id;
        row.classList.toggle("selected", isSelected);
        row.setAttribute("aria-label", `${state.projects.find((item) => item.id === Number(row.dataset.projectId))?.name || "Projekt"}${isSelected ? " · kijelölve" : ""}`);
    });
    ["#open-project", "#edit-project", "#rename-project", "#archive-project"].forEach((selector) => {
        const button = $(selector);
        if (button) button.disabled = !project || button.dataset.permissionAllowed === "false";
    });
}

function selectProject(projectId) {
    const project = state.projects.find((item) => item.id === projectId);
    state.selectedProjectId = project?.id || null;
    updateProjectSelectionControls();
}

function openSelectedProject() {
    const project = getSelectedProject();
    if (!project) return;
    openProject(project.id);
}

function openProjectCreate() {
    const idempotencyKey = crypto.randomUUID();
    showModal("Új projekt", "Projektportfólió", `<form id="project-create"><div class="form-grid"><label class="span-2">Projekt neve<input name="name" required maxlength="255"></label><label>Saját státusz<input name="status" value="Aktív"></label><label>Munkaszám<input name="work_number" maxlength="255"></label><label class="span-2">Vállalkozó<select name="responsible_company">${selectOptions(RESPONSIBLE_COMPANIES, "")}</select></label><label>Megbízó<input name="main_customer"></label><label class="span-3">Szerződés tárgya<textarea name="contract_subject" rows="3"></textarea></label><p class="field-help span-3">A szerződéses összeget az Ütemterv szerződéses mérföldköveinél lehet rögzíteni.</p><p id="project-create-error" class="form-error span-3" role="alert"></p></div><div class="modal-actions"><button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Projekt létrehozása</button></div></form>`);
    let submitting = false;
    $("#project-create").addEventListener("submit", async (event) => {
        event.preventDefault();
        if (submitting) return;
        const form = event.currentTarget;
        const submitButton = form.querySelector('button[type="submit"]');
        const closeButton = form.querySelector("[data-close]");
        const errorMessage = $("#project-create-error", form);
        submitting = true;
        form.setAttribute("aria-busy", "true");
        submitButton.disabled = true;
        closeButton.disabled = true;
        submitButton.textContent = "Projekt létrehozása…";
        errorMessage.textContent = "";
        try {
            const data = projectCreatePayload(form, idempotencyKey);
            await api("/projects", { method: "POST", body: data });
            if (form.isConnected) closeModal();
            toast("A projekt létrejött.");
            await loadProjects();
        } catch (error) {
            errorMessage.textContent = error.message || "A projekt létrehozása nem sikerült.";
            submitting = false;
            form.removeAttribute("aria-busy");
            submitButton.disabled = false;
            closeButton.disabled = false;
            submitButton.textContent = "Projekt létrehozása";
        }
    });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

async function openProjectEdit() {
    const selectedProject = getSelectedProject();
    if (!selectedProject) return;
    try {
        const project = await api(`/projects/${selectedProject.id}`);
        if (state.selectedProjectId !== selectedProject.id) return;
        const legacyCompany = normalizeResponsibleCompany(project.responsible_company);
        showModal("Projekt szerkesztése", "Projektportfólió", `<form id="project-edit"><div class="form-grid"><label class="span-2">Projekt neve<input name="name" value="${escapeHtml(project.name)}" required maxlength="255"></label><label>Saját státusz<input name="status" value="${escapeHtml(project.status || "Aktív")}" required></label><label>Munkaszám<input name="work_number" value="${escapeHtml(project.work_number || "")}" maxlength="255"></label><label class="span-2">Vállalkozó<select name="responsible_company">${responsibleCompanyOptions(legacyCompany)}</select>${legacyCompany && !RESPONSIBLE_COMPANIES.includes(legacyCompany) ? `<small class="field-help">Korábbi érték megőrizve: ${escapeHtml(legacyCompany)}. A cseréhez válassz a listából.</small>` : ""}</label><label>Megbízó<input name="main_customer" value="${escapeHtml(project.main_customer || project.customer || "")}"></label><label class="span-3">Szerződés tárgya<textarea name="contract_subject" rows="3">${escapeHtml(project.contract_subject || "")}</textarea></label><p class="field-help span-3">A szerződéses összeg forrása az Ütemterv szerződéses mérföldkőnézete.</p></div><div class="modal-actions"><button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Projekt mentése</button></div></form>`);
        $("#project-edit").addEventListener("submit", async (event) => {
            event.preventDefault();
            const data = formDataObject(event.currentTarget);
            data.responsible_company = normalizeResponsibleCompany(data.responsible_company) || legacyCompany;
            await api(`/projects/${project.id}`, { method: "PATCH", body: data });
            closeModal();
            toast("A projekt adatai frissültek.");
            await loadProjects($("#global-search").value.trim());
        });
        $("[data-close]", $("#modal")).addEventListener("click", closeModal);
    } catch (error) {
        toast(error.message || "A projekt adatai nem tölthetők be.", true);
    }
}

function openProjectRename() {
    const project = getSelectedProject();
    if (!project) return;
    showModal("Projekt átnevezése", "Projektportfólió", `<form id="project-rename"><label>Új projektnév<input name="name" value="${escapeHtml(project.name)}" required maxlength="255" autofocus></label><div class="modal-actions"><button type="button" data-close class="secondary-button">Mégse</button><button type="submit" class="primary-button">Átnevezés</button></div></form>`);
    $("#project-rename").addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = formDataObject(event.currentTarget);
        await api(`/projects/${project.id}`, { method: "PATCH", body: { name: data.name } });
        closeModal();
        toast("A projekt átnevezése megtörtént.");
        await loadProjects($("#global-search").value.trim());
    });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

async function archiveSelectedProject() {
    const project = getSelectedProject();
    if (!project || !confirm(`Biztosan törlöd a projektlistából ezt a projektet: ${project.name}? A történeti adatai megmaradnak.`)) return;
    await api(`/projects/${project.id}`, { method: "DELETE" });
    toast("A projekt törölve lett a projektlistából.");
    await loadProjects($("#global-search").value.trim());
}

async function openProject(id) {
    const navigation = ++state.navigationVersion;
    state.viewRenderVersion += 1;
    loading("Projekt megnyitása…");
    try {
        const project = await api(`/projects/${id}`);
        if (navigation !== state.navigationVersion) return;
        state.project = project;
        state.scheduleFinancialPhase = null;
        $("#active-project-name").textContent = state.project.name;
        $("#active-project-meta").textContent = `Projektazonosító: ${state.project.id}`;
        $("#global-search").value = "";
        state.settingsView = "project";
        setProjectGate(true);
        await selectModule("settings");
    } catch (error) {
        if (navigation !== state.navigationVersion) return;
        toast(error.message, true);
        await loadProjects();
    }
}

async function selectModule(module) {
    // Régi belső hivatkozások biztonságosan az új alapértelmezett projektoldalra mennek.
    module = module === "overview" ? "settings" : module;
    if (!state.project && module !== "admin") return loadProjects($("#global-search").value.trim());
    if (module === "admin" && !hasPermission("admin_panel")) return;
    if (!moduleLabels[module]) return;
    const navigation = ++state.navigationVersion;
    state.viewRenderVersion += 1;
    state.module = module;
    $$("#module-nav button").forEach((button) => button.classList.toggle("active", button.dataset.module === module));
    const [title, eyebrow] = moduleLabels[module];
    setHeader(title, eyebrow);
    loading();
    const renderers = { disciplines: renderDisciplines, schedule: renderSchedule, subcontractors: renderSubcontractors, finance: renderFinance, engagements: renderEngagements, settings: renderSettings, admin: renderAdmin };
    const performanceScope = beginPerformanceScope(`modul:${module}`);
    try {
        await renderers[module]();
    } catch (error) {
        if (navigation !== state.navigationVersion || state.module !== module) return;
        $("#content").innerHTML = empty(error.message);
        toast(error.message, true);
    } finally {
        endPerformanceScope(performanceScope);
    }
}

async function renderOverview() {
    const dashboard = await api(`/engagements/dashboard/${state.project.id}`);
    const progress = Number(dashboard.progress_percent || 0);
    $("#content").innerHTML = `
        <div class="kpi-grid">
            <div class="kpi"><span>Saját státusz</span><strong>${escapeHtml(state.project.status || "Nincs megadva")}</strong><small>${escapeHtml(state.project.main_customer || state.project.customer || "Nincs megbízó")}</small></div>
            <div class="kpi green"><span>Engedélyezési készültség</span><strong>${progress.toLocaleString("hu-HU")}%</strong><div class="progress-track"><span style="width:${Math.min(100, progress)}%"></span></div></div>
            <div class="kpi amber"><span>Nyitott engedélyügy</span><strong>${Number(dashboard.open || 0)}</strong><small>${Number(dashboard.total || 0)} ügyből</small></div>
            <div class="kpi red"><span>Figyelmet igényel</span><strong>${Number(dashboard.attention || 0)}</strong><small>lejárat, hiány vagy elakadás</small></div>
        </div>
        <div class="two-columns">
            <section class="panel"><div class="panel-header"><h2>Szakági készültség</h2></div><div class="panel-body discipline-bars">
                ${(dashboard.disciplines || []).length ? dashboard.disciplines.map((d) => `<button type="button" data-attention-discipline="${d.discipline_id}"><span><strong>${escapeHtml(d.discipline_name)}</strong><small>${d.closed_count}/${d.total_count} lezárva</small></span><span class="bar"><i style="width:${Math.min(100, Number(d.progress_percent || 0))}%"></i></span><b>${Number(d.progress_percent || 0).toLocaleString("hu-HU")}%</b></button>`).join("") : empty("Még nincs engedélyezési adat.")}
            </div></section>
            <section class="panel"><div class="panel-header"><h2>Figyelmet igénylő ügyek</h2></div><div class="compact-list">
                ${(dashboard.attention_items || []).length ? dashboard.attention_items.slice(0, 8).map((item) => `<button type="button" data-attention-id="${item.id}"><strong>${escapeHtml(item.partner_name || item.discipline_name)}</strong><span>${escapeHtml(item.task_name)}</span><small>${escapeHtml(item.status_name)} · ${formatDate(item.last_date)}</small></button>`).join("") : empty("Nincs kiemelt ügy.")}
            </div></section>
        </div>`;
    $$("[data-attention-id]").forEach((row) => row.addEventListener("dblclick", () => {
        state.module = "engagements";
        selectModule("engagements").then(() => openAssignment(Number(row.dataset.attentionId)));
    }));
    $$("[data-attention-discipline]").forEach((row) => row.addEventListener("click", () => {
        state.module = "engagements";
        selectModule("engagements").then(() => {
            const select = $("#eng-discipline-filter");
            if (select) { select.value = row.dataset.attentionDiscipline; loadAssignmentTable(); }
        });
    }));
}

async function renderDisciplines() {
    const view = beginViewRender("disciplines");
    if (!view) return;
    try {
    const [disciplines, rows, phases, rates] = await Promise.all([
        api(`/disciplines/${state.project.id}`),
        api(`/disciplines/${state.project.id}/daily-progress`),
        api(`/disciplines/${state.project.id}/phases`),
        api(`/disciplines/${state.project.id}/daily-rates`),
    ]);
    if (!viewRenderIsCurrent(view)) return;
    if (!disciplines.length) {
        $("#content").innerHTML = empty("Ehhez a projekthez még nincs szakág beállítva.");
        return;
    }
    if (!disciplines.some((item) => item.name === state.activeDiscipline)) state.activeDiscipline = disciplines[0].name;
    const activeRows = rows.filter((row) => row.discipline_name === state.activeDiscipline);
    const rateByYear = Object.fromEntries(rates.map((rate) => [Number(rate.year), Number(rate.daily_rate || 0)]));
    let cumulativeActual = 0;
    let cumulativePlanned = 0;
    const calculatedRows = activeRows.map((row) => {
        cumulativeActual += Number(row.actual_percent || 0);
        cumulativePlanned += Number(row.planned_percent || 0);
        const year = Number(String(row.record_date).slice(0, 4));
        return { ...row, cumulativeActual, cumulativePlanned, monthlyCost: Number(row.days || 0) * Number(rateByYear[year] || 0) };
    });
    const latest = calculatedRows.at(-1);
    $("#content").innerHTML = `
        <div class="section-heading"><div><h2>Szakági kimutatás</h2><p>Havi ráfordítások, készültség és költség</p></div><span>${disciplines.length} szakág</span></div>
        <div class="discipline-tabs" role="tablist">${disciplines.map((discipline) => `<button type="button" role="tab" aria-selected="${discipline.name === state.activeDiscipline}" class="${discipline.name === state.activeDiscipline ? "active" : ""}" data-discipline-name="${escapeHtml(discipline.name)}">${escapeHtml(discipline.name)}</button>`).join("")}</div>
        <section class="panel discipline-sheet">
            <div class="panel-header"><div><h2>${escapeHtml(state.activeDiscipline)}</h2><p class="muted">szakági havi adatlap</p></div><div class="discipline-summary"><strong>${calculatedRows.length} hónap</strong><span>valós ${Number(latest?.cumulativeActual || 0).toLocaleString("hu-HU")}%</span><span>terv ${Number(latest?.cumulativePlanned || 0).toLocaleString("hu-HU")}%</span></div></div>
            ${canEdit() ? `<form id="discipline-month-form" class="inline-editor green-editor"><strong>Új hónap rögzítése</strong><label>Hónap<input name="month" type="month" required></label><label>Projektfázis<select name="phase"><option value="">Nincs megadva</option>${phases.map((phase) => `<option value="${escapeHtml(phase.phase_name)}">${escapeHtml(phase.phase_name)}</option>`).join("")}</select></label><button class="primary-button" type="submit">Hónap rögzítése</button><button id="delete-active-month" class="danger-button" type="button" disabled>Kijelölt hónap törlése</button></form>` : ""}
            <div class="panel-body discipline-table-intro"><strong>Havi szakági adatok</strong><span>${calculatedRows.length} bejegyzés</span><small>Dupla kattintással szerkeszthető.</small></div>
            <div class="table-wrap"><table class="discipline-table"><thead><tr><th>Hónap</th><th>Munkaszakasz / fázis</th><th>Ráfordított nap</th><th>Havi valós kész.</th><th>Össz. valós kész.</th><th>Havi terv</th><th>Össz. terv</th><th>Költség / hónap</th></tr></thead><tbody>${calculatedRows.length ? calculatedRows.map((row) => `<tr data-progress-id="${row.id}"><td>${formatMonth(row.record_date)}</td><td>${escapeHtml(row.phase || "–")}</td><td>${Number(row.days || 0).toLocaleString("hu-HU")} nap</td><td>${Number(row.actual_percent || 0).toLocaleString("hu-HU")}%</td><td><strong>${row.cumulativeActual.toLocaleString("hu-HU")}%</strong></td><td>${Number(row.planned_percent || 0).toLocaleString("hu-HU")}%</td><td><strong>${row.cumulativePlanned.toLocaleString("hu-HU")}%</strong></td><td>${formatMoney(row.monthlyCost)}</td></tr>`).join("") : '<tr><td colspan="8">Ehhez a szakághoz még nincs havi adat.</td></tr>'}</tbody></table></div>
        </section>`;
    $$("[data-discipline-name]").forEach((button) => button.addEventListener("click", () => { state.activeDiscipline = button.dataset.disciplineName; renderDisciplines(); }));
    let selectedRow = null;
    $$("[data-progress-id]").forEach((tableRow) => {
        tableRow.addEventListener("click", () => {
            selectedRow = calculatedRows.find((item) => item.id === Number(tableRow.dataset.progressId));
            $$("[data-progress-id]").forEach((item) => item.classList.toggle("selected", item === tableRow));
            if ($("#delete-active-month")) $("#delete-active-month").disabled = false;
        });
        tableRow.addEventListener("dblclick", () => openProgressForm(disciplines, phases, calculatedRows.find((item) => item.id === Number(tableRow.dataset.progressId))));
    });
    $("#discipline-month-form")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = formDataObject(event.currentTarget);
        await api(`/disciplines/${state.project.id}/months/${data.month}-01${toQuery({ phase: data.phase })}`, { method: "POST" });
        toast("A hónap minden szakághoz rögzítve lett.");
        await renderDisciplines();
    });
    $("#delete-active-month")?.addEventListener("click", async () => {
        if (!selectedRow || !confirm(`Biztosan törlöd a(z) ${formatMonth(selectedRow.record_date)} hónapot minden szakágból?`)) return;
        await api(`/disciplines/${state.project.id}/months/${String(selectedRow.record_date).slice(0, 10)}`, { method: "DELETE" });
        toast("A kijelölt hónap törölve lett.");
        await renderDisciplines();
    });
    } catch (error) {
        if (viewRenderIsCurrent(view)) throw error;
    }
}

function openProgressForm(disciplines, phases, row = null) {
    const current = row || { discipline_name: state.activeDiscipline || disciplines[0]?.name || "", record_date: new Date().toISOString().slice(0, 10), phase: "", days: 0, planned_percent: 0, actual_percent: 0 };
    showModal(row ? "Havi szakági adat szerkesztése" : "Havi szakági adat rögzítése", state.project.name, `<form id="progress-form"><div class="form-grid">
        <label>Szakág<select name="discipline_name" required>${disciplines.map((d) => `<option value="${escapeHtml(d.name)}" ${d.name === current.discipline_name ? "selected" : ""}>${escapeHtml(d.name)}</option>`).join("")}</select></label>
        <label>Hónap<input name="record_date" type="date" value="${escapeHtml(String(current.record_date).slice(0, 10))}" required></label><label>Fázis<select name="phase"><option value="">Nincs megadva</option>${phases.map((phase) => `<option value="${escapeHtml(phase.phase_name)}" ${phase.phase_name === current.phase ? "selected" : ""}>${escapeHtml(phase.phase_name)}</option>`).join("")}</select></label>
        <label>Ráfordított nap<input name="days" type="number" min="0" step="0.01" value="${escapeHtml(current.days)}"></label><label>Havi terv (%)<input name="planned_percent" type="number" min="0" max="100" step="0.001" value="${escapeHtml(current.planned_percent)}"></label><label>Havi valós készültség (%)<input name="actual_percent" type="number" min="0" max="100" step="0.001" value="${escapeHtml(current.actual_percent)}"></label>
        </div><div class="modal-actions">${row ? '<button id="delete-progress-row" class="danger-button" type="button">Sor törlése</button>' : ""}<button class="secondary-button" type="button" data-close>Bezárás</button><button class="primary-button" type="submit">Mentés</button></div></form>`);
    $("#progress-form").addEventListener("submit", async (event) => {
        event.preventDefault(); const data = formDataObject(event.currentTarget); data.project_id = state.project.id;
        await api(row ? `/disciplines/${state.project.id}/daily-progress/${row.id}` : `/disciplines/${state.project.id}/daily-progress`, { method: "PUT", body: data }); closeModal(); toast("A havi szakági adat mentése sikerült."); renderDisciplines();
    });
    $("#delete-progress-row")?.addEventListener("click", async () => { if (!confirm("Biztosan törlöd ezt a szakági sort?")) return; await api(`/disciplines/${state.project.id}/daily-progress/${row.id}`, { method: "DELETE" }); closeModal(); toast("A szakági sor törölve lett."); await renderDisciplines(); });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

function renderProjectContractBase() {
    const project = state.project;
    return `<dl class="contract-base-data">
        <div><dt>Megbízó</dt><dd>${escapeHtml(project.main_customer || project.customer || "–")}</dd></div>
        <div><dt>Vállalkozó</dt><dd>${escapeHtml(normalizeResponsibleCompany(project.responsible_company) || "–")}</dd></div>
        <div><dt>Saját státusz</dt><dd>${escapeHtml(project.status || "–")}</dd></div>
        <div class="contract-subject"><dt>Szerződés tárgya</dt><dd>${escapeHtml(project.contract_subject || "–")}</dd></div>
    </dl>`;
}

function renderMilestoneWorkspace(sections, milestones, scheduleRows = []) {
    const originalTotal = sections.reduce((sum, item) => sum + Number(item.original_fee || 0), 0);
    const modifiedTotal = sections.reduce((sum, item) => sum + (Number(item.modified_fee || 0) > 0 ? Number(item.modified_fee) : Number(item.original_fee || 0)), 0);
    const orderedScheduleRows = sortScheduleRows(scheduleRows);
    const phaseNumbers = [...new Set([
        ...sections.map((item) => Number(item.section_no ?? 1)),
        ...milestones.map((item) => Number(item.phase_no ?? 1)),
    ])].sort((left, right) => left - right);
    const allocationBadge = (value) => {
        const normalized = Number(value || 0);
        const stateClass = normalized > 100 ? "over" : normalized === 100 ? "complete" : "open";
        const label = normalized > 100
            ? `Túlosztás: +${(normalized - 100).toLocaleString("hu-HU")}%`
            : normalized === 100
                ? "Teljes: 100%"
                : `Kiosztva: ${normalized.toLocaleString("hu-HU")}% · hátra: ${(100 - normalized).toLocaleString("hu-HU")}%`;
        return `<span class="allocation-badge ${stateClass}">${label}</span>`;
    };
    const sectionRows = sections.length
        ? sections.map((item) => {
            const ratio = Number(item.fee_percent || 0) + Number(item.copyright_percent || 0);
            return `<tr data-contract-section-id="${item.id}" class="${Number(item.section_no) === 0 ? "section-color-0" : ""}">
                <td>${item.section_no}.</td><td>${formatMoney(item.original_fee)}</td><td>${formatMoney(item.modified_fee)}</td>
                <td>${Number(item.fee_percent || 0).toLocaleString("hu-HU")}%</td><td>${Number(item.copyright_percent || 0).toLocaleString("hu-HU")}%</td>
                <td>${allocationBadge(ratio)}</td><td>${formatDate(item.section_date)}</td><td>${escapeHtml(item.note || "")}</td>
            </tr>`;
        }).join("")
        : '<tr><td colspan="8">Nincs főszerződéses pénzügyi fázis.</td></tr>';
    const groups = phaseNumbers.length
        ? phaseNumbers.map((phaseNo) => {
            const phaseMilestones = milestones
                .filter((item) => Number(item.phase_no ?? 1) === phaseNo)
                .sort((left, right) => Number(left.sequence_no || 0) - Number(right.sequence_no || 0) || Number(left.id || 0) - Number(right.id || 0));
            const colorClass = phaseNo === 0 ? "section-color-0" : `section-color-${(phaseNo - 1) % 5 + 1}`;
            const section = sections.find((item) => Number(item.section_no) === phaseNo);
            const base = section ? (Number(section.modified_fee || 0) > 0 ? Number(section.modified_fee) : Number(section.original_fee || 0)) : 0;
            const mdAllocation = phaseMilestones.reduce((sum, item) => sum + Number(item.fee_percent || 0), 0);
            const copyrightAllocation = phaseMilestones.reduce((sum, item) => sum + Number(item.copyright_percent || 0), 0);
            const cards = phaseMilestones.length
                ? phaseMilestones.map((item) => {
                    const mdValue = base * Number(section?.fee_percent || 0) / 100 * Number(item.fee_percent || 0) / 100;
                    const copyrightValue = base * Number(section?.copyright_percent || 0) / 100 * Number(item.copyright_percent || 0) / 100;
                    const linkedScheduleRow = orderedScheduleRows.find((row) => Number(row.id) === Number(item.schedule_row_id))
                        || (!item.schedule_row_id ? orderedScheduleRows.find((row) => row.phase_name === item.reference_name) : null);
                    const relation = item.date_type === "Fix dátum" || item.date_type === "Fix"
                        ? "Fix dátum"
                        : item.date_type === "Ütemterv sorhoz kötve"
                            ? `${linkedScheduleRow ? scheduleRowLabel(linkedScheduleRow) : "Nincs ütemtervsor-hivatkozás"} ${Number(item.offset_days || 0) >= 0 ? "+" : ""}${Number(item.offset_days || 0)} nap`
                            : `${item.reference_name || "Nincs mérföldkő-hivatkozás"} ${Number(item.offset_days || 0) >= 0 ? "+" : ""}${Number(item.offset_days || 0)} nap`;
                    const shortName = item.short_name || item.name || "Névtelen mérföldkő";
                    const officialName = item.official_name || item.name || shortName;
                    return `<article class="milestone-card" data-milestone-id="${item.id}">
                        <header><span>${item.sequence_no}. mérföldkő</span><strong>${escapeHtml(shortName)}</strong></header>
                        <h3 class="milestone-official-name">${escapeHtml(officialName)}</h3>
                        <div class="milestone-dates"><span>Tervezett: <b>${formatDate(item.planned_date)}</b></span><span class="${item.actual_date ? "complete" : "pending"}">Tényleges: <b>${formatDate(item.actual_date)}</b></span><small>${escapeHtml(relation)}</small></div>
                        <dl><div><dt>MD · ${Number(item.fee_percent || 0).toLocaleString("hu-HU")}%</dt><dd>${formatMoney(mdValue)}</dd></div><div><dt>SZJD · ${Number(item.copyright_percent || 0).toLocaleString("hu-HU")}%</dt><dd>${formatMoney(copyrightValue)}</dd></div></dl>
                        <p>${escapeHtml(item.description || "Nincs részletes leírás.")}</p>
                    </article>`;
                }).join("")
                : '<div class="milestone-empty"><strong>Nincs mérföldkő ebben a pénzügyi fázisban.</strong><span>Új mérföldkő közvetlenül hozzárendelhető.</span></div>';
            return `<section class="milestone-group ${colorClass}">
                <div class="milestone-group-heading"><div><strong>${phaseNo}. pénzügyi fázis</strong><small>${phaseMilestones.length} mérföldkő · ${formatMoney(base)} számítási bázis</small></div><div class="milestone-allocation"><span>MD ${allocationBadge(mdAllocation)}</span><span>SZJD ${allocationBadge(copyrightAllocation)}</span></div></div>
                <div class="milestone-grid">${cards}</div>
            </section>`;
        }).join("")
        : empty("Még nincs főszerződéses pénzügyi fázis vagy mérföldkő.");
    return `
        <section class="panel contract-summary">
            <div class="panel-header"><h2>Főszerződés pénzügyi fázisai és projektstátuszok</h2>${canEdit() ? '<button id="new-contract-section" class="secondary-button" type="button">Új pénzügyi fázis</button>' : ""}</div>
            <div class="contract-totals"><span>Főszerződés összesítő</span><div><small>Eredeti</small><strong>${formatMoney(originalTotal)}</strong></div><div><small>Módosított</small><strong>${formatMoney(modifiedTotal)}</strong></div></div>
            ${renderProjectContractBase()}
            <div class="table-wrap"><table><thead><tr><th>Pénzügyi fázis</th><th>Eredeti díj</th><th>Módosított díj</th><th>MD%</th><th>SZJD%</th><th>Arány</th><th>Dátum</th><th>Megjegyzés</th></tr></thead><tbody>${sectionRows}</tbody></table></div>
        </section>
        <div class="toolbar"><div><strong>Pénzügyi mérföldkövek</strong><p class="muted">A főszerződés pénzügyi mérföldkövei dupla kattintással szerkeszthetők.</p></div>${canEdit() ? '<button id="new-milestone" class="primary-button" type="button">Új pénzügyi mérföldkő</button>' : ""}</div>
        <div class="milestone-groups">${groups}</div>`;
}

function wireMilestoneWorkspace(sections, milestones, scheduleRows) {
    $("#new-contract-section")?.addEventListener("click", () => openContractSection(null, sections));
    $$("[data-contract-section-id]").forEach((row) => row.addEventListener("dblclick", () => {
        openContractSection(sections.find((item) => Number(item.id) === Number(row.dataset.contractSectionId)), sections);
    }));
    $("#new-milestone")?.addEventListener("click", () => openMilestone(null, milestones, scheduleRows, sections));
    $$("[data-milestone-id]").forEach((card) => card.addEventListener("dblclick", () => {
        openMilestone(milestones.find((item) => Number(item.id) === Number(card.dataset.milestoneId)), milestones, scheduleRows, sections);
    }));
}

function openContractSection(section, sections) {
    const usedNumbers = new Set(sections.map((item) => Number(item.section_no)));
    const nextNo = [1, 2, 3, 4, 5].find((number) => !usedNumbers.has(number)) ?? 0;
    const current = section || { section_no: nextNo, original_fee: sections.length ? 0 : Number(state.project.contract_value || 0), modified_fee: 0, fee_percent: 90, copyright_percent: 10, section_date: "", note: "" };
    showModal(section ? "Pénzügyi fázis szerkesztése" : "Új pénzügyi fázis", state.project.name, `<form id="contract-section-form"><div class="form-grid">
        <label>Pénzügyi fázis<select name="section_no">${[0, 1, 2, 3, 4, 5].map((number) => `<option value="${number}" ${number === Number(current.section_no) ? "selected" : ""}>${number}. pénzügyi fázis</option>`).join("")}</select></label>
        <label>Eredeti díj (Ft)<input name="original_fee" type="number" min="0" step="0.01" value="${current.original_fee}" required></label>
        <label>Módosított díj (Ft)<input name="modified_fee" type="number" min="0" step="0.01" value="${current.modified_fee}" required></label>
        <label>MD (%)<input name="fee_percent" type="number" min="0" max="100" step="0.01" value="${current.fee_percent}" required></label>
        <label>SZJD (%)<input name="copyright_percent" type="number" min="0" max="100" step="0.01" value="${current.copyright_percent}" required></label>
        <label>Dátum<input name="section_date" type="date" value="${escapeHtml(current.section_date || "")}"></label>
        <label class="span-3">Megjegyzés<textarea name="note" rows="3">${escapeHtml(current.note || "")}</textarea><small class="field-help">Az MD és SZJD arány a mérföldkövek forintértékeinek számítási alapja.</small></label>
        </div><div class="modal-actions">${section ? '<button id="delete-contract-section" type="button" class="danger-button">Törlés</button>' : ""}<button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Mentés</button></div></form>`);
    $("#contract-section-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = formDataObject(event.currentTarget);
        Object.assign(data, {
            project_id: state.project.id,
            section_no: Number(data.section_no),
            original_fee: Number(data.original_fee),
            modified_fee: Number(data.modified_fee),
            fee_percent: Number(data.fee_percent),
            copyright_percent: Number(data.copyright_percent),
            section_date: valueOrNull(data.section_date),
        });
        await api(section ? `/schedules/${state.project.id}/contract-sections/${section.id}` : `/schedules/${state.project.id}/contract-sections`, { method: section ? "PUT" : "POST", body: data });
        closeModal();
        toast("A pénzügyi fázis mentése sikerült.");
        await renderSettings();
    });
    $("#delete-contract-section")?.addEventListener("click", async () => {
        if (!confirm("Biztosan törlöd ezt a pénzügyi fázist?")) return;
        await api(`/schedules/${state.project.id}/contract-sections/${section.id}`, { method: "DELETE" });
        closeModal();
        toast("A pénzügyi fázis törölve lett.");
        await renderSettings();
    });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

function openMilestone(milestone, milestones, scheduleRows, sections) {
    const source = milestone || {};
    const availablePhaseNumbers = [...new Set(sections.map((item) => Number(item.section_no)))].sort((left, right) => left - right);
    const defaultPhaseNo = availablePhaseNumbers[0] ?? 1;
    const current = {
        sequence_no: milestones.length + 1, name: "", short_name: "", official_name: "", elapsed_months: 0,
        fee_percent: 0, copyright_percent: 0, description: "", planned_date: "", phase_no: defaultPhaseNo,
        actual_date: "", date_type: "Fix dátum", reference_name: "", schedule_row_id: null, offset_days: 0,
        ...source,
        short_name: source.short_name || source.name || "",
        official_name: source.official_name || source.name || "",
    };
    if (!availablePhaseNumbers.includes(Number(current.phase_no))) availablePhaseNumbers.push(Number(current.phase_no));
    availablePhaseNumbers.sort((left, right) => left - right);
    const dateType = current.date_type === "Fix" ? "Fix dátum" : current.date_type;
    const orderedRows = sortScheduleRows(scheduleRows);
    const linkedRow = orderedRows.find((row) => Number(row.id) === Number(current.schedule_row_id))
        || (!current.schedule_row_id ? orderedRows.find((row) => row.phase_name === current.reference_name) : null);
    const scheduleOptions = orderedRows.map((row) => `<option value="${row.id}" ${Number(row.id) === Number(linkedRow?.id) ? "selected" : ""}>${escapeHtml(scheduleRowLabel(row))}</option>`).join("");
    const milestoneReferences = milestones
        .filter((item) => Number(item.id) !== Number(current.id))
        .sort((left, right) => Number(left.phase_no ?? 1) - Number(right.phase_no ?? 1) || Number(left.sequence_no || 0) - Number(right.sequence_no || 0));
    const referenceNames = new Set(milestoneReferences.map((item) => item.official_name || item.name).filter(Boolean));
    if (current.reference_name) referenceNames.add(current.reference_name);
    const milestoneOptions = [...referenceNames].map((name) => `<option value="${escapeHtml(name)}" ${name === current.reference_name ? "selected" : ""}>${escapeHtml(name)}</option>`).join("");
    showModal(milestone ? "Mérföldkő szerkesztése" : "Új mérföldkő", state.project.name, `<form id="milestone-form"><div class="form-grid">
        <label class="span-2">Rövid név<input name="short_name" value="${escapeHtml(current.short_name)}" required></label>
        <label class="span-3">Hivatalos név<input name="official_name" value="${escapeHtml(current.official_name)}" required></label>
        <label>Pénzügyi fázis<select name="phase_no" required>${availablePhaseNumbers.map((number) => `<option value="${number}" ${number === Number(current.phase_no) ? "selected" : ""}>${number}. pénzügyi fázis</option>`).join("")}</select></label>
        <label>Sorrend<input name="sequence_no" type="number" min="0" value="${current.sequence_no}" required></label>
        <label>Dátumtípus<select name="date_type"><option ${dateType === "Fix dátum" ? "selected" : ""}>Fix dátum</option><option ${dateType === "Ütemterv sorhoz kötve" ? "selected" : ""}>Ütemterv sorhoz kötve</option><option ${dateType === "Másik mérföldkőhöz kötve" ? "selected" : ""}>Másik mérföldkőhöz kötve</option></select></label>
        <label data-fixed-date>Tervezett dátum<input name="planned_date" type="date" value="${escapeHtml(current.planned_date || "")}"></label>
        <label>Tényleges dátum<input name="actual_date" type="date" value="${escapeHtml(current.actual_date || "")}"></label>
        <label class="span-3" data-schedule-reference-field>Ütemtervsor<select name="schedule_row_id"><option value="">Válassz ütemtervsort</option>${scheduleOptions}</select></label>
        <label class="span-3" data-milestone-reference-field>Hivatkozott mérföldkő<select name="reference_name"><option value="">Válassz mérföldkövet</option>${milestoneOptions}</select></label>
        <label class="span-3" data-offset-field><span data-offset-label></span><input name="offset_days" type="number" value="${current.offset_days}"></label>
        <label>MD (%)<input name="fee_percent" type="number" min="0" max="100" step="0.01" value="${current.fee_percent}"></label>
        <label>SZJD (%)<input name="copyright_percent" type="number" min="0" max="100" step="0.01" value="${current.copyright_percent}"></label>
        <label>Eltelt hónap<input name="elapsed_months" type="number" min="0" value="${current.elapsed_months}"></label>
        <label class="span-3">Részletes leírás<textarea name="description" rows="8" maxlength="5000">${escapeHtml(current.description || "")}</textarea></label>
        </div><div class="modal-actions">${milestone ? '<button id="delete-milestone" type="button" class="danger-button">Törlés</button>' : ""}<button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Mentés</button></div></form>`);
    const updateDateFields = () => {
        const form = $("#milestone-form");
        const selectedType = $('[name="date_type"]', form).value;
        const fixed = selectedType === "Fix dátum";
        const scheduleLinked = selectedType === "Ütemterv sorhoz kötve";
        $("[data-fixed-date]", form).hidden = !fixed;
        $("[data-schedule-reference-field]", form).hidden = !scheduleLinked;
        $("[data-milestone-reference-field]", form).hidden = fixed || scheduleLinked;
        $("[data-offset-field]", form).hidden = fixed;
        $('[name="schedule_row_id"]', form).required = scheduleLinked;
        $('[name="reference_name"]', form).required = !fixed && !scheduleLinked;
        $("[data-offset-label]", form).textContent = scheduleLinked
            ? "Eltolás a hivatkozott ütemtervsor befejezésétől (naptári nap)"
            : "Eltolás a hivatkozott mérföldkő dátumától (naptári nap)";
    };
    $('[name="date_type"]', $("#milestone-form")).addEventListener("change", updateDateFields);
    updateDateFields();
    $("#milestone-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = formDataObject(event.currentTarget);
        const scheduleLinked = data.date_type === "Ütemterv sorhoz kötve";
        const milestoneLinked = data.date_type === "Másik mérföldkőhöz kötve";
        const selectedRow = orderedRows.find((row) => Number(row.id) === Number(data.schedule_row_id));
        data.short_name = data.short_name.trim();
        data.official_name = data.official_name.trim();
        Object.assign(data, {
            name: data.official_name,
            project_id: state.project.id,
            sequence_no: Number(data.sequence_no),
            elapsed_months: Number(data.elapsed_months),
            fee_percent: Number(data.fee_percent),
            copyright_percent: Number(data.copyright_percent),
            phase_no: Number(data.phase_no),
            schedule_row_id: scheduleLinked ? Number(data.schedule_row_id) : null,
            offset_days: Number(data.offset_days || 0),
            planned_date: data.date_type === "Fix dátum" ? valueOrNull(data.planned_date) : null,
            reference_name: scheduleLinked ? selectedRow?.phase_name || "" : milestoneLinked ? data.reference_name : "",
            actual_date: valueOrNull(data.actual_date),
        });
        await api(milestone ? `/schedules/${state.project.id}/milestones/${milestone.id}` : `/schedules/${state.project.id}/milestones`, { method: milestone ? "PUT" : "POST", body: data });
        closeModal();
        toast("A mérföldkő mentése sikerült.");
        await renderSettings();
    });
    $("#delete-milestone")?.addEventListener("click", async () => {
        if (!confirm("Biztosan törlöd ezt a mérföldkövet?")) return;
        await api(`/schedules/${state.project.id}/milestones/${milestone.id}`, { method: "DELETE" });
        closeModal();
        toast("A mérföldkő törölve lett.");
        await renderSettings();
    });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

async function renderSchedule() {
    const view = beginViewRender("schedule");
    if (!view) return;
    try {
    if (state.scheduleView === "milestones") {
        state.settingsView = "milestones";
        return selectModule("settings");
    }
    const [settings, rows, sections, storedMilestones] = await Promise.all([
        api(`/schedules/${state.project.id}/settings`),
        api(`/schedules/${state.project.id}/rows`),
        api(`/schedules/${state.project.id}/contract-sections`),
        api(`/schedules/${state.project.id}/milestones`),
    ]);
    if (!viewRenderIsCurrent(view)) return;
    const phaseNumbers = sections
        .map((section) => Number(section.section_no))
        .filter((value) => Number.isInteger(value))
        .sort((left, right) => left - right);
    const legacyRows = rows.filter((row) => row.financial_phase_no === null || row.financial_phase_no === undefined);
    const hasFinancialPhases = phaseNumbers.length > 0;
    if (
        state.scheduleFinancialPhase === null
        || (state.scheduleFinancialPhase !== "legacy" && state.scheduleFinancialPhase !== "all" && !phaseNumbers.includes(Number(state.scheduleFinancialPhase)))
    ) {
        state.scheduleFinancialPhase = legacyRows.length
            ? "legacy"
            : hasFinancialPhases
                ? String(phaseNumbers[0])
                : "all";
    }
    const selectedLegacyRows = state.scheduleFinancialPhase === "legacy";
    const selectedFinancialPhase = state.scheduleFinancialPhase === "all" || selectedLegacyRows
        ? null
        : Number(state.scheduleFinancialPhase);
    const timelinePhase = state.scheduleView === "combined" ? null : selectedFinancialPhase;
    const timelinePath = `/schedules/${state.project.id}/timeline${toQuery({ financial_phase_no: timelinePhase })}`;
    let timeline;
    try {
        timeline = await api(timelinePath);
    } catch (error) {
        timeline = { project_start: settings.project_start, rows: [], milestones: storedMilestones, error: error.message };
    }
    if (!viewRenderIsCurrent(view)) return;
    state.scheduleSettings = settings;
    state.scheduleTimeline = timeline;
    const orderedRows = sortScheduleRows(
        selectedLegacyRows
            ? legacyRows
            : selectedFinancialPhase === null
                ? rows
                : rows.filter((row) => Number(row.financial_phase_no) === selectedFinancialPhase)
    );
    const isGantt = state.scheduleView === "gantt" || state.scheduleView === "combined";
    const showLegacyOnly = selectedLegacyRows && state.scheduleView !== "combined";
    const milestones = (timeline.milestones || storedMilestones).filter((item) => !showLegacyOnly || item.phase_no === null || item.phase_no === undefined);
    const visibleTimelineRows = showLegacyOnly
        ? (timeline.rows || []).filter((row) => row.financial_phase_no === null || row.financial_phase_no === undefined)
        : timeline.rows || [];
    const phaseLabel = selectedLegacyRows
        ? "Korábbi, pénzügyi fázis nélküli ütemterv"
        : selectedFinancialPhase === null
            ? "Projekt szintű ütemterv"
            : `${selectedFinancialPhase}. pénzügyi fázis`;
    const tabContent = isGantt
        ? `<div class="toolbar"><div><strong>${state.scheduleView === "combined" ? "Összesített Gantt nézet" : "Gantt nézet"}</strong><p class="muted">${state.scheduleView === "combined" ? "Minden pénzügyi fázis közös, színkódolt idővonalon jelenik meg; egy mérföldkő csak egyszer szerepel." : `${escapeHtml(phaseLabel)} tervezési és pénzügyi mérföldkövei ugyanazon a számított idővonalon jelennek meg.`}</p></div><div class="toolbar-group gantt-zoom"><span>Lépték</span><button data-gantt-zoom="daily" class="${state.ganttZoom === "daily" ? "active" : ""}" type="button">Napi</button><button data-gantt-zoom="weekly" class="${state.ganttZoom === "weekly" ? "active" : ""}" type="button">Heti</button><button data-gantt-zoom="monthly" class="${state.ganttZoom === "monthly" ? "active" : ""}" type="button">Havi</button><button data-gantt-zoom="yearly" class="${state.ganttZoom === "yearly" ? "active" : ""}" type="button">Éves</button><button id="calculate-schedule" class="primary-button" type="button">Újraszámítás</button><button id="export-schedule" class="secondary-button" type="button">Excel export</button></div></div>${timeline.error ? `<p class="schedule-error">${escapeHtml(timeline.error)}</p>` : ""}<section class="panel" id="schedule-result">${timeline.error ? empty("Az idővonal hibás hivatkozás miatt nem számítható ki.") : renderGantt(sortScheduleRows(visibleTimelineRows), milestones, state.ganttZoom, timeline, state.scheduleView === "combined", settings.schedule_keys || [])}</section>`
        : renderScheduleEditor(orderedRows, timeline, settings, sections);
    const scheduleKeyRowCount = orderedRows.filter((row) => row.schedule_key_id !== null && row.schedule_key_id !== undefined).length;
    const planningMilestoneCount = orderedRows.length - scheduleKeyRowCount;
    $("#content").innerHTML = `
        <div class="section-heading"><div><h2 class="sr-only">Ütemterv</h2><p>Tervezési és pénzügyi mérföldkövek, Gantt</p></div><span>${scheduleKeyRowCount} tervezési mérföldkőhöz rendelt elem · ${planningMilestoneCount} besorolatlan elem · ${milestones.length} pénzügyi mérföldkő</span></div>
        <div class="toolbar schedule-phase-filter"><label>Pénzügyi fázis<select id="schedule-financial-phase">${hasFinancialPhases ? phaseNumbers.map((phaseNo) => `<option value="${phaseNo}" ${Number(state.scheduleFinancialPhase) === phaseNo ? "selected" : ""}>${phaseNo}. pénzügyi fázis</option>`).join("") : `<option value="all" selected>Projekt szintű</option>`}${legacyRows.length ? `<option value="legacy" ${selectedLegacyRows ? "selected" : ""}>Nincs besorolva</option>` : ""}</select></label><small>Az adott pénzügyi fázis saját ütemtervi elemeit és tervezési mérföldköveit szerkeszted. Az összesített Gantt minden fázist közös idővonalon jelenít meg.</small></div>
        <div class="workspace-tabs" role="tablist">
            <button type="button" data-schedule-view="phases" class="${state.scheduleView === "phases" ? "active" : ""}">Ütemtervi elemek</button>
            <button type="button" data-schedule-view="gantt" class="${state.scheduleView === "gantt" ? "active" : ""}">Gantt-diagram</button>
            <button type="button" data-schedule-view="combined" class="${state.scheduleView === "combined" ? "active" : ""}">Összesített Gantt</button>
        </div>
        <div class="schedule-workspace">${tabContent}</div>`;
    $$("[data-schedule-view]").forEach((button) => button.addEventListener("click", () => { state.scheduleView = button.dataset.scheduleView; renderSchedule(); }));
    $("#schedule-financial-phase")?.addEventListener("change", (event) => { state.scheduleFinancialPhase = event.target.value; renderSchedule(); });
    if (state.scheduleView === "phases") wireScheduleEditor(orderedRows, settings, sections, rows);
    if (isGantt) {
        const redraw = () => { if (!state.scheduleTimeline?.error) $("#schedule-result").innerHTML = renderGantt(sortScheduleRows(showLegacyOnly ? (state.scheduleTimeline.rows || []).filter((row) => row.financial_phase_no === null || row.financial_phase_no === undefined) : (state.scheduleTimeline.rows || [])), state.scheduleTimeline.milestones, state.ganttZoom, state.scheduleTimeline, state.scheduleView === "combined", settings.schedule_keys || []); };
        $("#calculate-schedule")?.addEventListener("click", async () => { state.scheduleTimeline = await api(timelinePath); redraw(); toast("Az ütemezés újraszámítása elkészült."); });
        $("#export-schedule")?.addEventListener("click", () => downloadFile(`/schedules/${state.project.id}/export.xlsx${toQuery({ financial_phase_no: state.scheduleView === "combined" ? null : selectedFinancialPhase })}`, `utemterv-${state.project.id}${selectedFinancialPhase === null || state.scheduleView === "combined" ? "" : `-penzugyi-fazis-${selectedFinancialPhase}`}.xlsx`));
        $$("[data-gantt-zoom]").forEach((button) => button.addEventListener("click", () => { state.ganttZoom = button.dataset.ganttZoom; $$("[data-gantt-zoom]").forEach((item) => item.classList.toggle("active", item === button)); redraw(); }));
        $("#schedule-result")?.addEventListener("wheel", (event) => {
            if (!event.ctrlKey) return;
            event.preventDefault();
            const levels = ["daily", "weekly", "monthly", "yearly"];
            const direction = event.deltaY > 0 ? 1 : -1;
            state.ganttZoom = levels[Math.max(0, Math.min(levels.length - 1, levels.indexOf(state.ganttZoom) + direction))];
            $$("[data-gantt-zoom]").forEach((item) => item.classList.toggle("active", item.dataset.ganttZoom === state.ganttZoom));
            redraw();
        }, { passive: false });
    }
    } catch (error) {
        if (viewRenderIsCurrent(view)) throw error;
    }
}

function compareScheduleRows(left, right) {
    return Number(left.position || 0) - Number(right.position || 0) || Number(left.id || 0) - Number(right.id || 0);
}

function sortScheduleRows(rows) {
    return [...rows].sort(compareScheduleRows);
}

function scheduleRowLabel(row) {
  const financialPhase = row.financial_phase_no === null || row.financial_phase_no === undefined
    ? "Projekt szintű"
    : `Pénzügyi fázis ${row.financial_phase_no}`;
  const type = row.schedule_key_id === null || row.schedule_key_id === undefined
    ? "Nincs tervezési mérföldkőhöz rendelve"
    : `Tervezési mérföldkő${row.phase_code ? `: ${row.phase_code}` : ""}`;
  const activity = row.phase_name || "Névtelen ütemtervi elem";
  return `${financialPhase} · ${type} · Megnevezés: ${activity}`;
}

function renderScheduleEditor(rows, timeline, settings, sections = []) {
  const calculated = new Map((timeline.rows || []).map((row) => [String(row.id), row]));
  const editable = canEdit();
  const scheduleKeys = settings.schedule_keys || [];
  const scheduleKeysAvailable = settings.schedule_keys_available !== false;
  const scheduleKeyError = settings.schedule_keys_error || {};
  const phaseCount = sections.length;

  return `
    <section class="workspace-section schedule-editor">
      <div class="section-heading">
        <div>
          <h2 class="sr-only">Ütemterv</h2>
          <p>${phaseCount > 1 ? "A kiválasztott pénzügyi fázis önálló ütemterve." : "Projektütemterv tervezési mérföldkövekkel, referenciákkal és számított dátumokkal."}</p>
        </div>
        <div class="toolbar schedule-editor-actions">
          ${editable ? '<button id="new-schedule-row" class="primary-button" type="button" data-action="new-schedule-row"><span aria-hidden="true">+</span> Új ütemtervi elem</button>' : ""}
          <button class="secondary-button" type="button" data-action="recalculate-schedule"><span aria-hidden="true">↻</span> Újraszámítás</button>
          <label class="check-label"><input type="checkbox" id="schedule-auto-calculate" ${state.scheduleAutoCalculate ? "checked" : ""} ${editable ? "" : "disabled"}> Automatikus számítás</label>
        </div>
      </div>
      ${scheduleKeys.length ? "" : `<div class="dependency-note"><strong>${scheduleKeysAvailable ? "Nincs betöltött tervezési mérföldkő." : "A tervezési mérföldkövek REST-kapcsolata hibás."}</strong><span>${scheduleKeysAvailable ? "Az ütemtervi elem besorolás nélkül is létrehozható; a tervezési mérföldkő később hozzárendelhető." : escapeHtml(`${scheduleKeyError.message || "A futó backend nem éri el a tervezési mérföldkövek törzsadatát."} (${scheduleKeyError.code || "HTTP 404"})`)}</span></div>`}
      ${renderScheduleRows(rows, calculated, editable, scheduleKeys, sections)}
    </section>`;
}

function referenceOptions(rows, selectedReference = "Projekt kezdete", currentRowId = null) {
  const orderedRows = sortScheduleRows(rows || []);
  const currentRow = orderedRows.find((row) => String(row.id) === String(currentRowId));
  const selected = String(selectedReference || "Projekt kezdete").trim() || "Projekt kezdete";
  const referenceNames = orderedRows
    .filter((row) => {
      if (String(row.id) === String(currentRowId)) return false;
      return !currentRow || compareScheduleRows(row, currentRow) < 0;
    })
    .map((row) => String(row.phase_name || "").trim())
    .filter(Boolean);

  if (selected !== "Projekt kezdete" && !referenceNames.includes(selected)) {
    referenceNames.push(selected);
  }

  const uniqueNames = [...new Set(referenceNames)];
  return [
    `<option value="Projekt kezdete" ${selected === "Projekt kezdete" ? "selected" : ""}>Projekt kezdete</option>`,
    ...uniqueNames.map((name) => `<option value="${escapeHtml(name)}" ${name === selected ? "selected" : ""}>${escapeHtml(name)} vége</option>`),
  ].join("");
}

function renderScheduleRows(rows, calculated, editable, scheduleKeys, sections = []) {
  const keyOptions = (row) => {
    const selectedId = row.schedule_key_id === null || row.schedule_key_id === undefined ? "" : String(row.schedule_key_id);
    const legacyCode = String(row.phase_code || "").trim();
    const matchingKey = scheduleKeys.find((item) => String(item.code || "").trim() === legacyCode);
    const activeId = selectedId || (matchingKey ? String(matchingKey.id) : "");
    return `<option value="">Nincs tervezési mérföldkőhöz rendelve</option>${scheduleKeys.map((item) => `<option value="${escapeHtml(item.id)}" ${String(item.id) === activeId ? "selected" : ""}>${escapeHtml(item.code)}${item.description ? ` - ${escapeHtml(item.description)}` : ""}</option>`).join("")}`;
  };
  const financialPhaseOptions = (row) => sections.length
    ? `<option value="" ${row.financial_phase_no === null || row.financial_phase_no === undefined ? "selected" : ""}>Nincs besorolva</option>${sections.map((section) => `<option value="${section.section_no}" ${Number(row.financial_phase_no) === Number(section.section_no) ? "selected" : ""}>${section.section_no}. pénzügyi fázis</option>`).join("")}`
    : '<option value="" selected>Projekt szintű</option>';

  if (!rows.length) {
    return `<div class="empty-state compact"><strong>Nincs ütemtervi elem ebben a pénzügyi fázisban.</strong><p>Új elem pénzügyi fázissal, tervezési mérföldkővel, referenciával és számítási móddal rögzíthető.</p></div>`;
  }

  return `
    <div class="table-wrap schedule-table-wrap">
      <table class="data-table schedule-table">
        <thead><tr>
          <th>Pénzügyi fázis</th><th>Tervezési mérföldkő</th><th>Ütemtervi elem</th><th>Referencia</th><th>Számítás</th><th>Időtartam</th><th>Eltolás</th><th>Egyedi kezdés</th><th>Kezdés</th><th>Vége</th>
        </tr></thead>
        <tbody>
          ${rows.map((row) => {
            const calc = calculated.get(String(row.id)) || row;
            const calcType = row.calc_type === "workday" ? "Munkanap" : row.calc_type === "calendar" ? "Napt\u00e1ri nap" : (row.calc_type || "Napt\u00e1ri nap");
            const selectedKey = scheduleKeys.find((item) => Number(item.id) === Number(row.schedule_key_id))
              || scheduleKeys.find((item) => String(item.code || "").trim() === String(row.phase_code || "").trim());
            const financialColor = financialPhaseColor(row.financial_phase_no);
            const planningColor = planningMilestoneColor(selectedKey || { id: row.schedule_key_id || row.id });
            return `<tr data-schedule-row="${row.id}">
              <td class="schedule-colored-cell" style="--item-color:${financialColor};--item-tint:${colorTint(financialColor)}"><select data-field="financial_phase_no" ${editable ? "" : "disabled"}>${financialPhaseOptions(row)}</select></td>
              <td class="schedule-colored-cell" style="--item-color:${planningColor};--item-tint:${colorTint(planningColor)}"><select data-field="schedule_key_id" ${editable ? "" : "disabled"}>${keyOptions(row)}</select></td>
              <td><input data-field="phase_name" value="${escapeHtml(row.phase_name || "")}" ${editable ? "" : "disabled"}></td>
              <td><select data-field="reference_name" ${editable ? "" : "disabled"}>${referenceOptions(rows, row.reference_name, row.id)}</select></td>
              <td><select data-field="calc_type" ${editable ? "" : "disabled"}>
                <option value="Naptári nap" ${calcType === "Naptári nap" ? "selected" : ""}>Naptári nap</option>
                <option value="Munkanap" ${calcType === "Munkanap" ? "selected" : ""}>Munkanap</option>
              </select></td>
              <td><input data-field="days" type="number" min="1" value="${escapeHtml(row.days ?? 1)}" ${editable ? "" : "disabled"}></td>
              <td><input data-field="delay" type="number" value="${escapeHtml(row.delay ?? 0)}" ${editable ? "" : "disabled"}></td>
              <td><input data-field="manual_start" type="date" value="${escapeHtml(row.manual_start || "")}" ${editable ? "" : "disabled"}></td>
              <td>${formatDate(calc.calculated_start || calc.start_date)}</td>
              <td>${formatDate(calc.calculated_end || calc.end_date)}</td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>`;
}

async function refreshScheduleCalculations() {
  await renderSchedule();
}

function wireScheduleEditor(rows, settings, sections = [], allRows = rows) {
  document.querySelector('#new-schedule-row')?.addEventListener("click", () => {
    try {
      openScheduleRow(null, allRows, settings.phase_templates || [], settings.schedule_keys || [], sections);
    } catch (error) {
      console.error("Az új ütemtervi elem szerkesztője nem nyitható meg.", error);
      toast(error.message || "Az új ütemtervi elem szerkesztője nem nyitható meg.", true);
    }
  });
  document.querySelector('[data-action="recalculate-schedule"]')?.addEventListener("click", refreshScheduleCalculations);
  document.querySelector('#schedule-auto-calculate')?.addEventListener("change", (event) => {
    state.scheduleAutoCalculate = event.target.checked;
  });
  document.querySelectorAll('[data-schedule-row]').forEach((tr) => {
    tr.addEventListener("dblclick", (event) => {
      if (event.target.closest("input, select, button, textarea, a, label")) return;
      const row = rows.find((item) => String(item.id) === String(tr.dataset.scheduleRow));
      if (row) openScheduleRow(row, allRows, settings.phase_templates || [], settings.schedule_keys || [], sections);
    });
    tr.querySelectorAll('[data-field]').forEach((field) => {
      field.addEventListener("change", async () => {
        if (!state.scheduleAutoCalculate && field.dataset.field !== "financial_phase_no") return;
        const id = tr.dataset.scheduleRow;
        const currentRow = rows.find((item) => String(item.id) === String(id));
        const data = Object.fromEntries([...tr.querySelectorAll('[data-field]')].map((input) => [input.dataset.field, input.value]));
        const financialPhaseValue = valueOrNull(data.financial_phase_no);
        const nextFinancialPhase = financialPhaseValue === null ? null : Number(financialPhaseValue);
        const currentFinancialPhase = currentRow?.financial_phase_no === null || currentRow?.financial_phase_no === undefined ? null : Number(currentRow.financial_phase_no);
        const financialPhaseChanged = nextFinancialPhase !== currentFinancialPhase;
        const payload = {
          project_id: state.project.id,
          position: Number(currentRow?.position || 0),
          schedule_key_id: valueOrNull(data.schedule_key_id) === null ? null : Number(data.schedule_key_id),
          financial_phase_no: nextFinancialPhase,
          phase_name: data.phase_name,
          reference_name: financialPhaseChanged ? "Projekt kezdete" : valueOrNull(data.reference_name),
          calc_type: data.calc_type,
          days: Math.max(1, Number(data.days || 1)),
          delay: Number(data.delay || 0),
          manual_start: valueOrNull(data.manual_start),
        };
        try {
          await api(`/schedules/${state.project.id}/rows/${id}`, { method: "PUT", body: payload });
          await refreshScheduleCalculations();
        } catch (error) {
          toast(error.message, true);
        }
      });
    });
  });
}

function templateOptions(templates = [], selectedTemplateId = "") {
  return templates.map((item) => `<option value="${escapeHtml(item.id)}" ${String(item.id) === String(selectedTemplateId) ? "selected" : ""}>${escapeHtml(item.name || item.phase_name || `Sablon ${item.id}`)}</option>`).join("");
}

function openScheduleRow(row, rows, templates = [], scheduleKeys = [], sections = []) {
  const selectedPhase = state.scheduleFinancialPhase === "all" || state.scheduleFinancialPhase === "legacy" ? null : state.scheduleFinancialPhase;
  const defaultFinancialPhase = sections.length === 1 ? sections[0].section_no : selectedPhase;
  const initialFinancialPhase = row ? row.financial_phase_no : defaultFinancialPhase;
  const current = row || {
    financial_phase_no: initialFinancialPhase,
    schedule_key_id: null,
    phase_name: "",
    reference_name: "Projekt kezdete",
    days: 1,
    delay: 0,
    calc_type: "Naptári nap",
    manual_start: "",
  };
  const selectedKeyId = current.schedule_key_id === null || current.schedule_key_id === undefined ? "" : String(current.schedule_key_id);
  const canChooseFinancialPhase = Boolean(sections.length);
  const keyOptions = `<option value="">Nincs tervezési mérföldkőhöz rendelve</option>${scheduleKeys.map((item) => `<option value="${escapeHtml(item.id)}" ${String(item.id) === selectedKeyId ? "selected" : ""}>${escapeHtml(item.code)}${item.description ? ` - ${escapeHtml(item.description)}` : ""}</option>`).join("")}`;
  const phaseOptions = sections.length
    ? `<option value="">Válassz pénzügyi fázist</option>${sections.map((section) => `<option value="${section.section_no}" ${Number(current.financial_phase_no) === Number(section.section_no) ? "selected" : ""}>Pénzügyi fázis ${section.section_no}</option>`).join("")}`
    : `<option value="">Projekt szintű</option>`;
  const form = `
    <form id="schedule-row-form" class="modal-form">
      <div class="form-context"><span>Pénzügyi fázis</span><strong>${current.financial_phase_no === null || current.financial_phase_no === undefined ? "Nincs besorolva" : `${escapeHtml(current.financial_phase_no)}. pénzügyi fázis`}</strong></div>
      ${canChooseFinancialPhase ? `<label>Pénzügyi fázis hozzárendelése<select name="financial_phase_no" required>${phaseOptions}</select></label>` : ""}
      <label>Ütemtervi sablon<select name="template"><option value="">Egyedi megnevezés</option>${templateOptions(templates)}</select></label>
      <label>Tervezési mérföldkő (opcionális)<select name="schedule_key_id">${keyOptions}</select></label>
      <label>Ütemtervi elem<input name="phase_name" value="${escapeHtml(current.phase_name || "")}" required></label>
      <label>Referencia<select name="reference_name">${referenceOptions(rows, current.reference_name, current.id)}</select></label>
      <label>Számítás<select name="calc_type"><option value="Naptári nap" ${current.calc_type !== "Munkanap" ? "selected" : ""}>Naptári nap</option><option value="Munkanap" ${current.calc_type === "Munkanap" || current.calc_type === "workday" ? "selected" : ""}>Munkanap</option></select></label>
      <label>Időtartam (nap)<input name="days" type="number" min="1" value="${current.days ?? 1}" required></label>
      <label>Eltolás (nap)<input name="delay" type="number" value="${current.delay ?? 0}" required></label>
      <label>Egyedi kezdés<input name="manual_start" type="date" value="${escapeHtml(current.manual_start || "")}"></label>
      <div class="modal-actions">${row ? `<button class="danger-button" type="button" data-action="delete-schedule-row">T\u00f6rl\u00e9s</button>` : ""}<button class="secondary-button" type="button" data-close>Bez\u00e1r\u00e1s</button><button class="primary-button" type="submit">Ment\u00e9s</button></div>
    </form>`;
  showModal(row ? "Ütemtervi elem szerkesztése" : "Új ütemtervi elem", state.project.name, form);
  const formElement = document.querySelector("#schedule-row-form");
  formElement.querySelector("[data-close]")?.addEventListener("click", closeModal);
  formElement.querySelector('[name="template"]').addEventListener("change", (event) => {
    const template = templates.find((item) => String(item.id) === event.target.value);
    if (!template) return;
    formElement.querySelector('[name="phase_name"]').value = template.name || "";
  });
  formElement.querySelector('[name="financial_phase_no"]')?.addEventListener("change", (event) => {
    const selectedPhase = valueOrNull(event.target.value);
    const allowedRows = selectedPhase === null ? rows.filter((item) => item.financial_phase_no === null || item.financial_phase_no === undefined) : rows.filter((item) => Number(item.financial_phase_no) === Number(selectedPhase));
    const reference = formElement.querySelector('[name="reference_name"]');
    reference.innerHTML = referenceOptions(allowedRows, "Projekt kezdete", row?.id);
  });
  formElement.querySelector('[data-action="delete-schedule-row"]')?.addEventListener("click", async () => {
    if (!confirm("Biztosan törlöd ezt az ütemtervi elemet?")) return;
    try {
      await api(`/schedules/${state.project.id}/rows/${row.id}`, { method: "DELETE" });
      closeModal();
      await renderSchedule();
      toast("Az ütemtervi elem törölve lett.");
    } catch (error) {
      toast(error.message, true);
    }
  });
  formElement.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(formElement).entries());
    const financialPhaseValue = canChooseFinancialPhase
      ? valueOrNull(data.financial_phase_no)
      : current.financial_phase_no;
    const payload = {
      project_id: state.project.id,
      position: row?.position || Math.max(0, ...rows.map((item) => Number(item.position || 0))) + 10,
      schedule_key_id: valueOrNull(data.schedule_key_id) === null ? null : Number(data.schedule_key_id),
      financial_phase_no: financialPhaseValue === null || financialPhaseValue === undefined ? null : Number(financialPhaseValue),
      phase_name: data.phase_name,
      reference_name: valueOrNull(data.reference_name),
      days: Math.max(1, Number(data.days || 1)),
      delay: Number(data.delay || 0),
      manual_start: valueOrNull(data.manual_start),
      calc_type: data.calc_type,
    };
    try {
      if (row) {
        await api(`/schedules/${state.project.id}/rows/${row.id}`, { method: "PUT", body: payload });
      } else {
        await api(`/schedules/${state.project.id}/rows`, { method: "POST", body: payload });
      }
      closeModal();
      await renderSchedule();
      toast("Az ütemtervi elem mentése sikeres.");
    } catch (error) {
      toast(error.message, true);
    }
  });
}

function renderGantt(rows, milestones = [], zoom = "daily", timeline = {}, combined = false, scheduleKeys = []) {
    const asDate = (value) => new Date(`${String(value).slice(0, 10)}T12:00:00`);
    const milestoneDates = milestones.filter((item) => item.planned_date).map((item) => asDate(item.planned_date));
    if (!rows.length && !milestoneDates.length) return empty("Nincs dátummal rendelkező ütemtervi elem vagy mérföldkő.");
    const starts = [...rows.map((r) => asDate(r.start_date)), ...milestoneDates];
    const ends = [...rows.map((r) => asDate(r.end_date)), ...milestoneDates];
    const min = new Date(Math.min(...starts)); const max = new Date(Math.max(...ends));
    min.setDate(min.getDate() - (zoom === "daily" ? 2 : 0));
    max.setDate(max.getDate() + (zoom === "daily" ? 5 : 0));
    const cursor = new Date(min);
    if (zoom === "weekly") cursor.setDate(cursor.getDate() - ((cursor.getDay() + 6) % 7));
    if (zoom === "monthly") cursor.setDate(1);
    if (zoom === "yearly") { cursor.setMonth(0, 1); }
    const units = [];
    while (cursor <= max || !units.length) {
        const start = new Date(cursor);
        const next = new Date(cursor);
        if (zoom === "daily") next.setDate(next.getDate() + 1);
        else if (zoom === "weekly") next.setDate(next.getDate() + 7);
        else if (zoom === "monthly") next.setMonth(next.getMonth() + 1);
        else next.setFullYear(next.getFullYear() + 1);
        units.push({ start, end: new Date(next.getTime() - 1) });
        cursor.setTime(next.getTime());
    }
    const unitIndex = (date) => {
        const found = units.findIndex((unit) => date >= unit.start && date <= unit.end);
        return found < 0 ? Math.max(0, units.length - 1) : found;
    };
    const unitWidth = ({ daily: 38, weekly: 76, monthly: 96, yearly: 120 })[zoom] || 38;
    const timelineWidth = units.length * unitWidth;
    const gridStyle = `grid-template-columns:repeat(${units.length}, ${unitWidth}px);width:${timelineWidth}px`;
    const nonWorking = new Set(timeline.non_working_days || []);
    const headers = units.map((unit) => { const date = unit.start; const dateKey = date.toISOString().slice(0, 10); const weekend = zoom === "daily" && nonWorking.has(dateKey); const label = zoom === "daily" ? String(date.getDate()).padStart(2, "0") : zoom === "weekly" ? `${date.getFullYear()} / ${isoWeek(date)}. hét` : zoom === "monthly" ? date.toLocaleDateString("hu-HU", { year: "numeric", month: "short" }) : String(date.getFullYear()); const sub = zoom === "daily" ? date.toLocaleDateString("hu-HU", { weekday: "short" }) : ""; const monthStart = zoom === "daily" && date.getDate() === 1; return `<span class="gantt-day${weekend ? " weekend" : ""}${monthStart ? " month-start" : ""}">${escapeHtml(label)}${sub ? `<small>${escapeHtml(sub)}</small>` : ""}</span>`; }).join("");
    const monthBands = zoom === "daily" ? units.map((unit, index) => ({ unit, index })).filter(({ unit, index }) => index === 0 || unit.start.getMonth() !== units[index - 1].start.getMonth()).map(({ unit, index }, groupIndex, startsOfMonths) => { const nextIndex = startsOfMonths[groupIndex + 1]?.index ?? units.length; return `<span style="grid-column:${index + 1} / span ${nextIndex - index}">${escapeHtml(unit.start.toLocaleDateString("hu-HU", { year: "numeric", month: "long" }))}</span>`; }).join("") : "";
    const today = asDate(new Date().toISOString().slice(0, 10));
    const todayIndex = today >= units[0].start && today <= units[units.length - 1].end ? unitIndex(today) : -1;
    const nonWorkingColumns = zoom === "daily" ? units.map((unit, index) => nonWorking.has(unit.start.toISOString().slice(0, 10)) ? `<span class="gantt-nonworking" style="grid-column:${index + 1}"></span>` : "").join("") : "";
    const milestoneLane = milestones.length ? `<div class="gantt-row gantt-milestone-row"><strong>Pénzügyi mérföldkövek<small>${milestones.length} főszerződéses esemény</small></strong><div class="gantt-lane" style="${gridStyle}">${nonWorkingColumns}${milestones.filter((item) => item.planned_date).map((item) => { const column = unitIndex(asDate(item.planned_date)) + 1; return `<span class="gantt-milestone phase-${Number(item.phase_no || 1)}" style="grid-column:${column}" title="${escapeHtml(`${item.name} · ${formatDate(item.planned_date)} · ${item.phase_no}. pénzügyi fázis`)}"><b>◆</b><small>${escapeHtml(item.name)}</small></span>`; }).join("")}</div></div>` : "";
    const scheduleKeyById = new Map(scheduleKeys.map((item) => [String(item.id), item]));
    const planningGroups = new Map();
    rows.filter((row) => row.schedule_key_id !== null && row.schedule_key_id !== undefined && row.start_date && row.end_date).forEach((row) => {
        const phaseNo = row.financial_phase_no === null || row.financial_phase_no === undefined ? "unassigned" : String(row.financial_phase_no);
        const groupId = `${combined ? `${phaseNo}:` : ""}${row.schedule_key_id}`;
        const key = scheduleKeyById.get(String(row.schedule_key_id));
        const start = asDate(row.start_date);
        const end = asDate(row.end_date);
        const existing = planningGroups.get(groupId);
        if (existing) {
            if (start < existing.start) existing.start = start;
            if (end > existing.end) existing.end = end;
            existing.itemCount += 1;
            return;
        }
        planningGroups.set(groupId, {
            id: groupId,
            code: key?.code || row.phase_code || "Tervezési mérföldkő",
            description: key?.description || "",
            financialPhaseNo: row.financial_phase_no,
            start,
            end,
            itemCount: 1,
        });
    });
    const planningPeriods = [...planningGroups.values()].sort((left, right) => left.start - right.start || left.end - right.end || left.code.localeCompare(right.code, "hu"));
    const planningLane = planningPeriods.length ? `<div class="gantt-row gantt-planning-row"><strong>Tervezési mérföldkövek<small>${planningPeriods.length} időszak</small></strong><div class="gantt-lane" style="${gridStyle}">${nonWorkingColumns}${todayIndex >= 0 ? `<span class="gantt-today" style="grid-column:${todayIndex + 1}"></span>` : ""}${planningPeriods.map((period, index) => { const start = unitIndex(period.start) + 1; const width = Math.max(1, unitIndex(period.end) - unitIndex(period.start) + 1); const phasePrefix = combined && period.financialPhaseNo !== null && period.financialPhaseNo !== undefined ? `${period.financialPhaseNo}. pénzügyi fázis · ` : ""; const title = `${phasePrefix}${period.code}${period.description ? ` - ${period.description}` : ""} · ${formatDate(period.start)} – ${formatDate(period.end)} · ${period.itemCount} ütemtervi elem`; return `<i class="gantt-planning-bar color-${index % 5}" style="grid-column:${start} / span ${width}" title="${escapeHtml(title)}"><span>${escapeHtml(period.code)}</span></i>`; }).join("")}</div></div>` : "";
    return `<div class="gantt-scroll"><div class="gantt" style="width:${330 + timelineWidth}px;--gantt-unit:${unitWidth}px"><div class="gantt-head"><span>${combined ? "Pénzügyi fázisok / ütemtervi elemek" : "Tervezési mérföldkövek / ütemtervi elemek"}</span><div class="gantt-timeline-head" style="width:${timelineWidth}px">${monthBands ? `<div class="gantt-months" style="${gridStyle}">${monthBands}</div>` : ""}<div class="gantt-days" style="${gridStyle}">${headers}</div></div></div>${milestoneLane}${planningLane}${rows.map((r, index) => { const rowStart = asDate(r.start_date); const rowEnd = asDate(r.end_date); const start = unitIndex(rowStart) + 1; const width = Math.max(1, unitIndex(rowEnd) - unitIndex(rowStart) + 1); const days = Math.max(1, Math.round((rowEnd - rowStart) / 86400000) + 1); const phaseNo = Number(r.financial_phase_no); const phasePrefix = combined && Number.isInteger(phaseNo) ? `${phaseNo}. pénzügyi fázis · ` : ""; const hasPlanningMilestone = r.schedule_key_id !== null && r.schedule_key_id !== undefined; const keyPrefix = hasPlanningMilestone ? (r.phase_code ? `${r.phase_code} - ` : "Tervezési mérföldkő · ") : "Ütemtervi elem · "; const label = width * unitWidth > 170 ? keyPrefix + r.phase_name : `${days}n`; const delay = Number(r.delay || 0); const color = combined && Number.isInteger(phaseNo) ? ((phaseNo % 5 + 5) % 5) : index % 5; return `<div class="gantt-row"><strong title="${escapeHtml(phasePrefix + keyPrefix + r.phase_name)}">${escapeHtml(phasePrefix + keyPrefix + r.phase_name)}<small>${formatDate(r.start_date)} – ${formatDate(r.end_date)} · ${days} nap${delay ? ` · ${delay > 0 ? "+" : ""}${delay} nap eltérés` : ""}</small></strong><div class="gantt-lane" style="${gridStyle}">${nonWorkingColumns}${todayIndex >= 0 ? `<span class="gantt-today" style="grid-column:${todayIndex + 1}"></span>` : ""}<i class="gantt-bar color-${color}" style="grid-column:${start} / span ${width}" title="${escapeHtml(phasePrefix + keyPrefix + r.phase_name)} · ${formatDate(r.start_date)} – ${formatDate(r.end_date)}"><span>${escapeHtml(label)}</span></i>${r.manual_start ? `<span class="gantt-manual" style="grid-column:${start}" title="Kézzel megadott kezdés">◆</span>` : ""}</div></div>`; }).join("")}</div></div>`;
}

function isoWeek(value) {
    const date = new Date(Date.UTC(value.getFullYear(), value.getMonth(), value.getDate()));
    date.setUTCDate(date.getUTCDate() + 4 - (date.getUTCDay() || 7));
    const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
    return Math.ceil((((date - yearStart) / 86400000) + 1) / 7);
}

async function renderSubcontractors() {
    const view = beginViewRender("subcontractors");
    if (!view) return;
    try {
    const workspace = await api(`/subcontractors/${state.project.id}/workspace`);
    if (!viewRenderIsCurrent(view)) return;
    const { workflows, matrix, catalog } = workspace;
    state.subcontractorCatalog = catalog;
    const signed = workflows.filter((workflow) => workflow.signature_status === "Aláírva").length;
    const statusOf = (workflow) => workflow.signature_status === "Aláírva" ? "Aláírva" : workflow.acceptance === "Elfogadva" ? "Elfogadva" : workflow.no_offer ? "Nem adott ajánlatot" : workflow.offer_status || "Folyamatban";
    const folderItems = [...(catalog.folders || [])];
    const folderNames = new Set(folderItems.map((folder) => String(folder.name || "")));
    [...new Set(workflows.map((workflow) => workflow.discipline || "Besorolatlan"))].filter((name) => !folderNames.has(name)).forEach((name) => folderItems.push({ id: null, name, code: "", display_order: 99999 }));
    const grouped = folderItems.map((folder) => ({ folder, workflows: workflows.filter((workflow) => (workflow.discipline || "Besorolatlan") === folder.name) }));
    const offerRows = grouped.map(({ folder, workflows: groupWorkflows }) => {
        const rows = groupWorkflows.map((workflow) => {
            const status = statusOf(workflow);
            const rowClass = workflow.signature_status === "Aláírva" ? "signed" : workflow.acceptance === "Elfogadva" ? "accepted" : "";
            const searchText = `${workflow.code || ""} ${workflow.company_name} ${workflow.discipline || ""} ${status}`.toLocaleLowerCase("hu-HU");
            const details = (workflow.offer_parts || []).map((part) => `<tr class="offer-part-row" data-search-text="${escapeHtml(`${workflow.company_name} ${part.phase_name}`.toLocaleLowerCase("hu-HU"))}"><td></td><td><span>Részajánlat</span> ${escapeHtml(part.phase_name)}</td><td></td><td>${formatMoney(parseMoneyNumber(part.amount))}${part.optional ? " · opcionális" : ""}</td><td></td><td></td></tr>`).join("");
            return `<tr class="workflow-row ${rowClass}" data-workflow-id="${workflow.id}" data-search-text="${escapeHtml(searchText)}" title="Dupla kattintással szerkeszthető; jobb kattintással is megnyitható"><td>${escapeHtml(workflow.code || "–")}</td><td><strong>${escapeHtml(workflow.company_name)}</strong><small>${escapeHtml(workflow.status_note || "")}</small></td><td>${workflow.preliminary_estimate ? formatMoney(parseMoneyNumber(workflow.preliminary_estimate)) : "–"}</td><td><strong>${escapeHtml(workflow.no_offer ? "Nem adott ajánlatot" : workflow.offer_status || "Nincs adat")}</strong><small>${workflow.offer_price ? formatMoney(parseMoneyNumber(workflow.offer_price)) : ""}</small></td><td><span class="workflow-status ${rowClass}">${escapeHtml(status)}</span></td><td>${workflow.modified_total || workflow.contract_total ? `<strong>${formatMoney(parseMoneyNumber(workflow.modified_total || workflow.contract_total))}</strong>` : "–"}<small>${escapeHtml(workflow.signature_status || "")}</small></td><td><button type="button" class="secondary-button workflow-open" data-open-workflow="${workflow.id}">Megnyitás</button></td></tr>${details}`;
        }).join("");
        return `<tbody class="subcontractor-group" data-folder-id="${folder.id || ""}" data-folder-name="${escapeHtml(folder.name)}" ${folder.id && canEdit() ? 'draggable="true"' : ""}><tr class="subcontractor-folder-row"><td colspan="6"><div><span class="folder-grip" aria-hidden="true">⋮⋮</span><strong>${escapeHtml(folder.name)}</strong>${folder.code ? `<small>${escapeHtml(folder.code)}</small>` : ""}<span>${groupWorkflows.length} folyamat</span>${folder.id && canEdit() ? `<button type="button" class="icon-button" data-edit-folder="${folder.id}" title="Szakági mappa szerkesztése">✎</button>` : ""}</div></td></tr>${rows || '<tr class="folder-empty"><td colspan="6">Ebben a szakágban még nincs ajánlatkérés.</td></tr>'}</tbody>`;
    }).join("");
    const body = state.subcontractorView === "matrix" ? renderContractMatrixModern(matrix) : `
        <div class="toolbar subcontractor-toolbar"><div><strong>Alvállalkozói ajánlatok és szerződéses folyamatok</strong><p class="muted">Szakáganként csoportosítva. A szakági fejléc húzással átrendezhető, a folyamat dupla kattintással nyitható meg.</p></div><div class="toolbar-group"><input id="subcontractor-search" type="search" placeholder="Keresés kódra, cégre, szakágra vagy státuszra" value="${escapeHtml(state.subcontractorSearch || "")}"><button id="export-subcontractors" class="secondary-button" type="button">Excel export</button>${canEdit() ? '<button id="new-subcontractor-folder" class="secondary-button" type="button">Új szakág</button><button id="new-workflow" class="primary-button" type="button">Új ajánlatkérés</button>' : ""}</div></div>
        <div class="subcontractor-workspace" style="--workflow-panel-width:${Number(state.workflowPanelWidth || 460)}px"><section class="panel subcontractor-offers"><div class="panel-header"><h2>Ajánlatkérések kezelése</h2><span id="subcontractor-result-count">${workflows.length} folyamat</span></div><div class="table-wrap"><table><thead><tr><th>Kód</th><th>Alvállalkozó / feladat</th><th>Előzetes kalkuláció</th><th>Ajánlat</th><th>Aktuális állapot</th><th>Szerződés</th><th><span class="sr-only">Művelet</span></th></tr></thead>${offerRows || '<tbody><tr><td colspan="6">Nincs alvállalkozói folyamat.</td></tr></tbody>'}</table></div></section><div id="workflow-panel-resizer" class="workflow-panel-resizer" role="separator" aria-label="Folyamatpanel szélességének módosítása" aria-orientation="vertical" title="Húzd balra vagy jobbra a panel átméretezéséhez"></div><aside id="subcontractor-workflow-panel" class="workflow-side-panel"><div class="workflow-panel-empty"><strong>Válassz egy folyamatot</strong><p>A Megnyitás gombbal megjelenik a folyamat részletezése.</p></div></aside></div>`;
    $("#content").innerHTML = `<div class="section-heading"><div><h2 class="sr-only">Alvállalkozók</h2><p>ajánlatok, szerződések és kifizetési mátrix</p></div><span>${signed} aláírt szerződés</span></div><div class="workspace-tabs"><button data-subcontractor-view="offers" class="${state.subcontractorView === "offers" ? "active" : ""}" type="button">Ajánlatkérések kezelése</button><button data-subcontractor-view="matrix" class="${state.subcontractorView === "matrix" ? "active" : ""}" type="button">Kifizetési mátrix</button></div><div class="schedule-workspace">${body}</div>`;
    $$("[data-subcontractor-view]").forEach((button) => button.addEventListener("click", () => { state.subcontractorView = button.dataset.subcontractorView; renderSubcontractors(); }));
    $("#new-workflow")?.addEventListener("click", () => openWorkflow(null, catalog));
    $("#new-subcontractor-folder")?.addEventListener("click", () => openSubcontractorFolder(null, catalog.folders || [], catalog.categories || []));
    $("#export-subcontractors")?.addEventListener("click", () => downloadFile(`/subcontractors/${state.project.id}/export.xlsx`, `alvallalkozok-${state.project.id}.xlsx`));
    $("#subcontractor-search")?.addEventListener("input", (event) => {
        state.subcontractorSearch = event.target.value;
        const needle = event.target.value.trim().toLocaleLowerCase("hu-HU");
        let visible = 0;
        $$(".subcontractor-group").forEach((group) => {
            const folderMatches = Boolean(needle && String(group.dataset.folderName || "").toLocaleLowerCase("hu-HU").includes(needle));
            let groupVisible = 0;
            $$(".workflow-row", group).forEach((row) => { const show = !needle || folderMatches || row.dataset.searchText.includes(needle); row.hidden = !show; if (show) { visible += 1; groupVisible += 1; } });
            $$(".offer-part-row", group).forEach((row) => { row.hidden = Boolean(needle && !folderMatches && !row.dataset.searchText.includes(needle)); });
            group.hidden = Boolean(needle && !groupVisible && !folderMatches);
        });
        $("#subcontractor-result-count").textContent = `${visible} folyamat`;
    });
    $("#subcontractor-search")?.dispatchEvent(new Event("input"));
    $$("[data-workflow-id]").forEach((element) => {
        const workflow = workflows.find((item) => item.id === Number(element.dataset.workflowId));
        const open = () => openWorkflowPanel(workflow, catalog);
        element.addEventListener("dblclick", open);
        element.addEventListener("contextmenu", (event) => { event.preventDefault(); openWorkflowContextMenu(event, workflow, catalog); });
    });
    $$("[data-edit-folder]").forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); openSubcontractorFolder((catalog.folders || []).find((folder) => folder.id === Number(button.dataset.editFolder)), catalog.folders || [], catalog.categories || []); }));
    $$('[data-open-workflow]').forEach((button) => button.addEventListener("click", (event) => {
        event.stopPropagation();
        const workflow = workflows.find((item) => item.id === Number(button.dataset.openWorkflow));
        openWorkflowPanel(workflow, catalog);
    }));
    wireSubcontractorFolderDrag();
    wireWorkflowPanelResize();
    $$("[data-matrix-cell]").forEach((element) => element.addEventListener("dblclick", () => openMatrixCell({ id: Number(element.dataset.matrixCellId) || null, project_id: state.project.id, stage_id: Number(element.dataset.stageId) || null, reference_id: element.dataset.referenceId, column_code: element.dataset.columnCode, percent: element.dataset.percent || null, amount: Number(element.dataset.amount || 0), base_amount: Number(element.dataset.baseAmount || 0), text_value: element.dataset.textValue || "", cell_type: element.dataset.cellType || "money", locked: element.dataset.locked === "true" })));
    $$("[data-matrix-base]").forEach((element) => element.addEventListener("dblclick", () => openMatrixBaseValue(element.dataset.matrixBase, Number(element.dataset.amount || 0), element.dataset.locked === "true")));
    $("#new-matrix-stage")?.addEventListener("click", () => openMatrixStage(null, matrix.stages));
    $$("[data-matrix-stage-id]").forEach((element) => element.addEventListener("dblclick", () => openMatrixStage(matrix.stages.find((stage) => stage.id === Number(element.dataset.matrixStageId)), matrix.stages)));
    $$("[data-toggle-matrix-notes]").forEach((button) => button.addEventListener("click", () => { const workflowId = button.dataset.toggleMatrixNotes; $$(`[data-matrix-note-workflow="${workflowId}"]`).forEach((row) => row.hidden = !row.hidden); button.classList.toggle("active"); }));
    $(".matrix-table-wrap")?.addEventListener("wheel", (event) => { if (!event.ctrlKey) return; event.preventDefault(); state.matrixZoom = Math.max(.75, Math.min(1.45, Number(state.matrixZoom || 1) + (event.deltaY < 0 ? .1 : -.1))); renderSubcontractors(); }, { passive: false });
    } catch (error) {
        if (viewRenderIsCurrent(view)) throw error;
    }
}

function wireWorkflowPanelResize() {
    const workspace = $(".subcontractor-workspace");
    const resizer = $("#workflow-panel-resizer");
    if (!workspace || !resizer) return;
    resizer.addEventListener("pointerdown", (event) => {
        if (window.matchMedia("(max-width: 980px)").matches) return;
        event.preventDefault();
        resizer.setPointerCapture?.(event.pointerId);
        document.body.classList.add("workflow-panel-resizing");
        const resize = (pointerEvent) => {
            const bounds = workspace.getBoundingClientRect();
            const maxWidth = Math.max(420, Math.min(980, bounds.width - 420));
            const width = Math.max(380, Math.min(maxWidth, bounds.right - pointerEvent.clientX));
            state.workflowPanelWidth = Math.round(width);
            workspace.style.setProperty("--workflow-panel-width", `${state.workflowPanelWidth}px`);
        };
        const stop = () => {
            document.body.classList.remove("workflow-panel-resizing");
            window.removeEventListener("pointermove", resize);
            window.removeEventListener("pointerup", stop);
            window.removeEventListener("pointercancel", stop);
        };
        window.addEventListener("pointermove", resize);
        window.addEventListener("pointerup", stop);
        window.addEventListener("pointercancel", stop);
    });
}

const workflowPanelSteps = [
    "Alapadatok", "Ajánlatkérés", "Ajánlat beérkezése", "Döntés", "Szerződés", "Aláírás", "Módosítások",
];

const offerRequestFields = [
    "work_number", "history", "task_description", "request_text", "response_deadline", "schedule_text",
    "finance_text", "note", "attachments", "contacts", "document_date",
];
const offerRequestDateFields = new Set(["response_deadline", "document_date"]);

function offerRequestDataPayload(data = {}) {
    return Object.fromEntries(offerRequestFields.map((key) => [
        key,
        offerRequestDateFields.has(key) ? (data[key] || null) : String(data[key] ?? ""),
    ]));
}

function offerRequestPayload(source = {}) {
    const data = source.data || source;
    return {
        title: String(source.title || "Árajánlatkérő"),
        data: offerRequestDataPayload(data),
    };
}

function offerRequestFormPayload(form) {
    const raw = formDataObject(form);
    return {
        title: raw.title || "Árajánlatkérő",
        data: offerRequestDataPayload(raw),
    };
}

function companyContactText(contact = {}) {
    const identity = [contact.name, contact.job_title].filter(Boolean).join(" – ");
    const availability = [contact.email, contact.phone].filter(Boolean).join(" · ");
    return [identity, availability].filter(Boolean).join(" | ");
}

function documentLoadErrorContent(documentError) {
    const status = Number(documentError?.status || 0);
    if (status === 403) {
        return `<div class="dependency-note danger"><strong>Nincs hozzáférés a dokumentumtárhoz.</strong><span>${escapeHtml(documentError.message)}</span><small>A bejelentkezett felhasználó JWT-je továbbításra került, de a Supabase RLS nem engedte ezt a projektműveletet. Ellenőrizd a projekt-hozzáférést és a dokumentumszabályokat.</small></div>`;
    }
    if (status === 404) {
        return `<div class="dependency-note danger"><strong>A dokumentum API vagy a keresett dokumentum nem található.</strong><span>${escapeHtml(documentError.message)}</span><small>Ez nem jogosultsági hiba. Ellenőrizd a telepített backend-verziót és az API útvonalat.</small></div>`;
    }
    if (status >= 500) {
        return `<div class="dependency-note danger"><strong>A dokumentumtár kiszolgálása hibát jelzett.</strong><span>${escapeHtml(documentError.message)}</span><small>Ellenőrizd, hogy a legújabb adatbázis-migráció lefutott-e.</small></div>`;
    }
    return `<div class="dependency-note danger"><strong>A dokumentumok betöltése nem sikerült.</strong><span>${escapeHtml(documentError?.message)}</span><small>Ellenőrizd a hálózati kapcsolatot, majd próbáld újra.</small></div>`;
}

function offerRequestLauncherContent(workflow, document, documentError) {
    if (documentError) return documentLoadErrorContent(documentError);
    const status = document
        ? `<span class="document-status ${escapeHtml(document.status)}">${document.status === "issued" ? "Kiadva" : document.status === "draft" ? "Piszkozat" : "Korábbi változat"} · v${document.revision_no}</span>`
        : '<span class="document-status">Még nincs dokumentum</span>';
    return `<div class="workflow-panel-step-content document-launcher">
        <div class="workflow-document-heading"><div><h3>Ajánlatkérő dokumentum</h3><p>A folyamatadatokból összeállítható, menthető, előnézhető és exportálható.</p></div>${status}</div>
        ${workflowPanelSummary(workflow, 2)}
        <button id="open-offer-request-editor" class="primary-button document-builder-button" type="button">Ajánlatkérő összeállítása</button>
    </div>`;
}

function documentExportErrorMessage(error) {
    if (Number(error?.status) === 403) return "Nincs jogosultságod a dokumentum előképéhez vagy exportjához.";
    if (Number(error?.status) === 404) return "A mentett dokumentum nem található.";
    return error?.message || "A dokumentum előállítása nem sikerült.";
}

async function previewSavedDocument(path) {
    const previewWindow = window.open("about:blank", "_blank");
    if (!previewWindow) {
        toast("A böngésző letiltotta az előkép új lapját.", true);
        return;
    }
    previewWindow.opener = null;
    previewWindow.document.title = "Dokumentum-előkép betöltése";
    previewWindow.document.body.textContent = "A PDF-előkép betöltése folyamatban…";
    try {
        const blob = await api(path);
        const url = URL.createObjectURL(blob);
        previewWindow.location.replace(url);
        setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) {
        previewWindow.close();
        toast(documentExportErrorMessage(error), true);
    }
}

async function downloadSavedDocument(path, filename) {
    try {
        const blob = await api(path);
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        toast("A dokumentumexport elkészült.");
    } catch (error) {
        toast(documentExportErrorMessage(error), true);
    }
}

function workflowPanelSummary(workflow, step) {
    const values = [
        ["Szakág", workflow.discipline || "–"],
        ["Cég", workflow.company_name || "–"],
        ["Aktuális státusz", workflow.signature_status || workflow.acceptance || workflow.offer_status || "–"],
    ];
    if (step === 3) values.push(["Ajánlati ár", workflow.offer_price ? formatMoney(parseMoneyNumber(workflow.offer_price)) : "–"]);
    if (step === 4) values.push(["Döntés", workflow.acceptance || "–"]);
    if (step === 5) values.push(["Szerződés", workflow.contract_total ? formatMoney(parseMoneyNumber(workflow.contract_total)) : "–"]);
    if (step === 6) values.push(["Aláírás", workflow.signature_status || "–"]);
    return `<dl class="workflow-panel-summary">${values.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>`;
}

function offerRequestPanelContent(workflow, document, defaults, documentError) {
    if (documentError) return documentLoadErrorContent(documentError);
    const data = { ...(defaults?.data || {}), ...(document?.data || {}) };
    const currentStep = Math.max(1, Math.min(7, Number(workflow.current_step || 1)));
    const editable = canEdit() && (!document || document.status === "draft");
    const readonly = editable ? "" : "readonly";
    const dateValue = (value) => String(value || "").slice(0, 10);
    const contactOptions = (defaults?.company_contacts || []).map((contact) => `<option value="${contact.id}">${escapeHtml(companyContactText(contact))}</option>`).join("");
    const saveAction = editable
        ? `<button id="save-offer-request-top" class="primary-button document-export-button" type="button">${document ? "Mentés" : "Piszkozat létrehozása"}</button>`
        : "";
    const exportActions = document
        ? `<div class="document-export-copy"><strong>Dokumentumműveletek</strong><span>Az előkép és az export a legutóbb mentett állapotból készül.</span></div>
           ${saveAction}
           <button id="preview-offer-request" class="secondary-button document-export-button" type="button" title="A mentett dokumentum megnyitása PDF-előképként">Előkép</button>
           <label class="document-export-format"><span>Formátum</span><select id="offer-request-export-format" aria-label="Export formátuma"><option value="pdf">PDF</option><option value="word">Word (.docx)</option></select></label>
           <button id="export-offer-request" class="secondary-button document-export-button" type="button">Exportálás</button>`
        : `<div class="document-export-copy"><strong>Dokumentumműveletek</strong><span>Az előképhez és exporthoz előbb mentsd el a piszkozatot.</span></div>
           ${saveAction}
           <button class="secondary-button document-export-button" type="button" disabled title="Előbb hozd létre a dokumentum piszkozatát">Előkép</button>
           <label class="document-export-format disabled"><span>Formátum</span><select disabled aria-label="Export formátuma"><option>PDF</option><option>Word (.docx)</option></select></label>
           <button class="secondary-button document-export-button" type="button" disabled title="Előbb hozd létre a dokumentum piszkozatát">Exportálás</button>`;
    const editActions = editable
        ? `${document && currentStep === 2 ? '<button id="issue-offer-request" class="primary-button" type="button">Ajánlatkérő kiadása</button>' : ""}`
        : "";
    const revisionAction = document?.status === "issued" && canEdit()
        ? '<button id="new-offer-request-revision" class="secondary-button" type="button">Új változat készítése</button>'
        : "";
    const status = document
        ? `<span class="document-status ${escapeHtml(document.status)}">${document.status === "issued" ? "Kiadva" : document.status === "draft" ? "Piszkozat" : "Korábbi változat"} · v${document.revision_no}</span>`
        : '<span class="document-status">Még nincs dokumentum</span>';
    const lockedNote = !editable && document?.status !== "draft"
        ? '<div class="dependency-note">A kiadott dokumentum nem írható át. Szerkesztéshez készíts új változatot.</div>'
        : "";
    return `<div class="workflow-panel-document"><div class="workflow-document-heading"><div><button id="close-offer-request-editor" class="document-back-button" type="button">Vissza a folyamathoz</button><h3>Árajánlatkérő</h3><p>A projekt és a folyamat ismert adatai automatikusan bekerülnek.</p></div>${status}</div>
        <div class="document-export-toolbar">${exportActions}</div>${lockedNote}
        <div class="document-auto-data"><span><b>Projekt</b>${escapeHtml(data.project_name || state.project.name)}</span><span><b>Címzett</b>${escapeHtml(data.company_name || workflow.company_name)}</span><span><b>Szakág</b>${escapeHtml(data.discipline || workflow.discipline || "–")}</span></div>
        <form id="offer-request-document-form" class="workflow-document-form">
            <label>Dokumentum címe<input name="title" value="${escapeHtml(document?.title || defaults?.title || "Árajánlatkérő")}" ${readonly}></label>
            <label>Munkaszám<input name="work_number" value="${escapeHtml(data.work_number || "")}" ${readonly}></label>
            <label>Előzmények<textarea name="history" rows="3" ${readonly}>${escapeHtml(data.history || "")}</textarea></label>
            <label>Tervezési feladat részletezése<textarea name="task_description" rows="4" ${readonly}>${escapeHtml(data.task_description || "")}</textarea></label>
            <label>Ajánlatkérés<textarea name="request_text" rows="3" ${readonly}>${escapeHtml(data.request_text || "")}</textarea></label>
            <div class="form-grid"><label>Ajánlati határidő<input name="response_deadline" type="date" value="${escapeHtml(dateValue(data.response_deadline))}" ${readonly}></label><label>Dokumentum dátuma<input name="document_date" type="date" value="${escapeHtml(dateValue(data.document_date))}" ${readonly}></label></div>
            <label>Ütemezés<textarea name="schedule_text" rows="4" ${readonly}>${escapeHtml(data.schedule_text || "")}</textarea></label>
            <label>Pénzügyek<textarea name="finance_text" rows="3" ${readonly}>${escapeHtml(data.finance_text || "")}</textarea></label>
            <label>Megjegyzés<textarea name="note" rows="2" ${readonly}>${escapeHtml(data.note || "")}</textarea></label>
            <label>Csatolmányok / hivatkozások<textarea name="attachments" rows="2" ${readonly}>${escapeHtml(data.attachments || "")}</textarea></label>
            ${editable && contactOptions ? `<div class="document-contact-picker"><label>Belső kapcsolattartó<select id="offer-request-contact-select"><option value="">Válassz személyt</option>${contactOptions}</select></label><button id="add-offer-request-contact" class="secondary-button" type="button">Hozzáadás</button></div>` : ""}
            <label>Kapcsolattartás<textarea name="contacts" rows="2" ${readonly}>${escapeHtml(data.contacts || "")}</textarea></label>
            <div class="workflow-panel-actions">${editActions}${revisionAction}</div>
        </form></div>`;
}

async function openWorkflowPanel(workflow, catalog = state.subcontractorCatalog || { folders: [], subcontractors: [], categories: [] }) {
    if (!workflow?.id) return;
    const navigation = state.navigationVersion;
    const performanceScope = beginPerformanceScope("dokumentumpanel");
    const panel = $("#subcontractor-workflow-panel");
    if (!panel) {
        endPerformanceScope(performanceScope);
        return;
    }
    const workflowChanged = state.workflowPanelWorkflowId !== Number(workflow.id);
    state.workflowPanelWorkflowId = Number(workflow.id);
    let current;
    try {
        current = await api(`/subcontractors/${state.project.id}/workflows/${workflow.id}`);
    } catch (error) {
        endPerformanceScope(performanceScope);
        throw error;
    }
    if (navigation !== state.navigationVersion || !panel.isConnected || state.workflowPanelWorkflowId !== Number(workflow.id)) { endPerformanceScope(performanceScope); return; }
    if (workflowChanged) {
        state.workflowPanelStep = Number(current.current_step || 1);
        state.workflowPanelDocumentOpen = false;
    }
    const activeStep = Math.max(1, Math.min(7, Number(state.workflowPanelStep || current.current_step || 1)));
    state.workflowPanelStep = activeStep;
    let documents = [];
    let defaults = null;
    let documentError = null;
    try {
        [documents, defaults] = await Promise.all([
            api(`/subcontractors/${state.project.id}/workflows/${workflow.id}/documents`),
            api(`/subcontractors/${state.project.id}/workflows/${workflow.id}/documents/offer-request-defaults`),
        ]);
    } catch (error) {
        documentError = {
            status: Number(error.status || 0),
            message: error.message || "A dokumentumok betöltése nem sikerült.",
        };
    }
    endPerformanceScope(performanceScope);
    const latestDocument = documents.find((item) => item.document_type === "offer_request" && item.status === "draft")
        || documents.find((item) => item.document_type === "offer_request");
    const content = activeStep === 2
        ? state.workflowPanelDocumentOpen
            ? offerRequestPanelContent(current, latestDocument, defaults, documentError)
            : offerRequestLauncherContent(current, latestDocument, documentError)
        : `<div class="workflow-panel-step-content"><h3>${escapeHtml(workflowPanelSteps[activeStep - 1])}</h3>${workflowPanelSummary(current, activeStep)}<p>Ennek a lépésnek a részletes adatai a teljes folyamatűrlapon érhetők el. Az ottani mentési és lépészárási szabályok változatlanul érvényesek.</p><button id="open-full-workflow" class="secondary-button" type="button">Teljes folyamat szerkesztése</button></div>`;
    const currentStep = Math.max(1, Math.min(7, Number(current.current_step || 1)));
    if (navigation !== state.navigationVersion || !panel.isConnected || state.workflowPanelWorkflowId !== Number(workflow.id)) return;
    $(".subcontractor-workspace")?.classList.add("has-selection");
    panel.innerHTML = `<header class="workflow-panel-header"><div><span>${escapeHtml(current.code || "Alvállalkozói folyamat")}</span><h2>${escapeHtml(current.company_name || "Nincs megadva")}</h2><p>${escapeHtml(current.discipline || "Besorolatlan szakág")}</p></div><button id="close-workflow-panel" class="icon-button" type="button" title="Folyamatpanel bezárása">×</button></header><nav class="workflow-side-steps" aria-label="Folyamat lépései">${workflowPanelSteps.map((label, index) => { const step = index + 1; const stateClass = step < currentStep ? "complete" : step === currentStep ? "active" : "locked"; return `<button data-workflow-panel-step="${step}" class="${stateClass} ${step === activeStep ? "selected" : ""}" type="button"><b>${step}</b><span>${escapeHtml(label)}</span></button>`; }).join("")}</nav><div class="workflow-panel-content">${content}</div>`;
    $("#close-workflow-panel", panel)?.addEventListener("click", () => { state.workflowPanelWorkflowId = null; state.workflowPanelDocumentOpen = false; $(".subcontractor-workspace")?.classList.remove("has-selection"); panel.innerHTML = '<div class="workflow-panel-empty"><strong>Válassz egy folyamatot</strong><p>A Megnyitás gombbal megjelenik a folyamat részletezése.</p></div>'; });
    $$('[data-workflow-panel-step]', panel).forEach((button) => button.addEventListener("click", () => { state.workflowPanelStep = Number(button.dataset.workflowPanelStep); state.workflowPanelDocumentOpen = false; openWorkflowPanel(current, catalog); }));
    $("#open-full-workflow", panel)?.addEventListener("click", () => openWorkflow(current, catalog));
    $("#open-offer-request-editor", panel)?.addEventListener("click", () => { state.workflowPanelDocumentOpen = true; openWorkflowPanel(current, catalog); });
    $("#close-offer-request-editor", panel)?.addEventListener("click", () => { state.workflowPanelDocumentOpen = false; openWorkflowPanel(current, catalog); });
    $("#offer-request-document-form", panel)?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submitButton = $("#save-offer-request-top", panel);
        if (submitButton) submitButton.disabled = true;
        const payload = offerRequestFormPayload(event.currentTarget);
        const path = latestDocument
            ? `/subcontractors/${state.project.id}/workflows/${workflow.id}/documents/${latestDocument.id}`
            : `/subcontractors/${state.project.id}/workflows/${workflow.id}/documents/offer-request`;
        try {
            await api(path, { method: latestDocument ? "PUT" : "POST", body: payload });
            toast(latestDocument ? "Az ajánlatkérő piszkozata mentve." : "Az ajánlatkérő piszkozata létrejött.");
            await openWorkflowPanel(current, catalog);
        } catch (error) {
            if (submitButton) submitButton.disabled = false;
            toast(error.message || "A dokumentum mentése nem sikerült.", true);
        }
    });
    $("#save-offer-request-top", panel)?.addEventListener("click", () => $("#offer-request-document-form", panel)?.requestSubmit());
    $("#add-offer-request-contact", panel)?.addEventListener("click", () => {
        const contactId = Number($("#offer-request-contact-select", panel)?.value || 0);
        const contact = (defaults?.company_contacts || []).find((item) => Number(item.id) === contactId);
        const textarea = $("#offer-request-document-form", panel)?.elements.contacts;
        if (!contact || !textarea) return;
        const text = companyContactText(contact);
        const currentContacts = textarea.value.trim();
        if (!currentContacts.split("\n").map((line) => line.trim()).includes(text)) {
            textarea.value = [currentContacts, text].filter(Boolean).join("\n");
        }
    });
    $("#preview-offer-request", panel)?.addEventListener("click", () => {
        if (!latestDocument) return;
        previewSavedDocument(`/subcontractors/${state.project.id}/workflows/${workflow.id}/documents/${latestDocument.id}/preview`);
    });
    $("#export-offer-request", panel)?.addEventListener("click", async () => {
        if (!latestDocument) return;
        const format = $("#offer-request-export-format", panel)?.value === "word" ? "word" : "pdf";
        const extension = format === "word" ? "docx" : "pdf";
        await downloadSavedDocument(
            `/subcontractors/${state.project.id}/workflows/${workflow.id}/documents/${latestDocument.id}/export${toQuery({ format })}`,
            `ajanlatkero-${workflow.id}-v${latestDocument.revision_no || 1}.${extension}`,
        );
    });
    $("#issue-offer-request", panel)?.addEventListener("click", async () => {
        if (!latestDocument || !confirm("Biztosan kiadod ezt az ajánlatkérőt? A kiadott változat már nem módosítható.")) return;
        await api(`/subcontractors/${state.project.id}/workflows/${workflow.id}/documents/${latestDocument.id}/issue`, { method: "POST" });
        toast("Az ajánlatkérő kiadva. A PDF megnyitható a jobb oldali panelen.");
        await renderSubcontractors();
        await openWorkflowPanel(current, catalog);
    });
    $("#new-offer-request-revision", panel)?.addEventListener("click", async () => {
        if (!latestDocument) return;
        await api(`/subcontractors/${state.project.id}/workflows/${workflow.id}/documents/offer-request`, { method: "POST", body: offerRequestPayload(latestDocument) });
        toast("Az új ajánlatkérő-változat piszkozatként létrejött.");
        await openWorkflowPanel(current, catalog);
    });
}

function openWorkflowContextMenu(event, workflow, catalog) {
    $(".workflow-context-menu")?.remove();
    const menu = document.createElement("div");
    menu.className = "workflow-context-menu";
    menu.style.left = `${Math.min(event.clientX, window.innerWidth - 220)}px`;
    menu.style.top = `${Math.min(event.clientY, window.innerHeight - 120)}px`;
    menu.innerHTML = `<button type="button" data-context-open>Folyamat megnyitása</button>${canEdit() ? '<button type="button" data-context-archive class="danger">Folyamat archiválása</button>' : ""}`;
    document.body.append(menu);
    $("[data-context-open]", menu).addEventListener("click", () => { menu.remove(); openWorkflow(workflow, catalog); });
    $("[data-context-archive]", menu)?.addEventListener("click", async () => { menu.remove(); if (!confirm(`Biztosan archiválod ezt a folyamatot: ${workflow.company_name}?`)) return; await api(`/subcontractors/${state.project.id}/workflows/${workflow.id}`, { method: "DELETE" }); toast("A folyamat archiválva."); await renderSubcontractors(); });
    setTimeout(() => document.addEventListener("pointerdown", (pointerEvent) => { if (!menu.contains(pointerEvent.target)) menu.remove(); }, { once: true }), 0);
}

function openSubcontractorFolder(folder, folders, categories = []) {
    if (!canEdit()) return;
    const folderIndex = folders.findIndex((item) => Number(item.id) === Number(folder?.id));
    const currentPosition = folder ? Math.max(1, folderIndex + 1) : folders.length + 1;
    const usedNames = new Set(folders.filter((item) => Number(item.id) !== Number(folder?.id)).map((item) => String(item.name || "")));
    const choices = categories.filter((item) => !usedNames.has(String(item.name || "")));
    if (folder && !choices.some((item) => String(item.name) === String(folder.name))) choices.unshift({ name: folder.name, code: folder.code || "" });
    const categoryFields = categories.length ? `
        <label class="span-2">Szakág a törzsadatbázisból
            <select id="subcontractor-folder-category" required>
                <option value="">Válassz szakágat</option>
                ${choices.map((item) => `<option value="${escapeHtml(item.name)}" data-code="${escapeHtml(item.code || "")}" ${String(item.name) === String(folder?.name || "") ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}
            </select>
            <small class="field-help">A szakágnév és a kód a központi törzsadatból kerül be.</small>
        </label>
        <label>Kód<input id="subcontractor-folder-code" value="${escapeHtml(folder?.code || "")}" readonly></label>` : `
        <label class="span-2">Szakág neve<input name="name" maxlength="255" value="${escapeHtml(folder?.name || "")}" required><small class="field-help">A szakági törzsadatbázis jelenleg üres, ezért átmenetileg kézzel adható meg.</small></label>
        <label>Kód<input name="code" maxlength="80" value="${escapeHtml(folder?.code || "")}"></label>`;
    const noChoice = categories.length > 0 && choices.length === 0;
    showModal(folder ? "Szakági mappa szerkesztése" : "Új szakági mappa", state.project.name, `<form id="subcontractor-folder-form"><div class="form-grid">${categoryFields}<label>Pozíció<input name="display_order" type="number" min="1" max="${Math.max(1, folders.length + (folder ? 0 : 1))}" value="${currentPosition}" required><small class="field-help">Például a 3 érték a lista harmadik helyét jelenti.</small></label></div>${noChoice ? '<p class="form-warning">Minden törzsadatként felvett szakághoz tartozik már mappa.</p>' : ""}<div class="modal-actions">${folder ? '<button id="delete-subcontractor-folder" class="danger-button" type="button">Mappa törlése</button>' : ""}<button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button" ${noChoice ? "disabled" : ""}>Mentés</button></div></form>`);
    const categorySelect = $("#subcontractor-folder-category");
    const updateCode = () => { if ($("#subcontractor-folder-code")) $("#subcontractor-folder-code").value = categorySelect?.selectedOptions[0]?.dataset.code || ""; };
    categorySelect?.addEventListener("change", updateCode);
    updateCode();
    $("#subcontractor-folder-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = formDataObject(event.currentTarget);
        if (categorySelect) {
            const option = categorySelect.selectedOptions[0];
            data.name = categorySelect.value;
            data.code = option?.dataset.code || "";
        }
        data.display_order = Number(data.display_order || currentPosition);
        await api(folder ? `/subcontractors/${state.project.id}/folders/${folder.id}` : `/subcontractors/${state.project.id}/folders`, { method: folder ? "PUT" : "POST", body: data });
        closeModal();
        toast("A szakági mappa mentése sikerült.");
        await renderSubcontractors();
    });
    $("#delete-subcontractor-folder")?.addEventListener("click", async () => { if (!confirm("A szakági mappa csak üres állapotban törölhető. Folytatod?")) return; await api(`/subcontractors/${state.project.id}/folders/${folder.id}`, { method: "DELETE" }); closeModal(); toast("A szakági mappa törölve."); await renderSubcontractors(); });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

function wireSubcontractorFolderDrag() {
    if (!canEdit()) return;
    let dragged = null;
    let initialOrder = "";
    const currentOrder = () => $$(".subcontractor-group[data-folder-id]").map((item) => Number(item.dataset.folderId)).filter(Boolean);
    $$(".subcontractor-group[draggable=true]").forEach((group) => {
        group.addEventListener("dragstart", (event) => { dragged = group; initialOrder = currentOrder().join(","); group.classList.add("dragging"); event.dataTransfer.effectAllowed = "move"; });
        group.addEventListener("dragend", async () => {
            group.classList.remove("dragging");
            dragged = null;
            const folderIds = currentOrder();
            if (folderIds.join(",") === initialOrder) return;
            try {
                await api(`/subcontractors/${state.project.id}/folder-order`, { method: "PUT", body: { folder_ids: folderIds } });
                toast("A szakági sorrend mentve.");
            } catch {
                await renderSubcontractors();
            }
        });
        group.addEventListener("dragover", (event) => { if (!dragged || dragged === group) return; event.preventDefault(); const table = group.parentElement; const bounds = group.getBoundingClientRect(); table.insertBefore(dragged, event.clientY < bounds.top + bounds.height / 2 ? group : group.nextSibling); });
        group.addEventListener("drop", (event) => event.preventDefault());
    });
}

function matrixReferenceLabel(referenceId) {
    return String(referenceId || "").replaceAll("_SZJD", " · szerzői jogdíj").replaceAll("_MD", " · munkadíj").replaceAll("_SZ", " · szakasz ").replaceAll("ALV_", "Alvállalkozó ").replaceAll("FO_", "Főszerződés · ");
}

const matrixMonthNames = ["Január", "Február", "Március", "Április", "Május", "Június", "Július", "Augusztus", "Szeptember", "Október", "November", "December"];

function matrixMonthKey(value, fallbackDate) {
    const match = String(value || fallbackDate || "").match(/^(\d{4})-(\d{2})/);
    if (!match) return String(fallbackDate || new Date().toISOString()).slice(0, 7);
    const month = Math.max(1, Math.min(12, Number(match[2])));
    return `${match[1]}-${String(month).padStart(2, "0")}`;
}

function buildMatrixMonthGroups(columns, fallbackDate) {
    const groupedColumns = new Map();
    columns.forEach((column) => {
        const key = matrixMonthKey(column.stage_date, fallbackDate);
        if (!groupedColumns.has(key)) groupedColumns.set(key, []);
        groupedColumns.get(key).push(column);
    });
    const keys = [...groupedColumns.keys()].sort();
    if (!keys.length) keys.push(matrixMonthKey(fallbackDate, fallbackDate));
    const [startYear, startMonth] = keys[0].split("-").map(Number);
    const [endYear, endMonth] = keys[keys.length - 1].split("-").map(Number);
    const months = [];
    let year = startYear;
    let month = startMonth;
    while (year < endYear || (year === endYear && month <= endMonth)) {
        const key = `${year}-${String(month).padStart(2, "0")}`;
        months.push({ key, label: `${year}. ${matrixMonthNames[month - 1]}`, columns: groupedColumns.get(key) || [] });
        month += 1;
        if (month > 12) {
            month = 1;
            year += 1;
        }
    }
    return months;
}

function renderContractMatrixModern(matrix) {
    const fallbackDate = String(state.project?.created_at || new Date().toISOString()).slice(0, 10);
    const fallbackColumns = () => {
        const milestones = (matrix.milestones || []).map((milestone) => ({ id: null, milestone_id: milestone.id, name: milestone.name, stage_date: milestone.actual_date || milestone.planned_date || fallbackDate, phase_no: Number(milestone.phase_no || 1), fee_percent: Number(milestone.fee_percent || 0), copyright_percent: Number(milestone.copyright_percent || 0), code: `M_${milestone.id}`, source: "milestone", used_fallback_date: !(milestone.actual_date || milestone.planned_date) }));
        const stages = (matrix.stages || []).map((stage) => ({ id: stage.id, name: stage.name, stage_date: stage.stage_date || fallbackDate, code: `STAGE_${stage.id}`, source: "stage", used_fallback_date: !stage.stage_date }));
        const knownCodes = new Set([...milestones, ...stages].map((column) => column.code));
        const legacy = [...new Set((matrix.cells || []).filter((cell) => cell.column_code && cell.column_code !== "BASE" && !knownCodes.has(cell.column_code)).map((cell) => cell.column_code))].map((code) => ({ id: null, name: code.startsWith("EMP_") ? "Hóközi / előleg" : code, stage_date: fallbackDate, code, source: "legacy", used_fallback_date: true }));
        return [...milestones, ...stages, ...legacy];
    };
    const columns = ((matrix.columns || []).length ? matrix.columns : fallbackColumns())
        .map((column) => ({
            ...column,
            stage_date: column.effective_date || column.stage_date || fallbackDate,
            phase_no: column.phase_no === null || column.phase_no === undefined ? null : Number(column.phase_no),
            fee_percent: Number(column.fee_percent || 0),
            copyright_percent: Number(column.copyright_percent || 0),
        }))
        .sort((a, b) => String(a.stage_date).localeCompare(String(b.stage_date)) || String(a.code).localeCompare(String(b.code), "hu"));
    const milestoneColumns = columns.filter((column) => column.source === "milestone");
    const stageColumns = columns.filter((column) => column.source === "stage");
    const paidReferences = matrix.paid_references || {};
    const baseMap = new Map((matrix.base_values || []).map((value) => [value.reference_id, Number(value.amount || 0)]));
    const cellMap = new Map((matrix.cells || []).map((cell) => [`${cell.reference_id}|${cell.stage_id || ""}|${cell.column_code}`, cell]));
    const getCell = (reference, column) => cellMap.get(`${reference}|${column.id || ""}|${column.code}`) || cellMap.get(`${reference}||${column.code}`);
    const workflowIdFromReference = (reference) => Number(String(reference).match(/^ALV_(\d+)_/i)?.[1] || 0);
    const isLocked = (reference, column) => Boolean(paidReferences[`KIA_WF_${workflowIdFromReference(reference)}_COL_${String(column.code).toUpperCase()}`]);
    const activeWorkflows = (matrix.workflows || []).filter((workflow) => Number(workflow.current_step || 1) >= 5 || workflow.acceptance === "Elfogadva");
    const workflowGroups = activeWorkflows.map((workflow) => {
        const rows = [];
        const partCount = Math.max(1, Number(workflow.part_count || 1));
        for (let part = 1; part <= partCount; part += 1) {
            rows.push({ reference: `ALV_${workflow.id}_SZ${part}_MD`, label: `${part}. szakasz · munkadíj`, defaultBase: partCount === 1 ? parseMoneyNumber(workflow.modified_fee || workflow.contract_fee) : 0 });
            rows.push({ reference: `ALV_${workflow.id}_SZ${part}_SZJD`, label: `${part}. szakasz · szerzői jogdíj`, defaultBase: partCount === 1 ? parseMoneyNumber(workflow.modified_copyright_fee || workflow.copyright_fee) : 0 });
        }
        rows.forEach((row) => { if (!baseMap.has(row.reference) && row.defaultBase) baseMap.set(row.reference, row.defaultBase); });
        const contractValue = parseMoneyNumber(workflow.modified_total || workflow.contract_total) || parseMoneyNumber(workflow.modified_fee || workflow.contract_fee) + parseMoneyNumber(workflow.modified_copyright_fee || workflow.copyright_fee);
        const allocatedBase = rows.reduce((sum, row) => sum + Number(baseMap.get(row.reference) || 0), 0);
        return { workflow, rows, contractValue, allocatedBase };
    });
    const foRows = (matrix.contract_sections || []).flatMap((section) => {
        const effectiveFee = Number(section.modified_fee || 0) > 0 ? Number(section.modified_fee) : Number(section.original_fee || 0);
        const sectionNo = Number(section.section_no || 1);
        return [
            { label: `Főszerződés ${sectionNo}. szakasz · munkadíj`, base: effectiveFee * Number(section.fee_percent || 0) / 100, phaseNo: sectionNo, type: "MD" },
            { label: `Főszerződés ${sectionNo}. szakasz · szerzői jogdíj`, base: effectiveFee * Number(section.copyright_percent || 0) / 100, phaseNo: sectionNo, type: "SZJD" },
        ];
    });
    const fixedAmount = (row, column) => {
        if (column.source !== "milestone" || column.phase_no !== row.phaseNo) return 0;
        const percent = row.type === "MD" ? column.fee_percent : column.copyright_percent;
        return row.base * percent / 100;
    };
    const monthGroups = buildMatrixMonthGroups(columns, fallbackDate);
    const gridColumns = monthGroups.flatMap((month) => month.columns.length ? month.columns : [null]);
    const tableColumnCount = gridColumns.length + 2;
    const columnClass = (column) => column.source === "milestone" ? `milestone-column phase-${(Number(column.phase_no || 1) - 1) % 5 + 1}` : column.source === "stage" ? "stage-column" : "legacy-column";
    const columnMeta = (column) => `${formatDate(column.stage_date)}${column.source === "milestone" ? ` · ${column.phase_no}. szakasz` : column.source === "stage" ? " · hóközi / előleg" : ""}${column.used_fallback_date ? " · ellenőrizendő dátum" : ""}`;
    const monthHeader = (month) => `<th colspan="${Math.max(1, month.columns.length)}" style="height:38px">${escapeHtml(month.label)}</th>`;
    const columnHeader = (column) => column
        ? `<th class="${columnClass(column)}" style="top:38px;min-width:calc(138px * var(--matrix-zoom, 1))" data-column-code="${escapeHtml(column.code)}" data-milestone-id="${column.milestone_id || ""}" ${column.source === "stage" ? `data-matrix-stage-id="${column.id}" title="Dupla kattintással szerkeszthető"` : ""}><strong>${escapeHtml(column.name)}</strong><small>${escapeHtml(columnMeta(column))}</small></th>`
        : '<th class="matrix-empty-column" style="top:38px;min-width:calc(138px * var(--matrix-zoom, 1))"><strong>–</strong><small>Nincs mérföldkő</small></th>';
    const emptyGridCell = () => '<td class="matrix-empty-timeline-cell" style="min-width:calc(138px * var(--matrix-zoom, 1))">–</td>';
    const moneyCell = (reference, base, column) => {
        const cell = getCell(reference, column);
        const locked = isLocked(reference, column);
        const hasValue = Boolean(cell && (Number(cell.amount) || Number(cell.percent)));
        return `<td class="matrix-editable ${locked ? "matrix-locked" : ""} ${hasValue ? "has-value" : "matrix-cell-empty"}" style="min-width:calc(138px * var(--matrix-zoom, 1))" data-matrix-cell data-matrix-cell-id="${cell?.id || ""}" data-stage-id="${column.id || ""}" data-milestone-id="${column.milestone_id || ""}" data-reference-id="${escapeHtml(reference)}" data-column-code="${escapeHtml(column.code)}" data-percent="${cell?.percent ?? ""}" data-amount="${cell?.amount || 0}" data-base-amount="${base}" data-text-value="${escapeHtml(cell?.text_value || "")}" data-cell-type="money" data-locked="${locked}" title="${locked ? "Pénzügyileg teljesítve; módosításkor a pénzügyi státusz visszanyílik" : "Dupla kattintással írható be százalék vagy összeg"}">${hasValue ? `<strong>${Number(cell.percent || 0).toLocaleString("hu-HU", { maximumFractionDigits: 4 })}%</strong><small>${formatMoney(cell.amount)}</small>` : `<span class="matrix-entry-prompt">${locked ? "Módosítás" : "＋ Rögzítés"}</span>`}${locked ? '<span class="matrix-lock-mark">Zárolt</span>' : ""}</td>`;
    };
    const textCell = (reference, type, column) => {
        const cell = getCell(reference, column);
        return `<td class="matrix-editable" style="min-width:calc(138px * var(--matrix-zoom, 1))" data-matrix-cell data-matrix-cell-id="${cell?.id || ""}" data-stage-id="${column.id || ""}" data-milestone-id="${column.milestone_id || ""}" data-reference-id="${escapeHtml(reference)}" data-column-code="${escapeHtml(column.code)}" data-percent="" data-amount="0" data-base-amount="0" data-text-value="${escapeHtml(cell?.text_value || "")}" data-cell-type="${type}" data-locked="false" title="Dupla kattintással szerkeszthető">${cell?.text_value ? escapeHtml(type === "date" ? formatDate(cell.text_value) : cell.text_value) : "–"}</td>`;
    };
    const textRow = (workflow, suffix, label, type) => {
        const reference = `ALV_${workflow.id}_${suffix}`;
        return `<tr class="matrix-note-row" data-matrix-note-workflow="${workflow.id}" hidden><td><strong>${label}</strong></td><td>–</td>${gridColumns.map((column) => column ? textCell(reference, type, column) : emptyGridCell()).join("")}</tr>`;
    };
    const mainRows = foRows.map((row) => `<tr class="matrix-main-row"><td><strong>${escapeHtml(row.label)}</strong><small class="matrix-check ok">Mérföldkövekből számítva</small></td><td><strong>${formatMoney(row.base)}</strong></td>${gridColumns.map((column) => { if (!column) return emptyGridCell(); const amount = fixedAmount(row, column); const percent = column.source === "milestone" && column.phase_no === row.phaseNo ? (row.type === "MD" ? column.fee_percent : column.copyright_percent) : 0; return `<td class="matrix-fixed" style="min-width:calc(138px * var(--matrix-zoom, 1))" data-column-code="${escapeHtml(column.code)}" data-milestone-id="${column.milestone_id || ""}">${amount ? `<strong>${percent.toLocaleString("hu-HU")}%</strong><small>${formatMoney(amount)}</small>` : "–"}</td>`; }).join("")}</tr>`).join("");
    const subcontractorRows = workflowGroups.map(({ workflow, rows, contractValue, allocatedBase }) => {
        const baseDifference = contractValue - allocatedBase;
        const groupLocked = Object.keys(paidReferences).some((reference) => reference.startsWith(`KIA_WF_${workflow.id}_COL_`));
        const heading = `<tr class="matrix-workflow-row ${baseDifference > .99 ? "allocation-missing" : baseDifference < -.99 ? "allocation-over" : "allocation-complete"}"><td colspan="${tableColumnCount}"><div><button type="button" data-toggle-matrix-notes="${workflow.id}" class="matrix-note-toggle" title="Megjegyzés- és teljesítési dátumsorok megjelenítése">▸</button><strong>${escapeHtml(workflow.company_name)}</strong><span>${escapeHtml(workflow.discipline || workflow.code || "")}</span><small class="matrix-check ${Math.abs(baseDifference) < 1 ? "ok" : "warning"}">${Math.abs(baseDifference) < 1 ? `A teljes szerződés szakaszokra kiosztva: ${formatMoney(contractValue)}` : baseDifference > 0 ? `Még szakaszhoz rendelendő: ${formatMoney(baseDifference)}` : `Szakaszokra túlosztva: ${formatMoney(Math.abs(baseDifference))}`}</small>${groupLocked ? '<b class="paid-indicator">Van teljesített pénzügyi tétel</b>' : ""}</div></td></tr>`;
        const detailRows = rows.map((row) => {
            const base = Number(baseMap.get(row.reference) || 0);
            const scheduled = columns.reduce((sum, column) => sum + Number(getCell(row.reference, column)?.amount || 0), 0);
            const difference = base - scheduled;
            const baseLocked = columns.some((column) => isLocked(row.reference, column));
            const allocationClass = !base ? "allocation-no-base" : difference > .99 ? "allocation-missing" : difference < -.99 ? "allocation-over" : "allocation-complete";
            const allocationText = !base ? "Előbb add meg a bázisösszeget" : Math.abs(difference) < 1 ? "Teljes összeg kiosztva" : difference > 0 ? `Még kiosztandó: ${formatMoney(difference)}` : `Túlosztás: ${formatMoney(Math.abs(difference))}`;
            return `<tr class="matrix-sub-row ${allocationClass}"><td><strong>${escapeHtml(row.label)}</strong><small class="matrix-check ${Math.abs(difference) < 1 && base ? "ok" : "warning"}">${allocationText}</small></td><td class="matrix-base-cell ${base ? "has-value" : "missing"}" data-matrix-base="${row.reference}" data-amount="${base}" data-locked="${baseLocked}" title="Dupla kattintással szerkeszthető">${base ? `<strong>${formatMoney(base)}</strong>` : '<span>＋ Bázis megadása</span>'}</td>${gridColumns.map((column) => column ? moneyCell(row.reference, base, column) : emptyGridCell()).join("")}</tr>`;
        }).join("");
        return `${heading}${detailRows}${textRow(workflow, "KOMM", "Megjegyzések", "comment")}${textRow(workflow, "KIFDATUM", "Teljesítés / utalás dátuma", "date")}`;
    }).join("");
    const revenueByColumn = gridColumns.map((column) => column ? foRows.reduce((sum, row) => sum + fixedAmount(row, column), 0) : 0);
    const costByColumn = gridColumns.map((column) => column ? workflowGroups.reduce((total, group) => total + group.rows.reduce((sum, row) => sum + Number(getCell(row.reference, column)?.amount || 0), 0), 0) : 0);
    const summaryRows = `<tr class="matrix-summary-row revenue"><td><strong>Főszerződés bevételi mérföldkövei</strong></td><td>${formatMoney(foRows.reduce((sum, row) => sum + row.base, 0))}</td>${revenueByColumn.map((amount) => `<td>${amount ? formatMoney(amount) : "–"}</td>`).join("")}</tr><tr class="matrix-summary-row cost"><td><strong>Alvállalkozói havi kifizetések</strong></td><td>${formatMoney(workflowGroups.reduce((sum, group) => sum + group.allocatedBase, 0))}</td>${costByColumn.map((amount) => `<td>${amount ? formatMoney(amount) : "–"}</td>`).join("")}</tr><tr class="matrix-summary-row balance"><td><strong>Időszaki különbözet</strong></td><td>–</td>${revenueByColumn.map((amount, index) => { const balance = amount - costByColumn[index]; return `<td class="${balance < 0 ? "negative" : "positive"}">${formatMoney(balance)}</td>`; }).join("")}</tr>`;
    const zoom = Number(state.matrixZoom || 1);
    const warningNote = (matrix.matrix_warnings || []).length ? `<div class="dependency-note danger"><strong>Dátum-adatminőségi figyelmeztetés</strong><span>${escapeHtml(matrix.matrix_warnings.join(" "))}</span></div>` : "";
    return `<div class="toolbar"><div><strong>Kifizetési mérföldkőmátrix</strong><p class="muted">A felső fejléc hónapok szerint csoportosít, alatta minden mérföldkő önálló táblázatoszlopban jelenik meg. Az üres hónapokat egy helyőrző oszlop tartja folytonosan az idővonalon. Ctrl + görgő: táblázati nagyítás.</p></div><div class="toolbar-group"><span>${monthGroups.length} hónap · ${milestoneColumns.length} mérföldkő · ${stageColumns.length} hóközi / előleg tétel · ${matrix.cells.length} mentett kiosztás</span>${canEdit() ? '<button id="new-matrix-stage" class="secondary-button" type="button">Új hóközi / előleg tétel</button>' : ""}</div></div><div class="matrix-entry-guide"><span class="editable">＋ Rögzítés: dupla kattintással összeg vagy százalék írható</span><span class="missing">Még kiosztandó összeg</span><span class="complete">Teljesen kiosztva</span><span class="locked">Zárolt: pénzügyileg teljesítve</span></div>${warningNote}<div class="dependency-note"><strong>Védett pénzügyi kapcsolat:</strong> minden szerkeszthető cella megtartja a főszerződéses mérföldkő pontos azonosítóját. A zöld, zárolt tételek módosítása megerősítést kér, és a kapcsolódó pénzügyi tételt várható állapotba állítja vissza.</div>
        <section class="panel matrix-workspace"><div class="panel-header"><h2>Főszerződés és alvállalkozói kifizetések</h2><span>Mérföldkövek → mátrix → pénzügy</span></div><div class="table-wrap matrix-table-wrap" style="--matrix-zoom:${zoom}"><table class="contract-matrix-table"><thead><tr class="matrix-month-row"><th rowspan="2">Szerződés / díjtípus</th><th rowspan="2">Bázis</th>${monthGroups.map(monthHeader).join("")}</tr><tr class="matrix-column-row">${gridColumns.map(columnHeader).join("")}</tr></thead><tbody><tr class="matrix-group-row"><td colspan="${tableColumnCount}">FŐSZERZŐDÉS · AUTOMATIKUS BEVÉTELI MÉRFÖLDKÖVEK</td></tr>${foRows.length ? mainRows : `<tr><td colspan="${tableColumnCount}">Előbb rögzíts főszerződéses szakaszt és mérföldkövet az Ütemterv modulban.</td></tr>`}<tr class="matrix-group-row subcontractor"><td colspan="${tableColumnCount}">ALVÁLLALKOZÓI SZERZŐDÉSEK · SZERKESZTHETŐ KIFIZETÉSEK</td></tr>${workflowGroups.length ? subcontractorRows : `<tr><td colspan="${tableColumnCount}">Nincs mátrixba aktivált alvállalkozói szerződés.</td></tr>`}<tr class="matrix-group-row summary"><td colspan="${tableColumnCount}">IDŐSZAKI PÉNZÜGYI ELLENŐRZÉS</td></tr>${summaryRows}</tbody></table></div></section>`;
}

function renderContractMatrix(matrix) {
    const milestoneColumns = (matrix.milestones || []).map((milestone) => ({ id: null, milestone_id: milestone.id, name: milestone.name, stage_date: milestone.actual_date || milestone.planned_date, phase_no: Number(milestone.phase_no || 1), fee_percent: Number(milestone.fee_percent || 0), copyright_percent: Number(milestone.copyright_percent || 0), code: `M_${milestone.id}`, source: "milestone" }));
    const stageColumns = (matrix.stages || []).map((stage) => ({ id: stage.id, name: stage.name, stage_date: stage.stage_date, code: `STAGE_${stage.id}`, source: "stage" }));
    const knownCodes = new Set([...milestoneColumns, ...stageColumns].map((column) => column.code));
    const legacyColumns = [...new Set(matrix.cells.filter((cell) => cell.column_code && cell.column_code !== "BASE" && !knownCodes.has(cell.column_code)).map((cell) => cell.column_code))].map((code) => ({ id: null, name: code.startsWith("EMP_") ? "Hóközi / előleg" : code, stage_date: null, code, source: "legacy" }));
    const columns = [...milestoneColumns, ...stageColumns, ...legacyColumns].sort((a, b) => String(a.stage_date || "9999").localeCompare(String(b.stage_date || "9999")) || String(a.code).localeCompare(String(b.code)));
    const existingReferences = new Set([...matrix.base_values.map((item) => item.reference_id), ...matrix.cells.map((item) => item.reference_id)]);
    const workflowRows = [];
    for (const workflow of matrix.workflows || []) {
        if (Number(workflow.current_step || 1) < 5 && workflow.acceptance !== "Elfogadva") continue;
        const partCount = Math.max(1, Number(workflow.part_count || 1));
        for (let part = 1; part <= partCount; part += 1) {
            workflowRows.push({ reference: `ALV_${workflow.id}_SZ${part}_MD`, label: `${workflow.company_name} · ${part}. szakasz · munkadíj`, defaultBase: partCount === 1 ? Number(String(workflow.modified_fee || workflow.contract_fee || 0).replaceAll(" ", "")) || 0 : 0 });
            workflowRows.push({ reference: `ALV_${workflow.id}_SZ${part}_SZJD`, label: `${workflow.company_name} · ${part}. szakasz · szerzői jogdíj`, defaultBase: partCount === 1 ? Number(String(workflow.modified_copyright_fee || workflow.copyright_fee || 0).replaceAll(" ", "")) || 0 : 0 });
        }
    }
    workflowRows.forEach((row) => existingReferences.add(row.reference));
    const baseMap = new Map(matrix.base_values.map((value) => [value.reference_id, Number(value.amount || 0)]));
    workflowRows.forEach((row) => { if (!baseMap.has(row.reference) && row.defaultBase) baseMap.set(row.reference, row.defaultBase); });
    const cellMap = new Map(matrix.cells.map((cell) => [`${cell.reference_id}|${cell.stage_id || ""}|${cell.column_code}`, cell]));
    const foRows = (matrix.contract_sections || []).flatMap((section) => {
        const effectiveFee = Number(section.modified_fee || 0) > 0 ? Number(section.modified_fee) : Number(section.original_fee || 0);
        const sectionNo = Number(section.section_no || 1);
        return [
            { reference: `FO_SZ${sectionNo}_MD`, label: `Főszerződés ${sectionNo}. szakasz · munkadíj`, base: effectiveFee * Number(section.fee_percent || 0) / 100, phaseNo: sectionNo, type: "MD" },
            { reference: `FO_SZ${sectionNo}_SZJD`, label: `Főszerződés ${sectionNo}. szakasz · szerzői jogdíj`, base: effectiveFee * Number(section.copyright_percent || 0) / 100, phaseNo: sectionNo, type: "SZJD" },
        ];
    });
    const alvReferences = [...existingReferences].filter((reference) => !String(reference).startsWith("FO_")).sort((a, b) => {
        const ai = workflowRows.findIndex((row) => row.reference === a); const bi = workflowRows.findIndex((row) => row.reference === b);
        return (ai < 0 ? 99999 : ai) - (bi < 0 ? 99999 : bi) || String(a).localeCompare(String(b), "hu");
    });
    const labelMap = new Map(workflowRows.map((row) => [row.reference, row.label]));
    const renderRows = (references, type) => references.map((reference) => {
        const base = Number(baseMap.get(reference) || 0);
        const scheduled = columns.reduce((sum, column) => { const cell = cellMap.get(`${reference}|${column.id || ""}|${column.code}`) || cellMap.get(`${reference}||${column.code}`); return sum + Number(cell?.amount || 0); }, 0);
        const difference = base - scheduled;
        return `<tr class="matrix-${type}-row"><td><strong>${escapeHtml(labelMap.get(reference) || matrixReferenceLabel(reference))}</strong><small class="matrix-check ${Math.abs(difference) < 1 ? "ok" : "warning"}">${base || scheduled ? (Math.abs(difference) < 1 ? "Kiosztva" : `Eltérés: ${formatMoney(difference)}`) : "Nincs keret"}</small></td><td data-matrix-base="${escapeHtml(reference)}" data-amount="${base}" title="Dupla kattintással szerkeszthető"><strong>${formatMoney(base)}</strong></td>${columns.map((column) => { const cell = cellMap.get(`${reference}|${column.id || ""}|${column.code}`) || cellMap.get(`${reference}||${column.code}`); return `<td class="matrix-editable" data-matrix-cell data-matrix-cell-id="${cell?.id || ""}" data-stage-id="${column.id || ""}" data-reference-id="${escapeHtml(reference)}" data-column-code="${escapeHtml(column.code)}" data-percent="${cell?.percent ?? ""}" data-amount="${cell?.amount || 0}" data-base-amount="${base}" data-text-value="${escapeHtml(cell?.text_value || "")}" title="Dupla kattintással szerkeszthető">${cell && (Number(cell.amount) || Number(cell.percent)) ? `<strong>${Number(cell.percent || 0).toLocaleString("hu-HU")}%</strong><small>${formatMoney(cell.amount)}</small>` : "–"}</td>`; }).join("")}</tr>`;
    }).join("");
    const renderMainRows = () => foRows.map((row) => {
        const allocations = columns.map((column) => {
            const percent = column.source === "milestone" && column.phase_no === row.phaseNo ? (row.type === "MD" ? column.fee_percent : column.copyright_percent) : 0;
            const amount = row.base * percent / 100;
            return `<td class="matrix-fixed" title="Az ütemtervi mérföldkőből számítva">${amount ? `<strong>${percent.toLocaleString("hu-HU")}%</strong><small>${formatMoney(amount)}</small>` : "–"}</td>`;
        }).join("");
        return `<tr class="matrix-main-row"><td><strong>${escapeHtml(row.label)}</strong><small class="matrix-check ok">Mérföldkövekből számítva</small></td><td><strong>${formatMoney(row.base)}</strong></td>${allocations}</tr>`;
    }).join("");
    return `<div class="toolbar"><div><strong>Kifizetési ütemterv</strong><p class="muted">Az alapütemet az Ütemterv szerződéses mérföldkövei adják; külön hóközi vagy előleg oszlop is felvehető. Az alvállalkozói összegek innen kerülnek a Pénzügy várható kiadásai közé.</p></div><div class="toolbar-group"><span>${milestoneColumns.length} mérföldkő · ${stageColumns.length} külön oszlop · ${matrix.cells.length} mentett kiosztás</span>${canEdit() ? '<button id="new-matrix-stage" class="secondary-button" type="button">Új hóközi / előleg oszlop</button>' : ""}</div></div>
        <section class="panel matrix-workspace"><div class="panel-header"><h2>Főszerződés és alvállalkozói kifizetések</h2><span>Ütemterv → mátrix → pénzügy</span></div><div class="table-wrap matrix-table-wrap"><table class="contract-matrix-table"><thead><tr><th>Szerződés / díjtípus</th><th>Bázis</th>${columns.map((column) => `<th ${column.source === "stage" ? `data-matrix-stage-id="${column.id}" title="Dupla kattintással szerkeszthető"` : ""} class="${column.source === "milestone" ? `milestone-column phase-${(column.phase_no - 1) % 5 + 1}` : column.source === "stage" ? "stage-column" : "legacy-column"}"><strong>${escapeHtml(column.name)}</strong><small>${formatDate(column.stage_date)}${column.source === "milestone" ? ` · ${column.phase_no}. szakasz` : column.source === "stage" ? " · külön ütem" : ""}</small></th>`).join("")}</tr></thead><tbody><tr class="matrix-group-row"><td colspan="${columns.length + 2}">FŐSZERZŐDÉS · AUTOMATIKUS BEVÉTELI ÜTEM</td></tr>${foRows.length ? renderMainRows() : `<tr><td colspan="${columns.length + 2}">Előbb rögzíts főszerződéses szakaszt az Ütemterv mérföldkőnézetében.</td></tr>`}<tr class="matrix-group-row subcontractor"><td colspan="${columns.length + 2}">ALVÁLLALKOZÓI SZERZŐDÉSEK · SZERKESZTHETŐ KIADÁSI ÜTEM</td></tr>${alvReferences.length ? renderRows(alvReferences, "sub") : `<tr><td colspan="${columns.length + 2}">Nincs mátrixba aktivált alvállalkozói szerződés.</td></tr>`}</tbody></table></div></section>`;
}

function openMatrixCell(cell) {
    if (!cell || !canEdit()) return;
    const isText = cell.cell_type === "comment" || cell.cell_type === "date";
    const editor = isText
        ? `<label class="span-3">${cell.cell_type === "date" ? "Teljesítés / utalás dátuma" : "Megjegyzés"}${cell.cell_type === "date" ? `<input name="text_value" type="date" value="${escapeHtml(cell.text_value || "")}">` : `<textarea name="text_value" rows="5">${escapeHtml(cell.text_value || "")}</textarea>`}</label>`
        : `<label>Százalék<input name="percent" type="number" step="0.0001" value="${escapeHtml(cell.percent ?? "")}"></label><label>Összeg (Ft)<input name="amount" type="number" min="0" step="0.01" value="${escapeHtml(cell.amount || 0)}" required></label><label class="span-3">Cellamegjegyzés<input name="text_value" value="${escapeHtml(cell.text_value || "")}"></label>`;
    showModal(isText ? cell.cell_type === "date" ? "Teljesítési dátum" : "Mátrixmegjegyzés" : "Mátrixcella szerkesztése", matrixReferenceLabel(cell.reference_id), `<form id="matrix-cell-form">${cell.locked ? '<div class="dependency-note danger"><strong>Pénzügyileg teljesített cella.</strong> Az összeg módosítása visszanyitja a kapcsolódó pénzügyi tételt.</div>' : ""}<div class="form-grid"><label>Mérföldkő / tétel<input value="${escapeHtml(cell.column_code || "BASE")}" disabled></label>${editor}</div><div class="modal-actions"><button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Mentés</button></div></form>`);
    const matrixForm = $("#matrix-cell-form");
    let syncingMatrixValue = false;
    let calculationSource = "amount";
    matrixForm.elements.percent?.addEventListener("input", () => { calculationSource = "percent"; if (syncingMatrixValue || !cell.base_amount) return; syncingMatrixValue = true; matrixForm.elements.amount.value = (cell.base_amount * Number(matrixForm.elements.percent.value || 0) / 100).toFixed(2); syncingMatrixValue = false; });
    matrixForm.elements.amount?.addEventListener("input", () => { calculationSource = "amount"; if (syncingMatrixValue || !cell.base_amount) return; syncingMatrixValue = true; matrixForm.elements.percent.value = (Number(matrixForm.elements.amount.value || 0) / cell.base_amount * 100).toFixed(4); syncingMatrixValue = false; });
    $("#matrix-cell-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = formDataObject(event.currentTarget);
        const amountChanged = Math.abs(Number(data.amount || 0) - Number(cell.amount || 0)) >= .01;
        let reopen = false;
        if (cell.locked && amountChanged) {
            reopen = confirm("Ehhez a cellához pénzügyileg teljesített tétel tartozik. A mentés a pénzügyi tételt Várható állapotba nyitja vissza. Folytatod?");
            if (!reopen) return;
        }
        Object.assign(data, { project_id: state.project.id, stage_id: cell.stage_id, reference_id: cell.reference_id, column_code: cell.column_code, percent: isText || valueOrNull(data.percent) === null ? null : Number(data.percent), amount: isText ? 0 : Number(data.amount || 0), calculation_source: isText ? "text" : calculationSource, reopen_completed_payment: reopen });
        const result = cell.id ? await api(`/subcontractors/${state.project.id}/matrix/${cell.id}`, { method: "PUT", body: data }) : await api(`/subcontractors/${state.project.id}/matrix`, { method: "PUT", body: [data] });
        closeModal();
        if (result.reopened_payments?.length) toast("A cella mentve, a kapcsolódó pénzügyi tétel Várható állapotba került."); else toast("A mátrixcella mentése sikerült.");
        await renderSubcontractors();
    });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

function openMatrixBaseValue(referenceId, amount, locked = false) {
    if (!canEdit()) return;
    showModal("Mátrixbázis szerkesztése", matrixReferenceLabel(referenceId), `<form id="matrix-base-form">${locked ? '<div class="dependency-note danger"><strong>A bázishoz teljesített pénzügyi cella tartozik.</strong> A módosítás az érintett százalékos cellákat újraszámolja.</div>' : ""}<div class="form-grid"><label class="span-2">Szerződéses bázisösszeg (Ft)<input name="amount" type="number" min="0" step="0.01" value="${amount}" required></label></div><div class="modal-actions"><button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Mentés</button></div></form>`);
    $("#matrix-base-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = formDataObject(event.currentTarget); const changed = Math.abs(Number(data.amount || 0) - Number(amount || 0)) >= .01; const reopen = locked && changed ? confirm("A bázis módosítása teljesített pénzügyi tételeket nyithat vissza Várható állapotba. Folytatod?") : false; if (locked && changed && !reopen) return; const result = await api(`/subcontractors/${state.project.id}/matrix/base-values`, { method: "PUT", body: [{ reference_id: referenceId, amount: Number(data.amount || 0), reopen_completed_payments: reopen }] }); closeModal(); toast(result.reopened_payments?.length ? "A bázis mentve, az érintett pénzügyi tételek visszanyíltak." : "A szerződéses bázis mentése sikerült."); await renderSubcontractors(); });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

function openMatrixStage(stage, stages) {
    if (!canEdit()) return;
    const current = stage || { name: "", stage_date: "", sort_order: Math.max(0, ...stages.map((item) => Number(item.sort_order || 0))) + 10 };
    showModal(stage ? "Hóközi / előleg tétel szerkesztése" : "Új hóközi / előleg tétel", state.project.name, `<form id="matrix-stage-form"><div class="form-grid"><label class="span-2">Tétel neve<input name="name" value="${escapeHtml(current.name)}" placeholder="Például: 1. előleg" required></label><label>Várható dátum<input name="stage_date" type="date" value="${escapeHtml(current.stage_date || "")}" required></label><label>Sorrend<input name="sort_order" type="number" min="0" value="${current.sort_order}" required></label></div><div class="modal-actions">${stage ? '<button id="delete-matrix-stage" class="danger-button" type="button">Tétel törlése</button>' : ""}<button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Mentés</button></div></form>`);
    $("#matrix-stage-form").addEventListener("submit", async (event) => { event.preventDefault(); const data = formDataObject(event.currentTarget); Object.assign(data, { stage_date: valueOrNull(data.stage_date), sort_order: Number(data.sort_order) }); await api(stage ? `/subcontractors/${state.project.id}/matrix/stages/${stage.id}` : `/subcontractors/${state.project.id}/matrix/stages`, { method: stage ? "PUT" : "POST", body: data }); closeModal(); toast("A hóközi / előleg tétel mentése sikerült."); await renderSubcontractors(); });
    $("#delete-matrix-stage")?.addEventListener("click", async () => { if (!confirm("A tételhez tartozó mátrixcellák is törlődnek. Folytatod?")) return; await api(`/subcontractors/${state.project.id}/matrix/stages/${stage.id}`, { method: "DELETE" }); closeModal(); toast("A hóközi / előleg tétel törölve."); await renderSubcontractors(); });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

async function openWorkflow(workflow, catalog = state.subcontractorCatalog || { folders: [], subcontractors: [], categories: [] }) {
    const current = workflow?.id ? await api(`/subcontractors/${state.project.id}/workflows/${workflow.id}`) : {
        display_order: 10, company_name: "", discipline: "", code: "", finance_class: "Alvállalkozó", status_note: "",
        preliminary_estimate: "", offer_status: "Kiküldésre vár", offer_date: "", offer_link: "", received_date: "", received_link: "",
        offer_price: "", acceptance: "Tárgyalás alatt", feedback: "", contract_total: "", contract_fee: "", copyright_fee: "",
        guarantee: "", notification: "Még nem történt meg", draft: "", signature_status: "Nincs elindítva", signature_date: "",
        closing_note: "", currency: "HUF", vat_type: "Nettó", no_offer: false, current_step: 1, part_count: 1,
        modified_fee: "", modified_copyright_fee: "", modified_total: "", modification_date: "", modification_note: "",
        offer_parts: [], contract_parts: [], contract_changes: [],
    };
    let offerParts = [...(current.offer_parts || [])];
    const currentStep = Math.max(1, Math.min(7, Number(current.current_step || 1)));
    const selectOptions = (values, selected) => values.map((value) => `<option ${value === selected ? "selected" : ""}>${escapeHtml(value)}</option>`).join("");
    const disciplineChoices = [
        ...(catalog.folders || []).map((folder) => ({ name: folder.name, code: folder.code || "" })),
        ...(catalog.categories || []).map((category) => ({ name: category.name, code: category.code || "" })),
    ].filter((item, index, items) => item.name && items.findIndex((candidate) => candidate.name === item.name) === index);
    if (current.discipline && !disciplineChoices.some((item) => item.name === current.discipline)) {
        disciplineChoices.unshift({ name: current.discipline, code: "" });
    }
    const disciplineOptions = disciplineChoices.map((item) => `<option value="${escapeHtml(item.name)}" ${item.name === current.discipline ? "selected" : ""}>${escapeHtml(item.code ? `${item.code} – ${item.name}` : item.name)}</option>`).join("");
    const companyOptions = [...new Set([current.company_name, ...(catalog.subcontractors || []).map((item) => item.name)].filter(Boolean))].map((name) => `<option value="${escapeHtml(name)}"></option>`).join("");
    const stepAction = (step) => step < currentStep
        ? `<button class="step-action secondary-button" data-reopen-workflow-step="${step}" type="button">Lépés újranyitása</button>`
        : step === currentStep && step < 7
            ? `<button class="step-action primary-button" data-close-workflow-step="${step}" type="button">${step === 6 ? "Folyamat befejezése" : "Lépés lezárása és tovább"}</button>`
            : step > currentStep ? '<span class="workflow-step-lock">Előző lépés lezárása szükséges</span>' : "";
    const stepClass = (step) => step < currentStep ? "complete" : step === currentStep ? "active" : "locked";
    const changes = current.contract_changes || [];
    showModal(workflow ? "Alvállalkozói folyamat" : "Új alvállalkozói folyamat", `${state.project.name} · ${current.code || "új ajánlatkérés"}`, `<form id="workflow-form" class="workflow-form">
        <div class="workflow-progress">${[1,2,3,4,5,6,7].map((step) => `<span class="${stepClass(step)}"><b>${step}</b>${["Alapadat", "Ajánlatkérés", "Ajánlat", "Döntés", "Szerződés", "Aláírás", "Módosítások"][step - 1]}</span>`).join("")}</div>
        <div class="workflow-settings"><label>Pénznem<select name="currency">${selectOptions(["HUF", "EUR", "USD"], current.currency || "HUF")}</select></label><label>Áfa-kezelés<select name="vat_type">${selectOptions(["Nettó", "AAM", "Bruttó"], current.vat_type || "Nettó")}</select></label></div>
        <fieldset data-workflow-step="1" class="workflow-step ${stepClass(1)}"><legend><span>1</span> Alapadatok</legend><div class="form-grid"><label>Szakág / szerep<select name="discipline" required><option value="">Válassz szakágat</option>${disciplineOptions}</select><small class="field-help">A szakág kódja és neve a projekt szakági listájából választható.</small></label><label class="span-2">Cég neve<input name="company_name" list="workflow-companies" value="${escapeHtml(current.company_name)}" required><datalist id="workflow-companies">${companyOptions}</datalist></label><label>Kód<input name="code" value="${escapeHtml(current.code)}"></label><label>Partner szerepe<input name="finance_class" value="${escapeHtml(current.finance_class)}"><small class="field-help">A pénzügyi csoportosításhoz használt szerep vagy osztály.</small></label><label>Előzetes kalkuláció<input name="preliminary_estimate" inputmode="decimal" value="${escapeHtml(current.preliminary_estimate)}"></label><label class="span-3">Belső megjegyzés<textarea name="status_note" rows="2">${escapeHtml(current.status_note)}</textarea></label></div><div class="workflow-step-actions">${currentStep === 1 && canEdit() ? '<button id="new-subcontractor-master" class="secondary-button" type="button">Új cég felvétele a törzsbe</button>' : ""}${stepAction(1)}</div></fieldset>
        <fieldset data-workflow-step="2" class="workflow-step ${stepClass(2)}"><legend><span>2</span> Ajánlatkérés</legend><div class="form-grid"><label>Státusz<select name="offer_status">${selectOptions(["Kiküldésre vár", "Kiküldve", "Elutasítva"], current.offer_status || "Kiküldésre vár")}</select></label><label>Kiküldés dátuma<input name="offer_date" type="date" value="${escapeHtml(current.offer_date)}"></label><label>Ajánlatkérés mappája / linkje<input name="offer_link" value="${escapeHtml(current.offer_link)}"></label></div><div class="workflow-step-actions"><button id="open-offer-request-from-modal" class="secondary-button step-action" type="button">Ajánlatkérő összeállítása</button>${stepAction(2)}</div></fieldset>
        <fieldset data-workflow-step="3" class="workflow-step ${stepClass(3)}"><legend><span>3</span> Ajánlat beérkezése</legend><div class="form-grid"><label>Beérkezés dátuma<input name="received_date" type="date" value="${escapeHtml(current.received_date)}"></label><label>Beérkezett ajánlat linkje<input name="received_link" value="${escapeHtml(current.received_link)}"></label><label>Ajánlati ár összesen<input name="offer_price" inputmode="decimal" value="${escapeHtml(current.offer_price)}"></label><label class="checkbox-label span-2"><input name="no_offer" type="checkbox" ${current.no_offer ? "checked" : ""}> A cég nem ad ajánlatot</label></div><div class="workflow-parts"><div class="panel-header"><h3>Részletes ajánlati bontás</h3><strong id="offer-parts-total"></strong></div><div class="table-wrap"><table><thead><tr><th>Fázis megnevezése</th><th>Összeg</th><th>Opcionális</th><th></th></tr></thead><tbody id="offer-parts-body"></tbody></table></div><div class="inline-add"><input id="offer-part-name" placeholder="Fázis neve"><input id="offer-part-amount" inputmode="decimal" placeholder="Összeg"><label class="checkbox-label"><input id="offer-part-optional" type="checkbox"> Opcionális</label><button id="add-offer-part" class="secondary-button" type="button">Részlet hozzáadása</button></div></div><div class="workflow-step-actions">${stepAction(3)}</div></fieldset>
        <fieldset data-workflow-step="4" class="workflow-step ${stepClass(4)}"><legend><span>4</span> Döntés és elfogadás</legend><div class="form-grid"><label>Elfogadás állapota<select name="acceptance">${selectOptions(["Tárgyalás alatt", "Elfogadva", "Elutasítva"], current.acceptance || "Tárgyalás alatt")}</select></label><label class="span-2">Írásbeli megrendelés / döntés linkje<input name="feedback" value="${escapeHtml(current.feedback)}"></label></div><div class="workflow-step-actions">${stepAction(4)}</div></fieldset>
        <fieldset data-workflow-step="5" class="workflow-step ${stepClass(5)}"><legend><span>5</span> Szerződés és mátrixaktiválás</legend><div class="form-grid"><label>Munkadíj<input name="contract_fee" inputmode="decimal" value="${escapeHtml(current.contract_fee)}"></label><label>Szerzői jogdíj<input name="copyright_fee" inputmode="decimal" value="${escapeHtml(current.copyright_fee)}"></label><label>Szerződés összesen<input name="contract_total" inputmode="decimal" value="${escapeHtml(current.contract_total)}" readonly></label><label>Biztosíték<select name="guarantee">${selectOptions(["", "KELL", "NEM KELL"], current.guarantee || "")}</select></label><label>Bejelentés<select name="notification">${selectOptions(["Még nem történt meg", "Megtörtént"], current.notification || "Még nem történt meg")}</select></label><label>Kifizetési szakaszok száma<input name="part_count" type="number" min="1" max="100" value="${current.part_count || 1}"><small class="field-help">Ennyi külön munkadíj- és szerzői jogdíjsor készül az alvállalkozóhoz a kifizetési mátrixban.</small></label><input name="draft" type="hidden" value="${escapeHtml(current.draft)}"></div><div class="workflow-step-actions">${stepAction(5)}</div></fieldset>
        <fieldset data-workflow-step="6" class="workflow-step ${stepClass(6)}"><legend><span>6</span> Aláírás</legend><div class="form-grid"><label>Aláírás állapota<select name="signature_status">${selectOptions(["Nincs elindítva", "Applikációban elindítva", "Aláírási folyamat elindítva", "Aláírva"], current.signature_status || "Nincs elindítva")}</select></label><label>Aláírás dátuma<input name="signature_date" type="date" value="${escapeHtml(current.signature_date)}"></label><label class="span-3">Záró megjegyzés<textarea name="closing_note" rows="2">${escapeHtml(current.closing_note)}</textarea></label></div><div class="workflow-step-actions">${stepAction(6)}</div></fieldset>
        <fieldset data-workflow-step="7" class="workflow-step modifications ${stepClass(7)}"><legend><span>7</span> Szerződésmódosítások naplója</legend><div class="panel-header"><h3>Módosítási előzmények</h3>${workflow && currentStep >= 7 ? '<button id="new-contract-change" class="secondary-button step-action" type="button">Új módosítás</button>' : ""}</div><div class="table-wrap"><table><thead><tr><th>Dátum</th><th>Új munkadíj</th><th>Új SZJD</th><th>Összesen</th><th>Indoklás</th><th></th></tr></thead><tbody>${changes.length ? changes.map((change) => `<tr><td>${formatDate(change.change_date)}</td><td>${escapeHtml(change.modified_fee || "–")}</td><td>${escapeHtml(change.modified_copyright_fee || "–")}</td><td>${escapeHtml(change.modified_total || "–")}</td><td>${escapeHtml(change.reason || "")}</td><td>${canEdit() ? `<button class="icon-danger step-action" data-delete-contract-change="${change.id}" type="button" title="Módosítás törlése">×</button>` : ""}</td></tr>`).join("") : '<tr><td colspan="6">Nincs szerződésmódosítás.</td></tr>'}</tbody></table></div></fieldset>
        <input name="current_step" type="hidden" value="${currentStep}"><div class="modal-actions">${workflow ? '<button id="archive-workflow" type="button" class="danger-button">Archiválás</button>' : ""}<button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Állapot mentése</button></div></form>`);

    let scheduleKeyAssignments = [...(current.schedule_key_assignments || [])].map((item) => ({
        financial_phase_no: Number(item.financial_phase_no),
        schedule_key_id: Number(item.schedule_key_id),
    }));
    const assignmentHost = document.createElement("section");
    assignmentHost.className = "workflow-key-assignments";
    const availableFinancialPhases = catalog.financial_phases || [];
    const availableScheduleKeys = catalog.schedule_keys || [];
    const assignmentsAvailable = Boolean(catalog.schedule_key_assignments_available);
    const renderScheduleKeyAssignments = () => {
        if (!assignmentsAvailable) {
            assignmentHost.innerHTML = '<div class="dependency-note"><strong>A tervezési mérföldkő hozzárendelése még nem érhető el.</strong> Előbb futtasd a 016-os adatbázis-migrációt.</div>';
            return;
        }
        if (!availableFinancialPhases.length || !availableScheduleKeys.length) {
            assignmentHost.innerHTML = '<div class="dependency-note"><strong>Nincs választható pénzügyi fázis vagy aktív tervezési mérföldkő.</strong> A hozzárendeléshez mindkét törzsadat szükséges.</div>';
            return;
        }
        const phaseOptions = (selected) => availableFinancialPhases.map((item) => '<option value="' + Number(item.section_no) + '"' + (Number(item.section_no) === Number(selected) ? " selected" : "") + '>' + Number(item.section_no) + '. penzugyi fazis</option>').join("");
        const keyOptions = (selected) => availableScheduleKeys.map((item) => '<option value="' + Number(item.id) + '"' + (Number(item.id) === Number(selected) ? " selected" : "") + '>' + escapeHtml(item.code) + '</option>').join("");
        const rows = scheduleKeyAssignments.length
            ? scheduleKeyAssignments.map((assignment, index) => '<div class="workflow-key-assignment"><select data-workflow-key-phase="' + index + '"' + (canEdit() ? "" : " disabled") + '>' + phaseOptions(assignment.financial_phase_no) + '</select><select data-workflow-key-id="' + index + '"' + (canEdit() ? "" : " disabled") + '>' + keyOptions(assignment.schedule_key_id) + '</select>' + (canEdit() ? '<button type="button" class="icon-danger" data-remove-workflow-schedule-key="' + index + '" title="Hozzarendeles torlese">x</button>' : "") + '</div>').join("")
            : '<p class="muted">Ehhez az alvállalkozói folyamathoz még nincs tervezési mérföldkő rendelve.</p>';
        assignmentHost.innerHTML = '<div class="panel-header"><div><h3>Pénzügyi fázis és tervezési mérföldkövek</h3><span>Ugyanahhoz a fázishoz több tervezési mérföldkő is rendelhető.</span></div>' + (canEdit() ? '<button id="add-workflow-schedule-key" type="button" class="secondary-button">Hozzárendelés</button>' : "") + '</div><div class="workflow-key-assignment-list">' + rows + '</div>';
        $("#add-workflow-schedule-key", assignmentHost)?.addEventListener("click", () => {
            scheduleKeyAssignments.push({
                financial_phase_no: Number(availableFinancialPhases[0].section_no),
                schedule_key_id: Number(availableScheduleKeys[0].id),
            });
            renderScheduleKeyAssignments();
        });
        $$("[data-remove-workflow-schedule-key]", assignmentHost).forEach((button) => button.addEventListener("click", () => {
            scheduleKeyAssignments.splice(Number(button.dataset.removeWorkflowScheduleKey), 1);
            renderScheduleKeyAssignments();
        }));
        $$("[data-workflow-key-phase]", assignmentHost).forEach((select) => select.addEventListener("change", () => {
            scheduleKeyAssignments[Number(select.dataset.workflowKeyPhase)].financial_phase_no = Number(select.value);
        }));
        $$("[data-workflow-key-id]", assignmentHost).forEach((select) => select.addEventListener("change", () => {
            scheduleKeyAssignments[Number(select.dataset.workflowKeyId)].schedule_key_id = Number(select.value);
        }));
    };
    $('[data-workflow-step="1"]', $("#workflow-form"))?.querySelector(".workflow-step-actions")?.insertAdjacentElement("beforebegin", assignmentHost);
    renderScheduleKeyAssignments();

    const moneyNumber = parseMoneyNumber;
    const renderOfferParts = () => {
        $("#offer-parts-body").innerHTML = offerParts.length ? offerParts.map((part, index) => `<tr><td>${escapeHtml(part.phase_name)}</td><td>${formatMoney(moneyNumber(part.amount))}</td><td>${part.optional ? "Igen" : "Nem"}</td><td><button class="icon-danger step-action" data-remove-offer-part="${index}" type="button" title="Részlet törlése">×</button></td></tr>`).join("") : '<tr><td colspan="4">Nincs részletes bontás.</td></tr>';
        const baseTotal = offerParts.filter((part) => !part.optional).reduce((sum, part) => sum + moneyNumber(part.amount), 0);
        $("#offer-parts-total").textContent = `Alapdíj: ${formatMoney(baseTotal)}`;
        $$('[data-remove-offer-part]').forEach((button) => button.addEventListener("click", () => { offerParts.splice(Number(button.dataset.removeOfferPart), 1); renderOfferParts(); applyWorkflowStepStates(); }));
    };
    const applyWorkflowStepStates = () => {
        $$('[data-workflow-step]').forEach((fieldset) => {
            const editable = Number(fieldset.dataset.workflowStep) === currentStep;
            $$('input, select, textarea, button', fieldset).forEach((control) => { if (!control.classList.contains("step-action")) control.disabled = !editable; });
        });
        $("#workflow-form").elements.currency.disabled = false;
        $("#workflow-form").elements.vat_type.disabled = false;
    };
    renderOfferParts();
    applyWorkflowStepStates();
    const recalcContract = () => { $("#workflow-form").elements.contract_total.value = String(moneyNumber($("#workflow-form").elements.contract_fee.value) + moneyNumber($("#workflow-form").elements.copyright_fee.value)); };
    const applyNoOfferState = () => { const form = $("#workflow-form"); form.elements.offer_price.disabled = form.elements.no_offer.checked || currentStep !== 3; if (form.elements.no_offer.checked) form.elements.offer_price.value = ""; };
    $("#workflow-form").elements.contract_fee.addEventListener("input", recalcContract);
    $("#workflow-form").elements.copyright_fee.addEventListener("input", recalcContract);
    $("#workflow-form").elements.no_offer.addEventListener("change", applyNoOfferState);
    applyNoOfferState();
    $("#add-offer-part").addEventListener("click", () => { const name = $("#offer-part-name").value.trim(); if (!name) return toast("Add meg a részlet nevét.", true); offerParts.push({ phase_name: name, amount: $("#offer-part-amount").value.trim(), optional: $("#offer-part-optional").checked }); $("#offer-part-name").value = ""; $("#offer-part-amount").value = ""; $("#offer-part-optional").checked = false; renderOfferParts(); applyWorkflowStepStates(); });
    $("#new-subcontractor-master")?.addEventListener("click", async () => { const name = prompt("Az új alvállalkozó neve:", $("#workflow-form").elements.company_name.value.trim()); if (!name?.trim()) return; const category = prompt("Kategória / szervezettípus:", $("#workflow-form").elements.discipline.value.trim()) || ""; const code = prompt("Rövid kód (opcionális):", "") || ""; const saved = await api("/subcontractors/catalog/subcontractors", { method: "POST", body: { name: name.trim(), category: category.trim(), code: code.trim() } }); catalog.subcontractors = [...(catalog.subcontractors || []), saved]; $("#workflow-form").elements.company_name.value = saved.name; const list = $("#workflow-companies"); const option = document.createElement("option"); option.value = saved.name; list.append(option); toast("Az alvállalkozó bekerült a központi törzsbe."); });

    const saveWorkflow = async () => {
        const form = $("#workflow-form");
        const entered = formDataObject(form);
        const keys = ["display_order","company_name","discipline","code","finance_class","status_note","preliminary_estimate","offer_status","offer_date","offer_link","received_date","received_link","offer_price","acceptance","feedback","contract_total","contract_fee","copyright_fee","guarantee","notification","draft","signature_status","signature_date","closing_note","currency","vat_type","part_count","modified_fee","modified_copyright_fee","modified_total","modification_date","modification_note"];
        const data = { project_id: state.project.id };
        keys.forEach((key) => data[key] = entered[key] ?? current[key] ?? (key === "display_order" ? 10 : ""));
        Object.assign(data, { display_order: Number(data.display_order || 10), current_step: currentStep, part_count: Number(data.part_count || 1), no_offer: form.elements.no_offer.checked, reopen_completed_payments: form.dataset.reopenPayments === "true" });
        const saved = await api(workflow ? `/subcontractors/${state.project.id}/workflows/${workflow.id}` : `/subcontractors/${state.project.id}/workflows`, { method: workflow ? "PUT" : "POST", body: data });
        await api(`/subcontractors/${state.project.id}/workflows/${saved.id}/offer-parts`, { method: "PUT", body: offerParts.map((part) => ({ phase_name: part.phase_name, amount: part.amount || "", optional: Boolean(part.optional) })) });
        if (assignmentsAvailable) {
            await api(`/subcontractors/${state.project.id}/workflows/${saved.id}/schedule-keys`, {
                method: "PUT",
                body: { assignments: scheduleKeyAssignments },
            });
        }
        return saved;
    };
    $("#open-offer-request-from-modal")?.addEventListener("click", async () => {
        const form = $("#workflow-form");
        if (!form.reportValidity()) return;
        const saved = await saveWorkflow();
        closeModal();
        state.workflowPanelWorkflowId = Number(saved.id);
        state.workflowPanelStep = 2;
        state.workflowPanelDocumentOpen = true;
        await renderSubcontractors();
        await openWorkflowPanel(saved, state.subcontractorCatalog);
    });
    $("#workflow-form").addEventListener("submit", async (event) => { event.preventDefault(); await saveWorkflow(); closeModal(); toast("Az alvállalkozói folyamat mentése sikerült."); await renderSubcontractors(); });
    $$('[data-close-workflow-step]').forEach((button) => button.addEventListener("click", async () => {
        const step = Number(button.dataset.closeWorkflowStep);
        const form = $("#workflow-form");
        if (step === 1 && (!form.elements.company_name.value.trim() || !form.elements.discipline.value.trim())) return toast("A cég és a szakág kitöltése kötelező.", true);
        let allowOfferMismatch = false;
        if (step === 3 && !form.elements.no_offer.checked && offerParts.length) { const detailTotal = offerParts.filter((part) => !part.optional).reduce((sum, part) => sum + moneyNumber(part.amount), 0); const offerTotal = moneyNumber(form.elements.offer_price.value); if (offerTotal && detailTotal && Math.abs(offerTotal - detailTotal) >= .01) { allowOfferMismatch = confirm("Az ajánlati ár nem egyezik a nem opcionális részletek összegével. Biztosan lezárod a lépést?"); if (!allowOfferMismatch) return; } }
        if (step === 5 && form.elements.acceptance.value === "Elfogadva" && !moneyNumber(form.elements.contract_fee.value) && !moneyNumber(form.elements.copyright_fee.value)) return toast("Elfogadott ajánlatnál munkadíj vagy szerzői jogdíj szükséges a mátrixhoz.", true);
        if (step === 5 && workflow && !confirm("A szerződéses összegek mentése a mátrix százalékos celláit újraszámolhatja. Ha már van teljesített pénzügyi tétel, az Várható állapotba nyílik vissza. Folytatod?")) return;
        if (step === 5) $("#workflow-form").dataset.reopenPayments = "true";
        const saved = await saveWorkflow();
        const transitioned = await api(`/subcontractors/${state.project.id}/workflows/${saved.id}/step`, { method: "POST", body: { step, action: "close", allow_offer_mismatch: allowOfferMismatch } });
        closeModal(); toast(`${step}. lépés lezárva.`); await renderSubcontractors(); await openWorkflow(transitioned, catalog);
    }));
    $$('[data-reopen-workflow-step]').forEach((button) => button.addEventListener("click", async () => { const step = Number(button.dataset.reopenWorkflowStep); if (!confirm(`A(z) ${step}. lépés újranyitása a későbbi mátrixadatokat is érintheti. Folytatod?`)) return; const saved = await saveWorkflow(); const transitioned = await api(`/subcontractors/${state.project.id}/workflows/${saved.id}/step`, { method: "POST", body: { step, action: "reopen", allow_offer_mismatch: false } }); closeModal(); toast(`${step}. lépés újranyitva.`); await renderSubcontractors(); await openWorkflow(transitioned, catalog); }));
    $("#new-contract-change")?.addEventListener("click", () => openContractChange(current));
    $$('[data-delete-contract-change]').forEach((button) => button.addEventListener("click", async () => { if (!confirm("Biztosan törlöd ezt a szerződésmódosítást? A korábbi összeg visszaállítása az érintett teljesített pénzügyi tételeket Várható állapotba nyithatja vissza.")) return; const result = await api(`/subcontractors/${state.project.id}/workflows/${current.id}/changes/${button.dataset.deleteContractChange}?reopen_completed_payments=true`, { method: "DELETE" }); closeModal(); toast(result.reopened_payments?.length ? "A módosítás törölve, az érintett pénzügyi tételek visszanyíltak." : "A szerződésmódosítás törölve."); await renderSubcontractors(); await openWorkflow(current); }));
    $("#archive-workflow")?.addEventListener("click", async () => { if (!confirm("Biztosan archiválod ezt az alvállalkozói folyamatot?")) return; await api(`/subcontractors/${state.project.id}/workflows/${workflow.id}`, { method: "DELETE" }); closeModal(); toast("A folyamat archiválva."); await renderSubcontractors(); });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

function openContractChange(workflow) {
    const effectiveFee = parseMoneyNumber(workflow.modified_fee || workflow.contract_fee);
    const effectiveCopyrightFee = parseMoneyNumber(workflow.modified_copyright_fee || workflow.copyright_fee);
    showModal("Új szerződésmódosítás", `${workflow.company_name} · ${workflow.code || "alvállalkozó"}`, `<form id="contract-change-form"><div class="form-grid"><label>Dátum<input name="change_date" type="date" value="${new Date().toISOString().slice(0, 10)}"></label><label class="checkbox-label span-2"><input id="contract-change-affects-finances" type="checkbox"> A módosítás pénzügyi összeget is érint</label><div id="contract-change-financial-fields" class="form-grid span-3" hidden><label>Új munkadíj<input name="modified_fee" inputmode="decimal" value="${effectiveFee}"></label><label>Új szerzői jogdíj<input name="modified_copyright_fee" inputmode="decimal" value="${effectiveCopyrightFee}"></label><div class="dependency-note"><strong>Figyelem:</strong> pénzügyi változásnál a mátrix újraszámolódhat, és a teljesített tételek visszanyílhatnak.</div></div><label class="span-3">Indoklás / tárgy<textarea name="reason" rows="3" required></textarea><small class="field-help">Nem pénzügyi módosítás is rögzíthető; ilyenkor az összegek és a kifizetési állapotok változatlanok maradnak.</small></label></div><div class="modal-actions"><button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Módosítás rögzítése</button></div></form>`);
    const form = $("#contract-change-form");
    const financeToggle = $("#contract-change-affects-finances");
    const financeFields = $("#contract-change-financial-fields");
    const setFinancialMode = () => {
        financeFields.hidden = !financeToggle.checked;
        form.elements.modified_fee.required = financeToggle.checked;
        form.elements.modified_copyright_fee.required = financeToggle.checked;
    };
    financeToggle.addEventListener("change", setFinancialMode);
    setFinancialMode();
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = formDataObject(event.currentTarget);
        const affectsFinances = financeToggle.checked;
        if (!affectsFinances) {
            data.modified_fee = String(effectiveFee);
            data.modified_copyright_fee = String(effectiveCopyrightFee);
        }
        data.modified_total = String(parseMoneyNumber(data.modified_fee) + parseMoneyNumber(data.modified_copyright_fee));
        if (affectsFinances && !confirm("A pénzügyi szerződésmódosítás újraszámolhatja a mátrix százalékos celláit. Az érintett teljesített pénzügyi tételek Várható állapotba nyílnak vissza. Rögzíted a módosítást?")) return;
        data.reopen_completed_payments = affectsFinances;
        const result = await api(`/subcontractors/${state.project.id}/workflows/${workflow.id}/changes`, { method: "POST", body: data });
        closeModal();
        toast(result.reopened_payments?.length ? "A módosítás rögzítve, az érintett pénzügyi tételek visszanyíltak." : "A szerződésmódosítás rögzítve.");
        await renderSubcontractors();
        await openWorkflow(workflow);
    });
    $("[data-close]", $("#modal")).addEventListener("click", () => openWorkflow(workflow));
}

const financeChartColors = ["#2383c4", "#25a968", "#ed8a24", "#8256b3", "#d04c45", "#2d7f84", "#697d8c", "#b38422"];

function financeCanvas(canvas, height = 250) {
    const width = Math.max(320, Math.floor(canvas.getBoundingClientRect().width || 600));
    const ratio = Math.max(1, window.devicePixelRatio || 1);
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    canvas.style.height = `${height}px`;
    const context = canvas.getContext("2d");
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);
    context.font = "12px Segoe UI, Arial, sans-serif";
    return { context, width, height };
}

function drawFinanceDonut(canvas, entries, centerLabel) {
    if (!canvas) return;
    const { context, width, height } = financeCanvas(canvas, 250);
    const usable = entries.filter((item) => Number(item.value || 0) > 0);
    const total = usable.reduce((sum, item) => sum + Number(item.value || 0), 0);
    const radius = Math.min(82, height * .34);
    const centerX = Math.min(width * .32, 150);
    const centerY = height / 2;
    context.lineWidth = 28;
    if (!total) {
        context.strokeStyle = "#e6edf2";
        context.beginPath(); context.arc(centerX, centerY, radius, 0, Math.PI * 2); context.stroke();
    } else {
        let angle = -Math.PI / 2;
        usable.forEach((item, index) => {
            const next = angle + Math.PI * 2 * Number(item.value) / total;
            context.strokeStyle = financeChartColors[index % financeChartColors.length];
            context.beginPath(); context.arc(centerX, centerY, radius, angle, next); context.stroke();
            angle = next;
        });
    }
    context.fillStyle = "#1d3445"; context.font = "700 15px Segoe UI"; context.textAlign = "center";
    context.fillText(centerLabel, centerX, centerY - 4);
    context.font = "700 12px Segoe UI"; context.fillStyle = "#607686";
    context.fillText(formatMoney(total), centerX, centerY + 17);
    context.textAlign = "left"; context.font = "12px Segoe UI";
    usable.slice(0, 7).forEach((item, index) => {
        const y = 35 + index * 27;
        context.fillStyle = financeChartColors[index % financeChartColors.length]; context.fillRect(Math.max(285, width * .5), y - 9, 10, 10);
        context.fillStyle = "#263f50"; context.fillText(String(item.label).slice(0, 25), Math.max(303, width * .5 + 18), y);
    });
}

function drawFinanceLines(canvas, labels, series, valueSuffix = " nap") {
    if (!canvas) return;
    const { context, width, height } = financeCanvas(canvas, 260);
    const left = 46, right = 55, top = 22, bottom = 43;
    const values = series.flatMap((item) => item.values.map(Number));
    const maximum = Math.max(1, ...values);
    context.strokeStyle = "#d9e2e8"; context.fillStyle = "#6b7f8d"; context.font = "11px Segoe UI";
    for (let step = 0; step <= 4; step += 1) {
        const y = top + (height - top - bottom) * step / 4;
        context.beginPath(); context.moveTo(left, y); context.lineTo(width - right, y); context.stroke();
        context.fillText(`${Math.round(maximum * (4 - step) / 4)}${valueSuffix}`, 2, y + 4);
    }
    const xAt = (index) => labels.length <= 1 ? left : left + (width - left - right) * index / (labels.length - 1);
    labels.forEach((label, index) => { if (labels.length <= 8 || index % Math.ceil(labels.length / 8) === 0) { context.save(); context.translate(xAt(index), height - 10); context.rotate(-.45); context.fillStyle = "#607686"; context.fillText(label, 0, 0); context.restore(); } });
    series.forEach((item, seriesIndex) => {
        context.strokeStyle = financeChartColors[seriesIndex % financeChartColors.length]; context.lineWidth = seriesIndex === 0 ? 3 : 2;
        context.beginPath();
        item.values.forEach((value, index) => { const x = xAt(index); const y = top + (height - top - bottom) * (1 - Number(value || 0) / maximum); if (index === 0) context.moveTo(x, y); else context.lineTo(x, y); });
        context.stroke();
    });
}

function drawFinanceBars(canvas, labels, planned, actual) {
    if (!canvas) return;
    const { context, width, height } = financeCanvas(canvas, 240);
    const left = 42, top = 20, bottom = 42;
    const plotWidth = width - left - 18;
    const groupWidth = plotWidth / Math.max(1, labels.length);
    context.strokeStyle = "#d9e2e8"; context.beginPath(); context.moveTo(left, top); context.lineTo(left, height - bottom); context.lineTo(width - 18, height - bottom); context.stroke();
    labels.forEach((label, index) => {
        const x = left + groupWidth * index + groupWidth * .18;
        const plannedHeight = Math.min(100, Number(planned[index] || 0)) / 100 * (height - top - bottom);
        const actualHeight = Math.min(100, Number(actual[index] || 0)) / 100 * (height - top - bottom);
        context.fillStyle = "#aebcc6"; context.fillRect(x, height - bottom - plannedHeight, groupWidth * .27, plannedHeight);
        context.fillStyle = "#ed8a24"; context.fillRect(x + groupWidth * .31, height - bottom - actualHeight, groupWidth * .27, actualHeight);
        if (labels.length <= 8 || index % Math.ceil(labels.length / 8) === 0) { context.save(); context.translate(x, height - 11); context.rotate(-.45); context.fillStyle = "#607686"; context.font = "11px Segoe UI"; context.fillText(label, 0, 0); context.restore(); }
    });
}

function financeDisciplineLegend(series) {
    return series.map((item, index) => `<span><i style="background:${financeChartColors[index % financeChartColors.length]}"></i>${escapeHtml(item.discipline)}</span>`).join("");
}

function drawFinanceDisciplineBars(canvas, labels, series) {
    if (!canvas) return;
    const { context, width, height } = financeCanvas(canvas, 250);
    const left = 42, right = 26, top = 20, bottom = 45;
    const plotHeight = height - top - bottom;
    const groupWidth = (width - left - right) / Math.max(1, labels.length);
    const disciplineWidth = groupWidth * .76 / Math.max(1, series.length);
    context.font = "11px Segoe UI";
    for (let step = 0; step <= 4; step += 1) {
        const y = top + plotHeight * step / 4;
        context.strokeStyle = "#d9e2e8";
        context.beginPath(); context.moveTo(left, y); context.lineTo(width - right, y); context.stroke();
        context.fillStyle = "#607686"; context.fillText(`${100 - step * 25}%`, 2, y + 4);
    }
    labels.forEach((label, monthIndex) => {
        const startX = left + groupWidth * monthIndex + groupWidth * .12;
        series.forEach((item, seriesIndex) => {
            const x = startX + disciplineWidth * seriesIndex;
            const plannedHeight = Math.min(100, Number(item.planned_percent?.[monthIndex] || 0)) / 100 * plotHeight;
            const actualHeight = Math.min(100, Number(item.actual_percent?.[monthIndex] || 0)) / 100 * plotHeight;
            const color = financeChartColors[seriesIndex % financeChartColors.length];
            context.globalAlpha = .24; context.fillStyle = color;
            context.fillRect(x, height - bottom - plannedHeight, Math.max(2, disciplineWidth * .72), plannedHeight);
            context.globalAlpha = 1;
            context.fillRect(x + disciplineWidth * .16, height - bottom - actualHeight, Math.max(2, disciplineWidth * .4), actualHeight);
        });
        if (labels.length <= 8 || monthIndex % Math.ceil(labels.length / 8) === 0) {
            context.save(); context.translate(startX, height - 11); context.rotate(-.45); context.fillStyle = "#607686"; context.fillText(label, 0, 0); context.restore();
        }
    });
    context.globalAlpha = 1;
}

async function renderFinance() {
    const view = beginViewRender("finance");
    if (!view) return;
    try {
    const [summary, payments] = await Promise.all([api(`/finance/${state.project.id}/summary`), api(`/finance/${state.project.id}/payments`)]);
    if (!viewRenderIsCurrent(view)) return;
    const utilization = Math.max(0, Math.min(100, Number(summary.utilization_percent || 0)));
    const disciplines = Object.entries(summary.by_discipline || {}).map(([name, values]) => ({ name, current: Number(values.current || 0), estimated: Number(values.estimated || 0) })).sort((a, b) => b.estimated - a.estimated);
    const derivedItems = summary.finance_items || [];
    const derivedReferences = new Set(derivedItems.map((item) => item.reference));
    const financeItems = [...derivedItems, ...payments.filter((payment) => !derivedReferences.has(payment.reference)).map((payment) => { const orphaned = /^(BEV_MS_\d+|KIA_WF_\d+_COL_(M|STAGE)_\d+)$/i.test(payment.reference || ""); return { reference: payment.reference || `MANUAL_${payment.id}`, is_revenue: payment.is_revenue, workflow_id: payment.workflow_id, title: orphaned ? "Forrás nélküli pénzügyi rögzítés" : payment.reference || payment.invoice_number || "Kézi pénzügyi tétel", partner: orphaned ? "Az ütemtervi vagy mátrixforrás megszűnt" : payment.is_revenue ? "Egyéb bevétel" : "Egyéb kiadás", expected_date: payment.payment_date, expected_amount: orphaned ? 0 : payment.amount, payment, orphaned }; })];
    const allocationRows = [...(summary.allocations?.disciplines || [])];
    if ((summary.allocations?.unassigned?.subcontractors || []).length) allocationRows.push(summary.allocations.unassigned);
    const allocationDisciplines = (summary.allocations?.disciplines || []).map((item) => item.discipline);
    const mappingByWorkflow = new Map((summary.allocations?.mappings || []).map((item) => [Number(item.workflow_id), item.discipline_name]));
    const currentChart = allocationRows.map((item) => ({ label: item.discipline, value: Number(item.internal_current || 0) + Number(item.external_paid || 0) }));
    const forecastChart = allocationRows.map((item) => ({ label: item.discipline, value: Number(item.internal_estimated || 0) + Number(item.external_contracted || 0) }));
    const allocationTable = allocationRows.length ? allocationRows.map((item) => `<tr class="${item.discipline === "Nincs szakághoz rendelve" ? "allocation-warning" : ""}"><td><strong>${escapeHtml(item.discipline)}</strong><small>${(item.subcontractors || []).map((subcontractor) => escapeHtml(subcontractor.company_name)).join(", ") || "Nincs hozzárendelt alvállalkozó"}</small></td><td>${formatMoney(item.internal_current)}</td><td>${formatMoney(item.external_paid)}</td><td>${formatMoney(item.internal_estimated)}</td><td>${formatMoney(item.external_contracted)}</td></tr>`).join("") : '<tr><td colspan="5">Nincs költségallokációs adat.</td></tr>';
    const mappingEditor = canEdit() && summary.subcontractors?.length && allocationDisciplines.length ? `<form id="finance-mapping-form" class="inline-editor finance-mapping-editor"><label>Alvállalkozó<select name="workflow_id" required><option value="">Válassz szerződést</option>${summary.subcontractors.map((item) => `<option value="${item.id}">${escapeHtml(item.company_name)} · ${formatMoney(item.contracted)}</option>`).join("")}</select></label><label>Belső szakág<select name="discipline_name" required><option value="">Válassz szakágat</option>${allocationDisciplines.map((name) => `<option>${escapeHtml(name)}</option>`).join("")}</select></label><button class="primary-button" type="submit">Összerendelés mentése</button></form>` : "";
    const mappingList = summary.subcontractors?.length ? summary.subcontractors.map((item) => `<div class="mapping-row"><span><strong>${escapeHtml(item.company_name)}</strong><small>${escapeHtml(mappingByWorkflow.get(Number(item.id)) || "Nincs szakághoz rendelve")}</small></span>${mappingByWorkflow.has(Number(item.id)) && canEdit() ? `<button type="button" class="icon-button" data-delete-finance-mapping="${item.id}" title="Összerendelés megszüntetése" aria-label="Összerendelés megszüntetése">×</button>` : ""}</div>`).join("") : empty("Nincs elfogadott alvállalkozói szerződés.");
    const dashboard = `<div class="kpi-grid finance-kpis"><div class="kpi"><span>Szerződött keret</span><strong>${formatMoney(summary.budget)}</strong><small>projektbevételi bázis</small></div><div class="kpi amber"><span>Várható belső költség</span><strong>${formatMoney(summary.estimated_internal)}</strong><small>eddigi valós: ${formatMoney(summary.current_internal)}</small></div><div class="kpi orange"><span>Alvállalkozók</span><strong>${formatMoney(summary.external_contracted)}</strong><small>kifizetve: ${formatMoney(summary.external_paid)}</small></div><div class="kpi green"><span>Várható eredmény</span><strong>${formatMoney(summary.estimated_profit)}</strong><small>${(100 - utilization).toLocaleString("hu-HU")}%-os tartalék</small></div></div>
        <section class="panel finance-utilization"><div class="panel-header"><h2>Várható költségkeret kihasználtsága</h2><strong>${utilization.toLocaleString("hu-HU")}%</strong></div><div class="progress-track large"><span style="width:${utilization}%"></span></div></section>
        <div class="finance-chart-grid"><section class="panel"><div class="panel-header"><h2>Jelenlegi állás</h2><span>Tényleges belső + kifizetett külső</span></div><canvas id="finance-current-chart" aria-label="Jelenlegi költségmegoszlás"></canvas></section><section class="panel"><div class="panel-header"><h2>Várható költségek</h2><span>Előrebecsült belső + szerződött külső</span></div><canvas id="finance-forecast-chart" aria-label="Várható költségmegoszlás"></canvas></section></div>
        <section class="panel"><div class="panel-header"><h2>Szakági költségallokáció</h2><span>${summary.allocations?.unassigned?.subcontractors?.length || 0} besorolatlan szerződés</span></div>${mappingEditor}<div class="finance-allocation-layout"><div class="table-wrap"><table><thead><tr><th>Szakág</th><th>Belső tény</th><th>Külső kifizetett</th><th>Belső várható</th><th>Külső szerződött</th></tr></thead><tbody>${allocationTable}</tbody></table></div><div class="mapping-list">${mappingList}</div></div></section>`;
    const labor = `<div class="toolbar"><label>Szakági nézet<select id="finance-labor-filter"><option value="">Szakágak együtt</option>${(summary.labor_trends?.series || []).map((item) => `<option ${state.financeLaborDiscipline === item.discipline ? "selected" : ""}>${escapeHtml(item.discipline)}</option>`).join("")}</select></label><div class="finance-discipline-legend" id="finance-labor-legend"></div></div><div class="finance-chart-grid"><section class="panel"><div class="panel-header"><h2>Havi ráfordítás</h2><span>nap / hónap</span></div><canvas id="finance-monthly-labor-chart"></canvas></section><section class="panel"><div class="panel-header"><h2>Kumulált ráfordítás</h2><span>összesített nap</span></div><canvas id="finance-cumulative-labor-chart"></canvas></section></div><section class="panel"><div class="panel-header"><h2>Tervezett és tényleges készültség</h2><span>halvány: terv · telített: tény</span></div><canvas id="finance-progress-chart"></canvas></section><section class="panel"><div class="panel-header"><h2>Belső költség-előrejelzés</h2><span>szakáganként</span></div><div class="table-wrap"><table><thead><tr><th>Szakág</th><th>Jelenlegi költség</th><th>Előrebecsült költség</th><th>Hátralévő becslés</th><th>Megvalósulás</th></tr></thead><tbody>${disciplines.length ? disciplines.map((item) => { const percent = item.estimated ? Math.min(100, item.current / item.estimated * 100) : 0; return `<tr><td><strong>${escapeHtml(item.name)}</strong></td><td>${formatMoney(item.current)}</td><td>${formatMoney(item.estimated)}</td><td>${formatMoney(Math.max(0, item.estimated - item.current))}</td><td><div class="table-progress"><span style="width:${percent}%"></span></div><small>${percent.toLocaleString("hu-HU", { maximumFractionDigits: 1 })}%</small></td></tr>`; }).join("") : '<tr><td colspan="5">Nincs feldolgozható szakági ráfordítás.</td></tr>'}</tbody><tfoot><tr><th>Összesen</th><th>${formatMoney(summary.current_internal)}</th><th>${formatMoney(summary.estimated_internal)}</th><th>${formatMoney(Math.max(0, Number(summary.estimated_internal) - Number(summary.current_internal)))}</th><th></th></tr></tfoot></table></div></section>`;
    const transactions = `<div class="dependency-note"><strong>Adatforrás:</strong> a bevételeket az ütemtervi mérföldkövek, a kiadásokat a mérföldkövekhez rendelt alvállalkozói mátrixcellák hozzák létre. A pénzügyi státusz ezekhez a forráshivatkozásokhoz kapcsolódik.</div><div class="toolbar"><div class="toolbar-group"><input id="payment-search" type="search" placeholder="Mérföldkő, partner vagy számlaszám"><select id="payment-status-filter"><option value="">Minden státusz</option>${["Várható", "TIG kiállítva", "Számlázva", "Pénzügyileg teljesítve"].map((status) => `<option>${status}</option>`).join("")}</select><select id="payment-type-filter"><option value="">Bevétel és kiadás</option><option value="revenue">Bevétel</option><option value="cost">Kiadás</option></select></div>${canEdit() ? '<button id="new-payment" class="secondary-button" type="button">Egyéb pénzügyi tétel</button>' : ""}</div><div class="finance-process-layout"><section class="panel"><div class="panel-header"><h2>TIG, számla és kifizetés</h2><span id="payment-count">${financeItems.length} várható tétel</span></div><div class="table-wrap"><table><thead><tr><th>Forrás / partner</th><th>Várható dátum</th><th>Várható összeg</th><th>Folyamat</th><th>TIG</th><th>Számla</th><th>Teljesítés</th><th>Tényleges összeg</th><th>Művelet</th></tr></thead><tbody id="payment-table-body"></tbody></table></div></section><aside class="panel payment-mini" id="payment-mini-dashboard"><div class="panel-header"><h2>Kiválasztott tétel</h2></div><div class="empty-state compact"><span>Kattints egy pénzügyi sorra az egyenleg megtekintéséhez.</span></div></aside></div>`;
    const body = state.financeView === "labor" ? labor : state.financeView === "transactions" ? transactions : dashboard;
    $("#content").innerHTML = `<div class="section-heading"><div><h2>Pénzügy</h2><p>dashboard, munkaórák és pénzügyi folyamatok</p></div><div class="heading-actions"><span>${formatMoney(summary.estimated_profit)} várható eredmény</span><a class="secondary-button" href="/api/finance/${state.project.id}/export.xlsx">Excel riport</a></div></div><div class="workspace-tabs"><button data-finance-view="dashboard" class="${state.financeView === "dashboard" ? "active" : ""}" type="button">Vezetői dashboard</button><button data-finance-view="labor" class="${state.financeView === "labor" ? "active" : ""}" type="button">Munkaórák alakulása</button><button data-finance-view="transactions" class="${state.financeView === "transactions" ? "active" : ""}" type="button">Pénzügyi folyamatok</button></div><div class="schedule-workspace">${body}</div>`;
    $$('[data-finance-view]').forEach((button) => button.addEventListener("click", () => { state.financeView = button.dataset.financeView; renderFinance(); }));
    $$('[data-finance-workflow-id]').forEach((button) => button.addEventListener("dblclick", async () => { state.subcontractorView = "offers"; await selectModule("subcontractors"); const workflows = await api(`/subcontractors/${state.project.id}/workflows`); const workflow = workflows.find((item) => item.id === Number(button.dataset.financeWorkflowId)); if (workflow) await openWorkflow(workflow); }));
    if (state.financeView === "dashboard") {
        requestAnimationFrame(() => { drawFinanceDonut($("#finance-current-chart"), currentChart, "Jelenlegi"); drawFinanceDonut($("#finance-forecast-chart"), forecastChart, "Várható"); });
        $("#finance-mapping-form")?.addEventListener("submit", async (event) => { event.preventDefault(); const data = formDataObject(event.currentTarget); await api(`/finance/${state.project.id}/mappings`, { method: "PUT", body: { project_id: state.project.id, workflow_id: Number(data.workflow_id), discipline_name: data.discipline_name } }); toast("A szakági összerendelés mentése sikerült."); await renderFinance(); });
        $$('[data-delete-finance-mapping]').forEach((button) => button.addEventListener("click", async () => { await api(`/finance/${state.project.id}/mappings/${button.dataset.deleteFinanceMapping}`, { method: "DELETE" }); toast("Az összerendelés megszűnt."); await renderFinance(); }));
    }
    if (state.financeView === "labor") {
        const drawLabor = () => {
            const selected = $("#finance-labor-filter").value;
            state.financeLaborDiscipline = selected;
            const allSeries = summary.labor_trends?.series || [];
            const sourceSeries = selected ? allSeries.filter((item) => item.discipline === selected) : allSeries;
            $("#finance-labor-legend").innerHTML = financeDisciplineLegend(sourceSeries);
            requestAnimationFrame(() => {
                drawFinanceLines($("#finance-monthly-labor-chart"), summary.labor_trends?.months || [], sourceSeries.map((item) => ({ label: item.discipline, values: item.monthly_days || [] })));
                drawFinanceLines($("#finance-cumulative-labor-chart"), summary.labor_trends?.months || [], sourceSeries.map((item) => ({ label: item.discipline, values: item.cumulative_days || [] })));
                drawFinanceDisciplineBars($("#finance-progress-chart"), summary.labor_trends?.months || [], sourceSeries);
            });
        };
        $("#finance-labor-filter").addEventListener("change", drawLabor); drawLabor();
    }
    if (state.financeView === "transactions") {
        const statusStep = (status) => Math.max(0, ["Várható", "TIG kiállítva", "Számlázva", "Pénzügyileg teljesítve"].indexOf(status || "Várható"));
        const updateMiniDashboard = (item) => {
            const payment = item.payment || {}; const workflow = summary.subcontractors?.find((row) => Number(row.id) === Number(item.workflow_id));
            const base = Number(workflow?.contracted || item.expected_amount || 0); const paid = Number(workflow?.paid || (payment.status === "Pénzügyileg teljesítve" ? payment.amount : 0) || 0); const remaining = Math.max(0, base - paid); const percent = base ? Math.min(100, paid / base * 100) : 0;
            $("#payment-mini-dashboard").innerHTML = `<div class="panel-header"><h2>${escapeHtml(item.partner || "Pénzügyi tétel")}</h2><span>${item.is_revenue ? "Bevétel" : "Kiadás"}</span></div><div class="payment-mini-body"><strong>${escapeHtml(item.title || item.reference)}</strong><div class="mini-balance"><span>Bázis <b>${formatMoney(base)}</b></span><span>Teljesítve <b>${formatMoney(paid)}</b></span><span>Hátralék <b>${formatMoney(remaining)}</b></span></div><div class="progress-track large"><span style="width:${percent}%"></span></div><small>${escapeHtml(payment.status || "Várható")} · ${percent.toLocaleString("hu-HU", { maximumFractionDigits: 1 })}%</small></div>`;
        };
        const renderPaymentRows = () => {
            const search = $("#payment-search").value.trim().toLocaleLowerCase("hu-HU"); const status = $("#payment-status-filter").value; const type = $("#payment-type-filter").value;
            const filtered = financeItems.filter((item) => { const payment = item.payment || {}; return (!search || `${item.title || ""} ${item.partner || ""} ${payment.invoice_number || ""}`.toLocaleLowerCase("hu-HU").includes(search)) && (!status || (payment.status || "Várható") === status) && (!type || (type === "revenue") === Boolean(item.is_revenue)); }).sort((a, b) => String(a.expected_date || "9999-12-31").localeCompare(String(b.expected_date || "9999-12-31")));
            $("#payment-count").textContent = `${filtered.length} tétel`;
            let previousMonth = "";
            $("#payment-table-body").innerHTML = filtered.length ? filtered.map((item) => {
                const payment = item.payment || {};
                const mismatch = !item.orphaned && payment.status === "Pénzügyileg teljesítve" && Math.abs(Number(payment.amount || 0) - Number(item.expected_amount || 0)) >= .01;
                const itemIndex = financeItems.indexOf(item);
                const month = item.expected_date ? String(item.expected_date).slice(0, 7) : "Dátum nélkül";
                const monthRow = month !== previousMonth ? `<tr class="finance-month-row"><td colspan="9">${escapeHtml(month === "Dátum nélkül" ? month : month.replace("-", ". "))}</td></tr>` : "";
                previousMonth = month;
                const step = statusStep(payment.status);
                const rowClasses = [item.orphaned ? "financial-orphan" : "", mismatch ? "financial-mismatch" : "", item.is_revenue ? "finance-revenue-row" : "finance-cost-row"].filter(Boolean).join(" ");
                return `${monthRow}<tr data-finance-item-index="${itemIndex}" class="${rowClasses}"><td><strong>${escapeHtml(item.title || item.reference)}</strong><small>${escapeHtml(item.partner || "")} · ${item.is_revenue ? "bevétel" : "kiadás"}</small></td><td>${formatDate(item.expected_date)}</td><td><strong>${item.orphaned ? "–" : formatMoney(item.expected_amount)}</strong></td><td><div class="payment-steps" title="${escapeHtml(payment.status || "Várható")}">${[0,1,2,3].map((index) => `<i class="${index <= step ? "done" : ""}"></i>`).join("")}</div><span class="payment-status">${escapeHtml(payment.status || "Várható")}</span>${item.orphaned ? '<small>Nem számít bele; ellenőrizd vagy töröld</small>' : mismatch ? '<small>Az alapösszeg megváltozott</small>' : ""}</td><td>${formatDate(payment.tig_date)}</td><td>${escapeHtml(payment.invoice_number || "–")}<small>${formatDate(payment.invoice_date)}</small></td><td>${formatDate(payment.payment_date)}</td><td>${payment.id ? `<strong>${formatMoney(payment.amount)}</strong>` : "–"}</td><td class="finance-row-action"><button type="button" class="secondary-button compact" data-edit-finance-item-index="${itemIndex}">${payment.id ? "Szerkesztés" : "Rögzítés"}</button></td></tr>`;
            }).join("") : '<tr><td colspan="9">Nincs a szűrésnek megfelelő pénzügyi tétel.</td></tr>';
            $$('[data-finance-item-index]').forEach((row) => { row.addEventListener("click", () => { $$('[data-finance-item-index]').forEach((item) => item.classList.toggle("selected", item === row)); updateMiniDashboard(financeItems[Number(row.dataset.financeItemIndex)]); }); row.addEventListener("dblclick", (event) => { if (event.target.closest("button")) return; const item = financeItems[Number(row.dataset.financeItemIndex)]; openPayment(item.payment || null, item); }); });
            $$('[data-edit-finance-item-index]').forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); const item = financeItems[Number(button.dataset.editFinanceItemIndex)]; openPayment(item.payment || null, item); }));
        };
        $("#new-payment")?.addEventListener("click", () => openPayment());
        $("#payment-search").addEventListener("input", renderPaymentRows); $("#payment-status-filter").addEventListener("change", renderPaymentRows); $("#payment-type-filter").addEventListener("change", renderPaymentRows); renderPaymentRows();
    }
    } catch (error) {
        if (viewRenderIsCurrent(view)) throw error;
    }
}

function openPayment(payment = null, expectedItem = null) {
    if (payment && expectedItem?.orphaned) {
        showModal("Forrás nélküli pénzügyi rögzítés", payment.reference || "régi tétel", `<div class="dependency-note danger"><strong>Az eredeti ütemtervi vagy mátrixforrás már nem létezik.</strong><p>Ez a rekord nem számít bele a pénzügyi összesítésbe. Nem kapcsolható át másik forrásra; ellenőrzés után törölhető.</p></div><div class="financial-source"><span>Korábbi státusz</span><strong>${escapeHtml(payment.status || "Várható")}</strong><span>Rögzített összeg</span><strong>${formatMoney(payment.amount)}</strong><span>Számlaszám</span><strong>${escapeHtml(payment.invoice_number || "–")}</strong></div><div class="modal-actions"><button id="delete-orphan-payment" type="button" class="danger-button">Rögzítés törlése</button><button type="button" data-close class="secondary-button">Bezárás</button></div>`);
        $("#delete-orphan-payment").addEventListener("click", async () => { if (!confirm("Biztosan törlöd a forrás nélküli pénzügyi rögzítést?")) return; await api(`/finance/${state.project.id}/payments/${payment.id}`, { method: "DELETE" }); closeModal(); toast("A forrás nélküli pénzügyi rögzítés törölve lett."); await renderFinance(); });
        $("[data-close]", $("#modal")).addEventListener("click", closeModal);
        return;
    }
    const current = payment || { reference: expectedItem?.reference || "", workflow_id: expectedItem?.workflow_id || null, payment_date: "", amount: "", is_revenue: Boolean(expectedItem?.is_revenue) };
    const statuses = ["Várható", "TIG kiállítva", "Számlázva", "Pénzügyileg teljesítve"];
    showModal(payment ? "Pénzügyi folyamat szerkesztése" : expectedItem ? "Várható tétel pénzügyi rögzítése" : "Egyéb pénzügyi tétel", expectedItem ? `${expectedItem.partner} · ${expectedItem.title}` : state.project.name, `<form id="payment-form">${expectedItem ? `<div class="financial-source"><span>Forráshivatkozás</span><strong>${escapeHtml(expectedItem.reference)}</strong><span>Várható dátum</span><strong>${formatDate(expectedItem.expected_date)}</strong><span>Mátrix / mérföldkő szerinti összeg</span><strong>${formatMoney(expectedItem.expected_amount)}</strong></div>` : ""}<div class="payment-workflow-stepper" id="payment-workflow-stepper">${statuses.map((status, index) => `<div data-payment-step="${index}"><i>${index + 1}</i><span>${escapeHtml(status)}</span></div>`).join("")}</div><div class="form-grid"><label>Teljesítés / utalás<input name="payment_date" type="date" value="${escapeHtml(current.payment_date || "")}"></label><label>Tényleges összeg (Ft)<input name="amount" type="number" min="0" step="0.01" value="${escapeHtml(current.amount || expectedItem?.expected_amount || "")}" required></label><label>Státusz<select name="status">${statuses.map((status) => `<option ${status === (current.status || "Várható") ? "selected" : ""}>${escapeHtml(status)}</option>`).join("")}</select></label><label>Számlaszám<input name="invoice_number" maxlength="120" value="${escapeHtml(current.invoice_number || "")}"></label><label>TIG dátuma<input name="tig_date" type="date" value="${escapeHtml(current.tig_date || "")}"></label><label>Számla dátuma<input name="invoice_date" type="date" value="${escapeHtml(current.invoice_date || "")}"></label><label class="span-2">Hivatkozás<input name="reference" maxlength="255" value="${escapeHtml(current.reference || "")}" ${expectedItem ? "readonly" : ""}></label><label class="span-2">Igazolás vagy dokumentum hivatkozása<input name="verification_link" maxlength="1000" value="${escapeHtml(current.verification_link || "")}"></label><label class="check-line span-2"><input name="is_revenue" type="checkbox" ${current.is_revenue ? "checked" : ""} ${expectedItem ? "disabled" : ""}> Bevételként számítandó tranzakció</label></div><div class="modal-actions">${payment ? '<button id="delete-payment" type="button" class="danger-button">Pénzügyi rögzítés törlése</button>' : ""}<button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Mentés</button></div></form>`);
    const paymentForm = $("#payment-form");
    const updatePaymentStepper = () => { const activeStep = statuses.indexOf(paymentForm.elements.status.value); $$('[data-payment-step]', paymentForm).forEach((step) => step.classList.toggle("active", Number(step.dataset.paymentStep) <= activeStep)); };
    paymentForm.elements.status.addEventListener("change", updatePaymentStepper); updatePaymentStepper();
    $("#payment-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const entered = formDataObject(form);
        const step = statuses.indexOf(entered.status);
        if (step >= 1 && !entered.tig_date) return toast("A kiválasztott státuszhoz add meg a TIG dátumát.", true);
        if (step >= 2 && (!entered.invoice_date || !entered.invoice_number.trim())) return toast("A számlázott státuszhoz add meg a számla dátumát és számát.", true);
        if (step >= 3 && (!entered.payment_date || Number(entered.amount || 0) <= 0)) return toast("A pénzügyi teljesítéshez add meg a teljesítés dátumát és összegét.", true);
        const data = {
            project_id: state.project.id,
            workflow_id: current.workflow_id || expectedItem?.workflow_id || null,
            payment_date: valueOrNull(entered.payment_date),
            amount: Number(entered.amount),
            verification_link: entered.verification_link || "",
            is_revenue: expectedItem ? Boolean(expectedItem.is_revenue) : form.elements.is_revenue.checked,
            reference: entered.reference || "",
            invoice_number: entered.invoice_number || "",
            status: entered.status,
            tig_date: valueOrNull(entered.tig_date),
            invoice_date: valueOrNull(entered.invoice_date),
        };
        await api(payment ? `/finance/${state.project.id}/payments/${payment.id}` : `/finance/${state.project.id}/payments`, { method: payment ? "PUT" : "POST", body: data });
        closeModal();
        toast("A pénzügyi tranzakció mentése sikerült.");
        await renderFinance();
    });
    $("#delete-payment")?.addEventListener("click", async () => { if (!confirm("Biztosan törlöd ezt a pénzügyi tranzakciót?")) return; await api(`/finance/${state.project.id}/payments/${payment.id}`, { method: "DELETE" }); closeModal(); toast("A pénzügyi tranzakció törölve lett."); await renderFinance(); });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

async function ensureEngagementData() {
    const navigation = state.navigationVersion, projectId = state.project?.id;
    if (!projectId) return;
    if (!state.master) state.master = await api("/engagements/master-data");
    if (navigation !== state.navigationVersion || state.project?.id !== projectId) return;
    const disciplines = await api(`/engagements/disciplines/${projectId}`);
    if (navigation !== state.navigationVersion || state.project?.id !== projectId) return;
    state.engagementDisciplines = disciplines;
}

async function renderEngagements() {
    const view = beginViewRender("engagements");
    if (!view) return;
    try {
    await ensureEngagementData();
    if (!viewRenderIsCurrent(view)) return;
    const dashboard = await api(`/engagements/dashboard/${state.project.id}`);
    if (!viewRenderIsCurrent(view)) return;
    $("#content").innerHTML = `<div class="kpi-grid"><div class="kpi"><span>Összes ügy</span><strong>${dashboard.total || 0}</strong></div><div class="kpi green"><span>Lezárt</span><strong>${dashboard.closed || 0}</strong><small>${Number(dashboard.progress_percent || 0).toLocaleString("hu-HU")}% súlyozott készültség</small></div><div class="kpi amber"><span>Nyitott</span><strong>${dashboard.open || 0}</strong></div><div class="kpi red"><span>Figyelmet igényel</span><strong>${dashboard.attention || 0}</strong></div></div>
        <div class="toolbar"><div class="toolbar-group"><input id="eng-search" type="search" placeholder="Partner, feladat, cím vagy megjegyzés" value="${escapeHtml($("#global-search").value)}"><select id="eng-discipline-filter"><option value="">Minden szakág</option>${state.engagementDisciplines.map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join("")}</select><select id="eng-status-filter"><option value="">Minden státusz</option>${state.master.statuses.map((s) => `<option value="${escapeHtml(s.code)}">${escapeHtml(s.code)} – ${escapeHtml(s.name)}</option>`).join("")}</select><button id="eng-filter" class="secondary-button" type="button">Szűrés</button></div><div class="toolbar-group"><button id="partner-database" class="secondary-button" type="button">Partneradatbázis</button>${canEdit() ? '<button id="import-excel" class="secondary-button" type="button">Excel import</button><button id="new-assignment" class="primary-button" type="button">Új ügy</button>' : ""}<button id="export-pdf" class="secondary-button" type="button">PDF riport</button><button id="export-excel" class="secondary-button" type="button">Excel export</button></div></div>
        <section class="panel"><div class="panel-header"><h2>Engedélyezési ügyek</h2><span id="assignment-count"></span></div><div id="assignment-table">${empty("Ügyek betöltése…")}</div></section>`;
    $("#eng-filter").addEventListener("click", loadAssignmentTable);
    $("#eng-search").addEventListener("keydown", (event) => { if (event.key === "Enter") loadAssignmentTable(); });
    $("#new-assignment")?.addEventListener("click", openNewAssignment);
    $("#partner-database").addEventListener("click", openPartnerDatabase);
    $("#import-excel")?.addEventListener("click", openEngagementImport);
    $("#export-excel").addEventListener("click", () => downloadFile(`/engagements/export/${state.project.id}.xlsx`, `engedelyek-${state.project.id}.xlsx`));
    $("#export-pdf").addEventListener("click", () => downloadFile(`/engagements/export/${state.project.id}.pdf`, `engedelyek-${state.project.id}.pdf`));
    await loadAssignmentTable();
    } catch (error) {
        if (viewRenderIsCurrent(view)) throw error;
    }
}

async function loadAssignmentTable() {
    const navigation = state.navigationVersion, version = ++state.assignmentRenderVersion;
    if (state.module !== "engagements" || !state.project) return;
    const params = { project_id: state.project.id, search: $("#eng-search")?.value || $("#global-search").value, discipline_id: $("#eng-discipline-filter")?.value, status_code: $("#eng-status-filter")?.value };
    const result = await api(`/engagements/assignments${toQuery(params)}`);
    if (navigation !== state.navigationVersion || version !== state.assignmentRenderVersion || state.module !== "engagements") return;
    $("#assignment-count").textContent = `${result.total} ügy`;
    $("#assignment-table").innerHTML = result.items.length ? `<div class="table-wrap"><table><thead><tr><th>Partner</th><th>Szakág</th><th>Feladat</th><th>Státusz</th><th>Utolsó dátum</th><th>Érvényes</th><th>Felelős</th></tr></thead><tbody>${result.items.map((a) => `<tr data-assignment-id="${a.id}"><td><strong>${escapeHtml(a.partner_name || a.temporary_partner_name || "Nincs partner")}</strong>${a.temporary_partner_name ? "<br><small>Jóváhagyásra váró partner</small>" : ""}</td><td>${escapeHtml(a.discipline_name)}</td><td>${escapeHtml(a.task_name)}</td><td>${statusBadge(a)}</td><td>${formatDate(a.last_date)}</td><td>${formatDate(a.valid_until)}</td><td>${escapeHtml(a.responsible || "–")}</td></tr>`).join("")}</tbody></table></div>` : empty("Nincs a szűrésnek megfelelő ügy.");
    $$("[data-assignment-id]").forEach((row) => row.addEventListener("dblclick", () => openAssignment(Number(row.dataset.assignmentId))));
}

function partnerOptions(partners, selectedId = null, selectedTemporary = null) {
    return partners.map((p) => `<option value="${p.temporary ? `t:${p.temporary_request_id}` : `p:${p.id}`}" ${(p.id === selectedId || p.temporary_request_id === selectedTemporary) ? "selected" : ""}>${escapeHtml(p.name)}${p.temporary ? " (jóváhagyásra vár)" : ""}</option>`).join("");
}

async function openNewAssignment() {
    const partners = await api("/engagements/partners?include_pending=true&limit=500");
    showModal("Új engedélyezési ügy", state.project.name, `<form id="assignment-create"><div class="form-grid"><label class="span-2">Partner<select name="partner_choice" required><option value="">Válassz partnert</option>${partnerOptions(partners)}</select></label><label>Szakág<select name="discipline_id" required>${state.engagementDisciplines.map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join("")}</select></label><label class="span-2">Feladat<select name="task_id" required>${state.master.tasks.map((t) => `<option value="${t.id}" data-weight="${t.weight}">${escapeHtml(t.name)}</option>`).join("")}</select></label><label>Súly<input name="weight" type="number" min="0" step="0.01" value="1"></label><label class="span-2">Cím<input name="address" maxlength="500"></label><label>Érvényesség<input name="valid_until" type="date"></label><label>Felelős<input name="responsible" maxlength="255"></label><label>Határidő<input name="due_date" type="date"></label><label>Kezdő státusz<select name="status_code">${state.master.statuses.map((s) => `<option value="${escapeHtml(s.code)}">${escapeHtml(s.code)} – ${escapeHtml(s.name)}</option>`).join("")}</select></label><label class="span-3">Megjegyzés<textarea name="main_note" rows="4" maxlength="5000"></textarea></label></div><div class="modal-actions"><button type="button" class="secondary-button" data-close>Bezárás</button><button type="submit" class="primary-button">Ügy létrehozása</button></div></form>`);
    $("#assignment-create").addEventListener("submit", async (event) => {
        event.preventDefault(); const data = formDataObject(event.currentTarget); const [type, id] = data.partner_choice.split(":"); delete data.partner_choice;
        Object.assign(data, { project_id: state.project.id, discipline_id: Number(data.discipline_id), task_id: Number(data.task_id), weight: Number(data.weight), partner_id: type === "p" ? Number(id) : null, temporary_partner_request_id: type === "t" ? Number(id) : null, valid_until: valueOrNull(data.valid_until), due_date: valueOrNull(data.due_date) });
        await api("/engagements/assignments", { method: "POST", body: data }); closeModal(); toast("Az ügy létrejött."); await renderEngagements();
    });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

async function openAssignment(id) {
    const detail = await api(`/engagements/assignments/${id}`);
    const partner = detail.partner || detail.temporary_partner_request?.proposed_data || {};
    showModal(`${partner.name || "Engedélyezési ügy"}`, `${detail.discipline?.name || "Szakág"} · ${detail.task?.name || "Feladat"}`, `<div class="detail-tabs"><button class="active" type="button" data-detail-tab="data">Ügyadatok</button><button type="button" data-detail-tab="rounds">Folyamat és körök</button><button type="button" data-detail-tab="files">Csatolmányok</button></div>
        <section data-detail-panel="data"><form id="assignment-edit"><div class="form-grid"><label>Szakág<select name="discipline_id">${state.engagementDisciplines.map((d) => `<option value="${d.id}" ${d.id === detail.discipline_id ? "selected" : ""}>${escapeHtml(d.name)}</option>`).join("")}</select></label><label class="span-2">Feladat<select name="task_id">${state.master.tasks.map((t) => `<option value="${t.id}" ${t.id === detail.task_id ? "selected" : ""}>${escapeHtml(t.name)}</option>`).join("")}</select></label><label class="span-2">Cím<input name="address" value="${escapeHtml(detail.address)}"></label><label>Súly<input name="weight" type="number" min="0" step="0.01" value="${escapeHtml(detail.weight)}"></label><label>Felelős<input name="responsible" value="${escapeHtml(detail.responsible)}"></label><label>Határidő<input name="due_date" type="date" value="${escapeHtml(detail.due_date || "")}"></label><label>Érvényesség<input name="valid_until" type="date" value="${escapeHtml(detail.valid_until || "")}"></label><label class="span-3">Fő megjegyzés<textarea name="main_note" rows="4">${escapeHtml(detail.main_note)}</textarea></label></div><div class="current-status"><span>Aktuális státusz</span>${statusBadge(detail.status || { status_code: detail.status_code })}<small>A státuszt elsődlegesen az aktuális folyamatkörnél kell megadni.</small></div>${canEdit() ? '<div class="modal-actions"><button id="archive-assignment" class="danger-button" type="button">Ügy archiválása</button><button class="primary-button" type="submit">Adatok mentése</button></div>' : ""}</form>${detail.partner ? `<div class="partner-actions"><strong>Központi partneradat</strong><span>${escapeHtml(partner.address || "")}</span>${canEdit() ? '<button id="request-partner-update" class="secondary-button" type="button">Módosítás kérése</button><button id="request-partner-delete" class="danger-button" type="button">Törlés kérése</button>' : ""}</div>` : ""}</section>
        <section data-detail-panel="rounds" hidden>${renderRounds(detail)}${canEdit() ? renderRoundForm() : ""}</section>
        <section data-detail-panel="files" hidden>${renderAttachments(detail)}${canEdit() ? renderAttachmentForm() : ""}</section>`);
    wireDetailTabs();
    $("#assignment-edit")?.addEventListener("submit", async (event) => { event.preventDefault(); const data = formDataObject(event.currentTarget); Object.assign(data, { discipline_id: Number(data.discipline_id), task_id: Number(data.task_id), weight: Number(data.weight), due_date: valueOrNull(data.due_date), valid_until: valueOrNull(data.valid_until) }); await api(`/engagements/assignments/${id}`, { method: "PATCH", body: data }); toast("Az ügy adatai frissültek."); await openAssignment(id); await loadAssignmentTable(); });
    $("#archive-assignment")?.addEventListener("click", async () => { if (!confirm("Biztosan archiválod ezt az ügyet? Az előzmények megmaradnak.")) return; await api(`/engagements/assignments/${id}`, { method: "DELETE" }); closeModal(); toast("Az ügy archiválva lett."); await renderEngagements(); });
    $("#round-create")?.addEventListener("submit", async (event) => { event.preventDefault(); const data = formDataObject(event.currentTarget); ["sent_date", "received_date", "intervention_type_id"].forEach((key) => data[key] = valueOrNull(data[key])); if (data.intervention_type_id) data.intervention_type_id = Number(data.intervention_type_id); await api(`/engagements/assignments/${id}/rounds`, { method: "POST", body: data }); toast("Az új folyamatkör mentése sikerült."); await openAssignment(id); await loadAssignmentTable(); });
    $("#attachment-upload")?.addEventListener("submit", async (event) => { event.preventDefault(); await api(`/engagements/assignments/${id}/attachments`, { method: "POST", body: new FormData(event.currentTarget) }); toast("A csatolmány feltöltése sikerült."); await openAssignment(id); });
    $("#request-partner-update")?.addEventListener("click", () => openPartnerChange("update", detail.partner));
    $("#request-partner-delete")?.addEventListener("click", () => openPartnerChange("delete", detail.partner));
}

function wireDetailTabs() {
    $$("[data-detail-tab]").forEach((button) => button.addEventListener("click", () => {
        $$("[data-detail-tab]").forEach((item) => item.classList.toggle("active", item === button));
        $$("[data-detail-panel]").forEach((panel) => panel.hidden = panel.dataset.detailPanel !== button.dataset.detailTab);
    }));
}

function renderRounds(detail) {
    return `<div class="timeline">${(detail.rounds || []).length ? detail.rounds.map((r) => { const status = state.master.statuses.find((s) => s.code === r.status_code) || { code: r.status_code }; const intervention = state.master.intervention_types.find((i) => i.id === r.intervention_type_id); return `<article class="timeline-item"><header><strong>${r.round_no}. kör</strong>${statusBadge(status)}</header><div class="round-grid"><div><small>Kiküldés</small><b>${formatDate(r.sent_date)}</b><p>${escapeHtml(r.sent_note || "Nincs megjegyzés")}</p></div><div><small>Beérkezés</small><b>${formatDate(r.received_date)}</b><p>${escapeHtml(r.received_note || "Nincs megjegyzés")}</p></div></div>${intervention ? `<small>Beavatkozás: ${escapeHtml(intervention.name)}</small>` : ""}</article>`; }).join("") : empty("Még nincs rögzített folyamatkör.")}</div>`;
}

function renderRoundForm() {
    return `<section class="subpanel"><h3>Új folyamatkör</h3><p class="muted">A kiküldés és a beérkezés külön mező; az aktuális státusz ennél a lépésnél kötelező.</p><form id="round-create"><div class="form-grid"><label>Kiküldés dátuma<input name="sent_date" type="date"></label><label class="span-2">Kiküldési megjegyzés<textarea name="sent_note" rows="2"></textarea></label><label>Beérkezés dátuma<input name="received_date" type="date"></label><label class="span-2">Beérkezési megjegyzés<textarea name="received_note" rows="2"></textarea></label><label>Beavatkozás<select name="intervention_type_id"><option value="">Nincs megadva</option>${state.master.intervention_types.map((i) => `<option value="${i.id}">${escapeHtml(i.name)}</option>`).join("")}</select></label><label class="span-2">Aktuális státusz<select name="status_code" required>${state.master.statuses.map((s) => `<option value="${escapeHtml(s.code)}">${escapeHtml(s.code)} – ${escapeHtml(s.name)}</option>`).join("")}</select></label></div><div class="modal-actions"><button class="primary-button" type="submit">Folyamatkör mentése</button></div></form></section>`;
}

function renderAttachments(detail) {
    return `<div class="file-list">${(detail.attachments || []).length ? detail.attachments.map((f) => `<div><span aria-hidden="true">▣</span><strong>${escapeHtml(f.original_name)}</strong><small>${Math.ceil(Number(f.size_bytes || 0) / 1024)} KB · ${formatDate(f.created_at)}</small><p>${escapeHtml(f.note)}</p><a class="secondary-button file-open" href="/api/engagements/attachments/${f.id}/download" target="_blank" rel="noopener">Megnyitás</a></div>`).join("") : empty("Nincs csatolmány.")}</div>`;
}

function renderAttachmentForm() {
    return `<form id="attachment-upload" class="upload-form"><label>Fájl<input name="file" type="file" accept=".pdf,.xlsx,.xlsm,.docx,.jpg,.jpeg,.png" required></label><label>Megjegyzés<input name="note" maxlength="2000"></label><button class="primary-button" type="submit">Feltöltés</button></form>`;
}

function openEngagementImport() {
    showModal("Excel-adatok importálása", state.project.name, `<form id="engagement-import"><div class="upload-form"><label>Excel-munkafüzet<input name="file" type="file" accept=".xlsx,.xlsm" required></label><span class="muted">Legfeljebb 15 MB. A rendszer makrót és képletet nem futtat.</span><button class="primary-button" type="submit">Előnézet készítése</button></div></form><div id="import-preview"></div>`);
    $("#engagement-import").addEventListener("submit", async (event) => {
        event.preventDefault();
        const file = $("input[type=file]", event.currentTarget).files[0];
        const form = new FormData(); form.append("file", file);
        const preview = await api("/engagements/import/preview", { method: "POST", body: form });
        const assignmentCount = (preview.disciplines || []).reduce((sum, item) => sum + (item.assignments || []).length, 0);
        $("#import-preview").innerHTML = `<section class="subpanel"><h3>Importálási előnézet</h3><div class="matrix-summary"><div><span>Feladat</span><strong>${preview.tasks.length}</strong></div><div><span>Partner</span><strong>${preview.partners.length}</strong></div><div><span>Szakág</span><strong>${preview.disciplines.length}</strong></div><div><span>Ügy</span><strong>${assignmentCount}</strong></div><div><span>Duplikáció</span><strong>${preview.duplicates.length}</strong></div><div><span>Javítandó hiba</span><strong>${preview.errors.length}</strong></div></div>${preview.errors.length ? `<div class="import-errors">${preview.errors.slice(0, 50).map((error) => `<p><strong>${escapeHtml(error.sheet || "Munkafüzet")}</strong>: ${escapeHtml(error.message)}${error.row ? ` (${error.row}. sor)` : ""}</p>`).join("")}</div>` : '<div class="modal-actions"><button id="commit-import" class="primary-button" type="button">Import véglegesítése</button></div>'}</section>`;
        $("#commit-import")?.addEventListener("click", async () => { const commitForm = new FormData(); commitForm.append("file", file); await api(`/engagements/import/${state.project.id}`, { method: "POST", body: commitForm }); closeModal(); toast("Az Excel-adatok importálása elkészült."); await renderEngagements(); });
    });
}

async function openPartnerDatabase(search = "") {
    const partners = await api(`/engagements/partners${toQuery({ search, include_pending: true, limit: 500 })}`);
    showModal("Engedélyezési partneradatbázis", "Minden projekt közös partnerállománya", `<div class="toolbar"><div class="toolbar-group"><input id="partner-search" type="search" value="${escapeHtml(search)}" placeholder="Név, cím, e-mail vagy szervezettípus"><button id="partner-search-button" class="secondary-button" type="button">Keresés</button></div>${canEdit() ? '<button id="new-partner-request" class="primary-button" type="button">Új partner javaslata</button>' : ""}</div><div class="table-wrap"><table><thead><tr><th>Név</th><th>Cím</th><th>Ügyintéző</th><th>Elérhetőség</th><th>Állapot</th></tr></thead><tbody>${partners.map((p) => `<tr data-partner-id="${p.id || ""}" data-temp-id="${p.temporary_request_id || ""}"><td><strong>${escapeHtml(p.name)}</strong></td><td>${escapeHtml(p.address)}</td><td>${escapeHtml(p.contact_person)}</td><td>${escapeHtml(p.email)}<br>${escapeHtml(p.phone)}</td><td>${p.temporary ? "Jóváhagyásra vár" : "Központi partner"}</td></tr>`).join("")}</tbody></table></div>`);
    $("#partner-search-button").addEventListener("click", () => openPartnerDatabase($("#partner-search").value));
    $("#partner-search").addEventListener("keydown", (event) => { if (event.key === "Enter") openPartnerDatabase(event.currentTarget.value); });
    $("#new-partner-request")?.addEventListener("click", () => openPartnerChange("create", {}));
    $$("[data-partner-id]").forEach((row) => row.addEventListener("dblclick", () => { const partner = partners.find((p) => String(p.id || "") === row.dataset.partnerId && String(p.temporary_request_id || "") === row.dataset.tempId); if (partner && !partner.temporary && canEdit()) openPartnerChange("update", partner); }));
}

function openPartnerChange(type, partner) {
    const labels = { create: "Új partner javaslata", update: "Partnermódosítás kérése", delete: "Partner törlésének kérése" };
    showModal(labels[type], "Adminisztrátori jóváhagyás szükséges", `<form id="partner-change"><div class="form-grid"><label class="span-2">Partner neve<input name="name" value="${escapeHtml(partner.name)}" required></label><label>Szervezettípus<input name="org_type" value="${escapeHtml(partner.org_type)}"></label><label class="span-2">Cím<input name="address" value="${escapeHtml(partner.address)}"></label><label>Ügyintéző<input name="contact_person" value="${escapeHtml(partner.contact_person)}"></label><label>E-mail<input name="email" type="email" value="${escapeHtml(partner.email)}"></label><label>Telefonszám<input name="phone" value="${escapeHtml(partner.phone)}"></label><label class="span-3">Indoklás<textarea name="reason" rows="3"></textarea></label></div><div class="modal-actions"><button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Kérelem beküldése</button></div></form>`);
    $("#partner-change").addEventListener("submit", async (event) => { event.preventDefault(); const data = formDataObject(event.currentTarget); const reason = data.reason; delete data.reason; await api("/engagements/partner-requests", { method: "POST", body: { request_type: type, partner_id: partner.id || null, proposed: data, reason } }); closeModal(); toast("A partnerkérelem jóváhagyásra elküldve."); });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

async function openCompanyCashFlow(year = new Date().getFullYear()) {
    const data = await api(`/finance/company-cash-flow?year=${year}`);
    const monthNames = ["Jan", "Feb", "Már", "Ápr", "Máj", "Jún", "Júl", "Aug", "Szep", "Okt", "Nov", "Dec"];
    const maximum = Math.max(1, ...data.monthly_revenue.map(Number), ...data.monthly_cost.map(Number));
    const chart = monthNames.map((month, index) => `<div class="cash-month"><div class="cash-bars"><span class="cash-revenue" style="height:${Math.max(2, Number(data.monthly_revenue[index]) / maximum * 100)}%" title="Bevétel: ${formatMoney(data.monthly_revenue[index])}"></span><span class="cash-cost" style="height:${Math.max(2, Number(data.monthly_cost[index]) / maximum * 100)}%" title="Költség: ${formatMoney(data.monthly_cost[index])}"></span></div><strong>${month}</strong><small>${formatMoney(data.monthly_net[index])}</small></div>`).join("");
    const monthlyRows = monthNames.map((month, index) => `<tr><td>${month}</td><td>${formatMoney(data.monthly_revenue[index])}</td><td>${formatMoney(data.monthly_external_cost[index])}</td><td>${formatMoney(data.monthly_internal_cost[index])}</td><td class="${Number(data.monthly_net[index]) >= 0 ? "positive" : "negative"}">${formatMoney(data.monthly_net[index])}</td><td>${formatMoney(data.cumulative[index])}</td></tr>`).join("");
    const projectRows = data.projects.length ? data.projects.map((project) => `<tr><td><strong>${escapeHtml(project.project_name)}</strong></td><td>${formatMoney(project.contract_value)}</td><td>${formatMoney(project.annual_revenue)}</td><td>${formatMoney(project.annual_cost)}</td><td class="${Number(project.annual_net) >= 0 ? "positive" : "negative"}">${formatMoney(project.annual_net)}</td></tr>`).join("") : `<tr><td colspan="5">Még nincs projektadat.</td></tr>`;
    showModal("Céges árbevétel és cash-flow", `${year}. évi, minden projektet összesítő nézet`, `<div class="toolbar"><label>Év<select id="cash-flow-year">${Array.from({ length: 15 }, (_, index) => new Date().getFullYear() - 5 + index).map((value) => `<option value="${value}" ${value === Number(year) ? "selected" : ""}>${value}</option>`).join("")}</select></label><a class="secondary-button" href="/api/finance/company-cash-flow/export?year=${year}">Excel export</a></div><div class="kpi-grid"><div class="kpi"><span>Főszerződések</span><strong>${formatMoney(data.contract_total)}</strong></div><div class="kpi green"><span>Éves bevétel</span><strong>${formatMoney(data.revenue_total)}</strong></div><div class="kpi red"><span>Éves költség</span><strong>${formatMoney(data.cost_total)}</strong></div><div class="kpi amber"><span>Éves nettó egyenleg</span><strong>${formatMoney(data.profit_total)}</strong></div></div><section class="cash-chart" aria-label="Havi bevétel és költség diagram">${chart}</section><div class="cash-legend"><span><i class="cash-revenue"></i>Bevétel</span><span><i class="cash-cost"></i>Költség</span></div><div class="workspace-tabs"><button class="active" type="button" data-cash-tab="monthly">Havi bontás</button><button type="button" data-cash-tab="projects">Projektek</button></div><section data-cash-panel="monthly"><div class="table-wrap"><table><thead><tr><th>Hónap</th><th>Bevétel</th><th>Alvállalkozói költség</th><th>Belső ráfordítás</th><th>Nettó</th><th>Göngyölített</th></tr></thead><tbody>${monthlyRows}</tbody></table></div></section><section data-cash-panel="projects" hidden><div class="table-wrap"><table><thead><tr><th>Projekt</th><th>Szerződéses érték</th><th>Éves bevétel</th><th>Éves költség</th><th>Nettó</th></tr></thead><tbody>${projectRows}</tbody></table></div></section>`);
    $("#cash-flow-year").addEventListener("change", (event) => openCompanyCashFlow(Number(event.currentTarget.value)));
    $$('[data-cash-tab]', $("#modal")).forEach((button) => button.addEventListener("click", () => {
        $$('[data-cash-tab]', $("#modal")).forEach((item) => item.classList.toggle("active", item === button));
        $$('[data-cash-panel]', $("#modal")).forEach((panel) => panel.hidden = panel.dataset.cashPanel !== button.dataset.cashTab);
    }));
}

function openProjectCompanyContact(contact = null) {
    const current = contact || { name: "", job_title: "", email: "", phone: "", display_order: 0 };
    showModal(
        contact ? "Céges kapcsolattartó szerkesztése" : "Új céges kapcsolattartó",
        state.project.name,
        `<form id="project-company-contact-form"><div class="form-grid">
            <label class="span-2">Név<input name="name" value="${escapeHtml(current.name)}" maxlength="255" required></label>
            <label>Beosztás / szerepkör<input name="job_title" value="${escapeHtml(current.job_title)}" maxlength="255"></label>
            <label>E-mail<input name="email" type="email" value="${escapeHtml(current.email)}" maxlength="255"></label>
            <label>Telefonszám<input name="phone" value="${escapeHtml(current.phone)}" maxlength="255"></label>
            <label>Sorrend<input name="display_order" type="number" value="${Number(current.display_order || 0)}"></label>
        </div><div class="modal-actions"><button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Mentés</button></div></form>`,
    );
    $("#project-company-contact-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = formDataObject(event.currentTarget);
        data.display_order = Number(data.display_order || 0);
        await api(
            contact
                ? `/settings/${state.project.id}/company-contacts/${contact.id}`
                : `/settings/${state.project.id}/company-contacts`,
            { method: contact ? "PUT" : "POST", body: data },
        );
        closeModal();
        toast("A céges kapcsolattartó mentése sikerült.");
        await renderSettings();
    });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

function openScheduleKey(scheduleKey = null) {
    const current = scheduleKey || { code: "", description: "", start_event: "", end_event: "", note: "", is_active: true };
    const title = scheduleKey ? "Tervezési mérföldkő szerkesztése" : "Új tervezési mérföldkő";
    const body = [
        '<form id="schedule-key-form"><div class="form-grid">',
        '<label>Tervezési mérföldkő kódja<input name="code" value="' + escapeHtml(current.code) + '" maxlength="255" required></label>',
        '<label class="checkbox-label"><input name="is_active" type="checkbox" ' + (current.is_active ? "checked" : "") + '> Aktív</label>',
        '<label class="span-3">Leírás<textarea name="description" rows="3" maxlength="5000">' + escapeHtml(current.description || "") + '</textarea></label>',
        '<label class="span-3">Kezdete<textarea name="start_event" rows="2" maxlength="1000">' + escapeHtml(current.start_event || "") + '</textarea></label>',
        '<label class="span-3">Vége<textarea name="end_event" rows="2" maxlength="1000">' + escapeHtml(current.end_event || "") + '</textarea></label>',
        '<label class="span-3">Megjegyzés<textarea name="note" rows="3" maxlength="5000">' + escapeHtml(current.note || "") + '</textarea></label>',
        '</div><div class="modal-actions"><button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Mentés</button></div></form>',
    ].join("");
    showModal(title, "Globális törzsadat", body);
    $("#schedule-key-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = formDataObject(event.currentTarget);
        data.is_active = event.currentTarget.elements.is_active.checked;
        const path = scheduleKey ? "/settings/schedule-keys/" + scheduleKey.id : "/settings/schedule-keys";
        await api(path, { method: scheduleKey ? "PUT" : "POST", body: data });
        closeModal();
        toast("A tervezési mérföldkő mentése sikerült.");
        await renderSettings();
    });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

async function renderSettings() {
    const view = beginViewRender("settings");
    if (!view) return;
    try {
    const [settings, finance] = await Promise.all([
        api(`/settings/${state.project.id}`),
        api(`/finance/${state.project.id}/summary`).catch(() => null),
    ]);
    if (!viewRenderIsCurrent(view)) return;
    const project = settings.project || state.project;
    const projectWritable = hasPermission("project_write");
    const settingsWritable = hasPermission("discipline_write");
    const calendarWritable = hasPermission("master_data_admin");
    const offerRequestSettings = settings.offer_request_settings || { history: "", task_description: "" };
    const projectProfile = settings.project_profile || {
        directorate: "",
        project_role: "",
        business_agreement: "",
        project_scale: "",
        project_source: "",
        nationally_significant: false,
    };
    const projectFieldState = projectWritable ? "" : "disabled";
    const responsibleCompany = normalizeResponsibleCompany(project.responsible_company);
    const companyContacts = settings.company_contacts || [];
    const rateRows = settings.daily_rates.length ? settings.daily_rates.map((rate) => `<tr><td>${rate.year}</td><td>${formatMoney(rate.daily_rate)} / nap</td><td>${settingsWritable ? `<button class="icon-button" type="button" data-delete-rate="${rate.id}" title="Napidíj törlése" aria-label="Napidíj törlése">×</button>` : ""}</td></tr>`).join("") : `<tr><td colspan="3">Még nincs éves napidíj rögzítve.</td></tr>`;
    const phaseRows = settings.phases.length ? settings.phases.map((phase) => `<li><span>${escapeHtml(phase.phase_name)}</span>${settingsWritable ? `<button class="icon-button" type="button" data-delete-phase="${phase.id}" title="Fázis törlése" aria-label="Fázis törlése">×</button>` : ""}</li>`).join("") : `<li><span>Még nincs projektspecifikus fázis.</span></li>`;
    const disciplineRows = settings.disciplines.length ? settings.disciplines.map((discipline) => `<label class="settings-check"><input type="checkbox" data-discipline-visibility="${discipline.id}" ${discipline.visible ? "checked" : ""} ${settingsWritable ? "" : "disabled"}><span><strong>${escapeHtml(discipline.name)}</strong><small>${escapeHtml(discipline.code || "Nincs kód")}</small></span></label>`).join("") : `<p class="muted">Még nincs szakág a projektben.</p>`;
    const exceptionRows = settings.calendar_exceptions.length ? settings.calendar_exceptions.map((item) => `<tr><td>${formatDate(item.exception_date)}</td><td>${escapeHtml(item.exception_type)}</td><td>${escapeHtml(item.name)}</td><td>${calendarWritable ? `<button class="icon-button" type="button" data-delete-exception="${item.id}" title="Kivétel törlése" aria-label="Kivétel törlése">×</button>` : ""}</td></tr>`).join("") : `<tr><td colspan="4">Nincs naptárkivétel.</td></tr>`;
    const companyContactRows = companyContacts.length
        ? companyContacts.map((contact) => `<tr><td><strong>${escapeHtml(contact.name)}</strong><small>${escapeHtml(contact.job_title || "")}</small></td><td>${escapeHtml(contact.email || "–")}</td><td>${escapeHtml(contact.phone || "–")}</td><td>${projectWritable ? `<div class="table-actions"><button class="icon-button" type="button" data-edit-company-contact="${contact.id}" title="Kapcsolattartó szerkesztése" aria-label="Kapcsolattartó szerkesztése">✎</button><button class="icon-button danger" type="button" data-delete-company-contact="${contact.id}" title="Kapcsolattartó törlése" aria-label="Kapcsolattartó törlése">×</button></div>` : ""}</td></tr>`).join("")
        : '<tr><td colspan="4">Még nincs céges kapcsolattartó rögzítve.</td></tr>';
    const contractSections = settings.contract_sections || [];
    const milestones = settings.milestones || [];
    const scheduleRows = sortScheduleRows(settings.schedule_rows || []);
    const scheduleKeys = settings.schedule_keys || [];
    const scheduleKeysAvailable = Boolean(settings.schedule_keys_available);
    const scheduleKeysError = settings.schedule_keys_error || {};
    const scheduleKeysWritable = hasPermission("master_data_admin");
    const canonicalScheduleKey = (value) => String(value || "").trim().toLocaleLowerCase("hu-HU");
    const knownScheduleKeyCodes = new Set(scheduleKeys.map((item) => canonicalScheduleKey(item.code)));
    const unresolvedLegacyCodes = [...new Set(
        scheduleRows
            .map((row) => String(row.phase_code || "").trim())
            .filter((code) => code && !knownScheduleKeyCodes.has(canonicalScheduleKey(code))),
    )].sort((left, right) => left.localeCompare(right, "hu-HU"));
    const scheduleKeyRows = scheduleKeys.length
        ? scheduleKeys.map((item) => '<tr><td><strong>' + escapeHtml(item.code) + '</strong></td><td>' + escapeHtml(item.description || "–") + '</td><td>' + (item.is_active ? "Aktív" : "Inaktív") + '</td><td>' + (scheduleKeysWritable ? '<button type="button" class="icon-button" data-edit-schedule-key="' + item.id + '" title="Tervezési mérföldkő szerkesztése" aria-label="Tervezési mérföldkő szerkesztése">✎</button>' : "") + '</td></tr>').join("")
        : '<tr><td colspan="4">Még nincs importált tervezési mérföldkő.</td></tr>';
    const unresolvedLegacyCodeRows = unresolvedLegacyCodes.length
        ? unresolvedLegacyCodes.map((code) => '<li><strong>' + escapeHtml(code) + '</strong><small>Kézi ellenőrzés szükséges a tervezési mérföldkő törzsben.</small></li>').join("")
        : '<li><span>Nincs kézi ellenőrzést igénylő régi tervezési mérföldkő kód.</span></li>';
    const originalContractValue = contractSections.reduce((sum, section) => sum + Number(section.original_fee || 0), 0);
    const effectiveContractValue = contractSections.reduce((sum, section) => sum + Number(section.modified_fee || section.original_fee || 0), 0);
    const milestoneRevenue = (finance?.finance_items || []).filter((item) => item.is_revenue).reduce((sum, item) => sum + Number(item.expected_amount || 0), 0);
    const revenueDifference = Math.abs(effectiveContractValue - milestoneRevenue);
    const contractSource = `<div class="settings-contract-source"><div><span>Főszerződés eredeti összege</span><strong>${formatMoney(originalContractValue)}</strong></div><div><span>Aktuális szerződéses keret</span><strong>${formatMoney(effectiveContractValue)}</strong></div><div><span>Pénzügyi mérföldkövekre kiosztva</span><strong class="${revenueDifference >= .01 ? "negative" : "positive"}">${formatMoney(milestoneRevenue)}</strong></div><div><span>Forrás</span><strong>${contractSections.length} pénzügyi fázis · ${milestones.length} pénzügyi mérföldkő</strong></div><button id="open-contract-settings-source" type="button" class="secondary-button">Pénzügyi mérföldkövek</button></div>`;
    const currentYear = new Date().getFullYear();
    const hasCurrentRate = settings.daily_rates.some((rate) => Number(rate.year) === currentYear);
    const hiddenDisciplines = settings.disciplines.filter((discipline) => !discipline.visible).length;
    const unassigned = finance?.allocations?.unassigned?.subcontractors?.length || 0;
    const reconciliation = finance?.reconciliation || { issues: [], error_count: 0, warning_count: 0 };
    const qualityIssues = [
        ...(!hasCurrentRate ? [{ severity: "error", message: `Nincs ${currentYear}. évi napidíj beállítva.` }] : []),
        ...(!contractSections.length ? [{ severity: "error", message: "Nincs főszerződéses szakasz rögzítve az Ütemtervben." }] : []),
        ...(contractSections.length && !milestones.length ? [{ severity: "warning", message: "A főszerződéshez még nincs pénzügyi mérföldkő." }] : []),
        ...(contractSections.length && milestones.length && revenueDifference >= .01 ? [{ severity: "warning", message: `A pénzügyi mérföldkövekre kiosztott bevétel ${formatMoney(revenueDifference)} összeggel eltér a szerződéses kerettől.`, reference: "Pénzügyi mérföldkövek" }] : []),
        ...(unassigned ? [{ severity: "warning", message: `${unassigned} alvállalkozói szerződés nincs belső szakághoz rendelve.` }] : []),
        ...(reconciliation.issues || []),
    ];
    const qualityErrorCount = qualityIssues.filter((issue) => issue.severity === "error").length;
    const qualityWarningCount = qualityIssues.filter((issue) => issue.severity !== "error").length;
    const panels = {
        milestones: renderMilestoneWorkspace(contractSections, milestones, scheduleRows),
        schedule_keys: scheduleKeysAvailable
            ? '<div class="settings-grid"><section class="panel"><div class="panel-header"><div><h2>Tervezési mérföldkő törzs</h2><span>' + scheduleKeys.length + ' tervezési mérföldkő</span></div>' + (scheduleKeysWritable ? '<button id="new-schedule-key" class="primary-button" type="button">Új tervezési mérföldkő</button>' : "") + '</div><div class="table-wrap"><table><thead><tr><th>Tervezési mérföldkő</th><th>Leírás</th><th>Állapot</th><th></th></tr></thead><tbody>' + scheduleKeyRows + '</tbody></table></div></section><section class="panel"><div class="panel-header"><h2>Régi projektkódok ellenőrzése</h2><span>Csak olvasási megfeleltetés</span></div><p class="muted">A megfeleltetés kis- és nagybetűtől, valamint szélső szóközöktől független. A rendszer itt nem írja át a meglévő ütemtervi rekordokat.</p><ul class="settings-list">' + unresolvedLegacyCodeRows + '</ul></section></div>'
            : '<section class="panel"><div class="panel-header"><h2>Tervezési mérföldkő törzs</h2><span>Supabase REST-kapcsolati hiba</span></div><p class="permission-note">' + escapeHtml(scheduleKeysError.message || "A futó backend nem éri el a schedule_keys táblát.") + ' <strong>Hibakód: ' + escapeHtml(scheduleKeysError.code || "HTTP 404") + '</strong></p></section>',
        project: `<section class="panel settings-project project-data-panel"><div class="panel-header"><h2>Adatlap</h2><span>Projektazonosítás és alapinformációk</span></div><div class="panel-body"><form id="settings-project-form" class="project-data-form">
                <section class="project-data-section"><h3>AZONOSÍTÓK</h3><div class="project-data-fields">
                    <label class="project-data-row"><span>Projekt neve</span><input name="name" value="${escapeHtml(project.name)}" required ${projectFieldState}></label>
                    <label class="project-data-row"><span>Munkaszám</span><input name="work_number" value="${escapeHtml(project.work_number || "")}" ${projectFieldState}></label>
                    <label class="project-data-row"><span>Saját státusz</span><input name="status" value="${escapeHtml(project.status || "Aktív")}" required ${projectFieldState}></label>
                    <label class="project-data-row project-data-row-textarea"><span>Szerződés tárgya</span><textarea name="contract_subject" rows="4" ${projectFieldState}>${escapeHtml(project.contract_subject || "")}</textarea></label>
                </div></section>
                <section class="project-data-section"><h3>PARTNEREK</h3><div class="project-data-fields">
                    <label class="project-data-row"><span>Megbízó</span><input name="main_customer" value="${escapeHtml(project.main_customer || project.customer || "")}" ${projectFieldState}></label>
                    <label class="project-data-row"><span>Vállalkozó</span><span><select name="responsible_company" ${projectFieldState}>${responsibleCompanyOptions(responsibleCompany)}</select>${responsibleCompany && !RESPONSIBLE_COMPANIES.includes(responsibleCompany) ? `<small class="field-help">Korábbi érték megőrizve: ${escapeHtml(responsibleCompany)}. A cseréhez válassz a listából.</small>` : ""}</span></label>
                    <label class="project-data-row"><span>Igazgatóság</span><input name="directorate" value="${escapeHtml(projectProfile.directorate || "")}" maxlength="255" ${projectFieldState}></label>
                    <label class="project-data-row"><span>Szerepkör</span><input name="project_role" value="${escapeHtml(projectProfile.project_role || "")}" maxlength="255" ${projectFieldState}></label>
                    <label class="project-data-row project-data-row-textarea"><span>Üzleti megállapodás</span><textarea name="business_agreement" rows="4" maxlength="5000" ${projectFieldState}>${escapeHtml(projectProfile.business_agreement || "")}</textarea></label>
                </div></section>
                <section class="project-data-section"><h3>ALAPINFORMÁCIÓK</h3><div class="project-data-fields">
                    <label class="project-data-row"><span>Projekt lépték</span><select name="project_scale" ${projectFieldState}>${selectOptions(PROJECT_SCALES, projectProfile.project_scale)}</select></label>
                    <label class="project-data-row"><span>Projekt forrás</span><select name="project_source" ${projectFieldState}>${selectOptions(PROJECT_SOURCES, projectProfile.project_source)}</select></label>
                    <label class="project-data-row project-data-row-checkbox"><span>Nemzetgazdasági szempontból kiemelt jelentőségű</span><span class="checkbox-control"><input name="nationally_significant" type="checkbox" ${projectProfile.nationally_significant ? "checked" : ""} ${projectFieldState}><b>Igen</b></span></label>
                </div></section>
                ${projectWritable ? '<div class="project-data-actions"><button class="primary-button" type="submit">Adatlap mentése</button></div>' : ""}
            </form></div></section>
            <section class="panel settings-project"><div class="panel-header"><h2>Ajánlatkérő alapadatai</h2><span>Új dokumentumok alapértelmezett szövege</span></div><div class="panel-body"><form id="offer-request-settings-form" class="form-grid"><label class="span-3">Előzmények<textarea name="history" rows="5" maxlength="5000" ${projectWritable ? "" : "disabled"}>${escapeHtml(offerRequestSettings.history || "")}</textarea><small class="field-help">Új ajánlatkérő összeállításakor automatikusan betöltődik, de a dokumentumban külön módosítható.</small></label><label class="span-3">Tervezési feladat részletezése<textarea name="task_description" rows="7" maxlength="5000" ${projectWritable ? "" : "disabled"}>${escapeHtml(offerRequestSettings.task_description || "")}</textarea><small class="field-help">A projekthez tartozó több ajánlat közös kiinduló műszaki leírása.</small></label>${projectWritable ? '<div class="modal-actions span-3"><button class="primary-button" type="submit">Ajánlatkérő alapadatok mentése</button></div>' : ""}</form></div></section>
            <section class="panel settings-project"><div class="panel-header"><div><h2>Céges kapcsolattartók</h2><p>Az ajánlatkérőben legördülő listából választhatók.</p></div>${projectWritable ? '<button id="new-company-contact" class="primary-button" type="button">Új kapcsolattartó</button>' : ""}</div><div class="table-wrap"><table><thead><tr><th>Név</th><th>E-mail</th><th>Telefon</th><th></th></tr></thead><tbody>${companyContactRows}</tbody></table></div></section>`,
        structure: `<div class="settings-grid"><section class="panel"><div class="panel-header"><h2>Projektfázisok</h2><span>${settings.phases.length} fázis</span></div>${settingsWritable ? '<form id="phase-form" class="inline-editor"><label>Új fázis neve<input name="phase_name" required maxlength="255"></label><label>Sorrend<input name="sort_order" type="number" value="0"></label><button class="primary-button" type="submit">Hozzáadás</button></form>' : ""}<ul class="settings-list">${phaseRows}</ul></section><section class="panel"><div class="panel-header"><h2>Szakágak és láthatóság</h2><span>${hiddenDisciplines} rejtett</span></div>${settingsWritable ? '<form id="discipline-form" class="inline-editor"><label>Szakág neve<input name="name" required maxlength="255"></label><label>Kód<input name="code" maxlength="40"></label><button class="primary-button" type="submit">Szakág felvétele</button></form>' : ""}<div class="settings-check-grid">${disciplineRows}</div></section></div>`,
        finance: `<div class="settings-grid"><section class="panel settings-project"><div class="panel-header"><h2>Főszerződés pénzügyi alapja</h2><span>Ütemtervből és mérföldkövekből</span></div>${renderProjectContractBase()}${contractSource}</section><section class="panel settings-project"><div class="panel-header"><h2>Éves napidíjak</h2><span>Belső költség és prognózis</span></div>${settingsWritable ? '<form id="daily-rate-form" class="inline-editor"><label>Év<input name="year" type="number" min="1900" max="2200" required></label><label>Napidíj (Ft)<input name="daily_rate" type="number" min="0" step="0.01" required></label><button class="primary-button" type="submit">Rögzítés</button></form>' : ""}<div class="table-wrap"><table><thead><tr><th>Év</th><th>Napidíj</th><th></th></tr></thead><tbody>${rateRows}</tbody></table></div></section></div>`,
        calendar: `<section class="panel settings-calendar"><div class="panel-header"><h2>Naptárkivételek</h2><span>Munkanap- és pihenőnap-kezelés</span></div>${calendarWritable ? '<form id="calendar-exception-form" class="inline-editor"><label>Dátum<input name="exception_date" type="date" required></label><label>Típus<select name="exception_type"><option>Munkanap</option><option>Munkaszüneti nap</option><option selected>Pihenőnap</option></select></label><label>Megnevezés<input name="name" maxlength="255"></label><button class="primary-button" type="submit">Rögzítés</button></form>' : '<p class="permission-note">A globális naptár módosításához adminisztrátori jogosultság szükséges.</p>'}<div class="table-wrap"><table><thead><tr><th>Dátum</th><th>Típus</th><th>Megnevezés</th><th></th></tr></thead><tbody>${exceptionRows}</tbody></table></div></section>`,
        quality: `<div class="settings-quality-kpis"><div><span>Aktív szakág</span><strong>${settings.disciplines.length - hiddenDisciplines}</strong></div><div><span>Szerződéses mérföldkő</span><strong>${milestones.length}</strong></div><div class="${hasCurrentRate ? "ok" : "error"}"><span>${currentYear}. évi napidíj</span><strong>${hasCurrentRate ? "Rendben" : "Hiányzik"}</strong></div><div class="${qualityIssues.length ? "warning" : "ok"}"><span>Adatminőségi tétel</span><strong>${qualityIssues.length}</strong></div></div><section class="panel"><div class="panel-header"><h2>Adatkapcsolati ellenőrzés</h2><span>${qualityErrorCount} hiba · ${qualityWarningCount} figyelmeztetés</span></div><div class="quality-list">${qualityIssues.length ? qualityIssues.map((issue) => `<div class="quality-item ${issue.severity || "warning"}"><i>${issue.severity === "error" ? "!" : "i"}</i><span><strong>${escapeHtml(issue.message)}</strong><small>${escapeHtml(issue.reference || "Projektbeállítás")}</small></span></div>`).join("") : '<div class="quality-empty"><strong>Az ellenőrzés nem talált hibát.</strong><span>A pénzügyi források és projektbeállítások összhangban vannak.</span></div>'}</div></section>`,
    };
    $("#content").innerHTML = `<div class="section-heading"><div><h2 class="sr-only">Adatok</h2><p>Projekt, struktúra, pénzügy és munkanaptár</p></div><span>${qualityIssues.length ? `${qualityIssues.length} ellenőrizendő tétel` : "Konfiguráció rendben"}</span></div><div class="workspace-tabs settings-tabs"><button data-settings-view="project" class="${state.settingsView === "project" ? "active" : ""}" type="button">Adatlap</button><button data-settings-view="structure" class="${state.settingsView === "structure" ? "active" : ""}" type="button">Szakágak / fázisok</button><button data-settings-view="finance" class="${state.settingsView === "finance" ? "active" : ""}" type="button">Napidíjak</button><button data-settings-view="calendar" class="${state.settingsView === "calendar" ? "active" : ""}" type="button">Munkanaptár</button><button data-settings-view="quality" class="${state.settingsView === "quality" ? "active" : ""}" type="button">Adatminőség <b>${qualityIssues.length}</b></button></div><div class="settings-workspace">${Object.entries(panels).map(([key, panel]) => `<div data-settings-panel="${key}" ${state.settingsView === key ? "" : "hidden"}>${panel}</div>`).join("")}</div>`;
    const projectSettingsTab = $('[data-settings-view="project"]');
    projectSettingsTab.insertAdjacentHTML(
        "afterend",
        '<button data-settings-view="milestones" class="' + (state.settingsView === "milestones" ? "active" : "") + '" type="button">Pénzügyi mérföldkövek</button>'
        + '<button data-settings-view="schedule_keys" class="' + (state.settingsView === "schedule_keys" ? "active" : "") + '" type="button">Tervezési mérföldkövek</button>',
    );
    $('[data-settings-view="structure"]').textContent = "Szakágak / fázisok";
    $$('[data-settings-view]').forEach((button) => button.addEventListener("click", () => { state.settingsView = button.dataset.settingsView; $$('[data-settings-view]').forEach((item) => item.classList.toggle("active", item === button)); $$('[data-settings-panel]').forEach((panel) => { panel.hidden = panel.dataset.settingsPanel !== state.settingsView; }); }));

    $("#settings-project-form")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = formDataObject(event.currentTarget);
        const projectData = {
            name: data.name,
            work_number: data.work_number,
            status: data.status,
            contract_subject: valueOrNull(data.contract_subject),
            main_customer: data.main_customer,
            responsible_company: normalizeResponsibleCompany(data.responsible_company) || responsibleCompany,
        };
        const profileData = {
            directorate: data.directorate || "",
            project_role: data.project_role || "",
            business_agreement: data.business_agreement || "",
            project_scale: data.project_scale || "",
            project_source: data.project_source || "",
            nationally_significant: event.currentTarget.elements.nationally_significant.checked,
        };
        state.project = await api(`/projects/${state.project.id}`, { method: "PATCH", body: projectData });
        await api(`/settings/${state.project.id}/project-profile`, { method: "PUT", body: profileData });
        $("#active-project-name").textContent = state.project.name;
        toast("Az adatlap mentése sikerült.");
        await renderSettings();
    });
    $("#offer-request-settings-form")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = formDataObject(event.currentTarget);
        await api(`/settings/${state.project.id}/offer-request`, { method: "PUT", body: data });
        toast("Az ajánlatkérő alapadatai mentve.");
        await renderSettings();
    });
    $("#new-company-contact")?.addEventListener("click", () => openProjectCompanyContact());
    $$("[data-edit-company-contact]").forEach((button) => button.addEventListener("click", () => openProjectCompanyContact(companyContacts.find((contact) => Number(contact.id) === Number(button.dataset.editCompanyContact)))));
    $$("[data-delete-company-contact]").forEach((button) => button.addEventListener("click", async () => {
        const contact = companyContacts.find((item) => Number(item.id) === Number(button.dataset.deleteCompanyContact));
        if (!contact || !confirm(`Biztosan törlöd ezt a kapcsolattartót: ${contact.name}?`)) return;
        await api(`/settings/${state.project.id}/company-contacts/${contact.id}`, { method: "DELETE" });
        toast("A céges kapcsolattartó törölve.");
        await renderSettings();
    }));
    $("#open-contract-settings-source")?.addEventListener("click", async () => { state.settingsView = "milestones"; await renderSettings(); });
    if (state.settingsView === "milestones") wireMilestoneWorkspace(contractSections, milestones, scheduleRows);
    $("#new-schedule-key")?.addEventListener("click", () => openScheduleKey());
    $$("[data-edit-schedule-key]").forEach((button) => button.addEventListener("click", () => openScheduleKey(scheduleKeys.find((item) => Number(item.id) === Number(button.dataset.editScheduleKey)))));
    $("#daily-rate-form")?.addEventListener("submit", async (event) => { event.preventDefault(); const data = formDataObject(event.currentTarget); await api(`/settings/${state.project.id}/daily-rates`, { method: "PUT", body: { year: Number(data.year), daily_rate: Number(data.daily_rate) } }); toast("A napidíj mentése sikerült."); await renderSettings(); });
    $$('[data-delete-rate]').forEach((button) => button.addEventListener("click", async () => { if (!confirm("Biztosan törlöd ezt a napidíjat?")) return; await api(`/settings/${state.project.id}/daily-rates/${button.dataset.deleteRate}`, { method: "DELETE" }); await renderSettings(); }));
    $("#phase-form")?.addEventListener("submit", async (event) => { event.preventDefault(); const data = formDataObject(event.currentTarget); await api(`/settings/${state.project.id}/phases`, { method: "POST", body: { phase_name: data.phase_name, sort_order: Number(data.sort_order) } }); toast("A projektfázis létrejött."); await renderSettings(); });
    $$('[data-delete-phase]').forEach((button) => button.addEventListener("click", async () => { if (!confirm("Biztosan törlöd ezt a projektfázist? A korábbi sorok szöveges fázisadata megmarad.")) return; await api(`/settings/${state.project.id}/phases/${button.dataset.deletePhase}`, { method: "DELETE" }); await renderSettings(); }));
    $("#discipline-form")?.addEventListener("submit", async (event) => { event.preventDefault(); const data = formDataObject(event.currentTarget); await api("/disciplines", { method: "POST", body: { project_id: state.project.id, name: data.name, code: data.code, visible: true, sort_order: settings.disciplines.length } }); toast("A szakág létrejött."); await renderSettings(); });
    $$('[data-discipline-visibility]').forEach((input) => input.addEventListener("change", async () => { await api(`/settings/${state.project.id}/disciplines/${input.dataset.disciplineVisibility}`, { method: "PATCH", body: { visible: input.checked } }); toast("A szakági láthatóság frissült."); }));
    $("#calendar-exception-form")?.addEventListener("submit", async (event) => { event.preventDefault(); const data = formDataObject(event.currentTarget); await api("/settings/calendar-exceptions", { method: "POST", body: data }); toast("A naptárkivétel mentése sikerült."); await renderSettings(); });
    $$('[data-delete-exception]').forEach((button) => button.addEventListener("click", async () => { if (!confirm("Biztosan törlöd ezt a naptárkivételt?")) return; await api(`/settings/calendar-exceptions/${button.dataset.deleteException}`, { method: "DELETE" }); await renderSettings(); }));
    } catch (error) {
        if (viewRenderIsCurrent(view)) throw error;
    }
}

async function renderAdmin() {
    const view = beginViewRender("admin");
    if (!view) return;
    try {
    const [profiles, pending, returned, clock] = await Promise.all([api("/admin/profiles"), api("/engagements/partner-requests?status=pending"), api("/engagements/partner-requests?status=changes_requested"), api("/admin/application-clock")]);
    if (!viewRenderIsCurrent(view)) return;
    const requests = [...pending, ...returned];
    $("#content").innerHTML = `<div class="kpi-grid"><div class="kpi"><span>Felhasználó</span><strong>${profiles.length}</strong></div><div class="kpi amber"><span>Partnerkérelem</span><strong>${requests.length}</strong><small>döntésre vagy javításra vár</small></div><div class="kpi green"><span>Rendszerdátum</span><strong>${formatDate(clock.system_date)}</strong></div><div class="kpi violet"><span>Alkalmazás dátuma</span><strong>${formatDate(clock.application_date)}</strong><small>${clock.offset_days} nap eltérés</small></div></div><div class="two-columns"><section class="panel"><div class="panel-header"><h2>Jóváhagyásra váró partnerkérelmek</h2><span>Dupla kattintással megnyitható</span></div><div class="compact-list">${requests.length ? requests.map((r) => `<button type="button" data-request-id="${r.id}"><strong>${escapeHtml(r.proposed_data?.name || "Névtelen kérelem")}</strong><span>${({ create: "Új partner", update: "Módosítás", delete: "Törlés/inaktiválás" })[r.request_type] || r.request_type}</span><small>${r.status === "changes_requested" ? "Javításra visszaküldve" : formatDate(r.created_at)}</small></button>`).join("") : empty("Nincs jóváhagyásra váró partnerkérelem.")}</div></section><section class="panel"><div class="panel-header"><h2>Felhasználók</h2></div><div class="compact-list">${profiles.map((p) => `<div class="profile-row"><span><strong>${escapeHtml(p.display_name || p.email || p.id)}</strong><small>${roleLabel(p.role)}</small></span><b>${p.active ? "Aktív" : "Inaktív"}</b></div>`).join("")}</div></section></div><section class="panel"><div class="panel-header"><h2>Értesítési tesztidő</h2><span>A valós rendszerdátum nem módosul</span></div><div class="panel-body"><form id="application-clock-form" class="clock-form"><label>Napeltolás<input name="offset_days" type="number" min="-3650" max="3650" value="${clock.offset_days}"></label><label class="checkbox-label"><input name="force_first_of_month" type="checkbox" ${clock.force_first_of_month ? "checked" : ""}> Mindig a hónap első napját használja</label><button class="primary-button" type="submit">Tesztidő alkalmazása</button></form></div></section>`;
    $$("[data-request-id]").forEach((row) => row.addEventListener("dblclick", () => openApproval(requests.find((r) => r.id === Number(row.dataset.requestId)))));
    $("#application-clock-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; const updatedClock = await api("/admin/application-clock", { method: "PUT", body: { offset_days: Number(form.elements.offset_days.value), force_first_of_month: form.elements.force_first_of_month.checked } }); state.applicationDate = updatedClock.application_date; toast("Az alkalmazás tesztideje frissült."); await renderAdmin(); await refreshNotifications(); });
    } catch (error) {
        if (viewRenderIsCurrent(view)) throw error;
    }
}

function openApproval(request) {
    const proposed = request.proposed_data || {};
    showModal("Partnerkérelem elbírálása", `${request.id}. kérelem · ${formatDate(request.created_at)}`, `<div class="approval-type">${({ create: "Új partner felvétele", update: "Partneradat módosítása", delete: "Partner inaktiválása" })[request.request_type]}</div>${request.old_data && Object.keys(request.old_data).length ? `<section class="subpanel"><h3>Korábbi értékek</h3><div class="diff-grid">${Object.entries(request.old_data).filter(([key]) => ["name","address","contact_person","email","phone","org_type"].includes(key)).map(([key, value]) => `<div><small>${escapeHtml(key)}</small><span>${escapeHtml(value)}</span></div>`).join("")}</div></section>` : ""}<form id="approval-form"><div class="form-grid"><label class="span-2">Partner neve<input name="name" value="${escapeHtml(proposed.name)}" required></label><label>Szervezettípus<input name="org_type" value="${escapeHtml(proposed.org_type)}"></label><label class="span-2">Cím<input name="address" value="${escapeHtml(proposed.address)}"></label><label>Ügyintéző<input name="contact_person" value="${escapeHtml(proposed.contact_person)}"></label><label>E-mail<input name="email" value="${escapeHtml(proposed.email)}"></label><label>Telefonszám<input name="phone" value="${escapeHtml(proposed.phone)}"></label><label class="span-3">Adminisztrátori megjegyzés<textarea name="comment" rows="3"></textarea></label></div><div class="modal-actions"><button type="button" class="danger-button" data-decision="rejected">Elutasítás</button><button type="button" class="secondary-button" data-decision="changes_requested">Visszaküldés javításra</button><button type="button" class="primary-button" data-decision="approved">Jóváhagyás</button></div></form>`);
    $$("[data-decision]", $("#modal")).forEach((button) => button.addEventListener("click", async () => { const data = formDataObject($("#approval-form")); const comment = data.comment; delete data.comment; await api(`/engagements/partner-requests/${request.id}/decision`, { method: "POST", body: { decision: button.dataset.decision, comment, proposed: data } }); closeModal(); toast("Az adminisztrátori döntés rögzítve."); await renderAdmin(); }));
}

async function legacyRefreshNotifications() {
    try { state.notifications = await api("/notifications"); $("#notification-count").textContent = state.notifications.length; } catch { state.notifications = []; $("#notification-count").textContent = "0"; }
}

async function legacyOpenNotifications() {
    await refreshNotifications();
    showModal("Értesítések", `${state.notifications.length} aktuális értesítés`, state.notifications.length ? `<div class="notification-list">${state.notifications.map((n, index) => `<article data-notification-index="${index}"><header><div><strong>${escapeHtml(n.subject)}</strong><span>${escapeHtml(n.project_name)}</span></div><button class="notification-close" type="button" data-mark-read title="Értesítés bezárása és olvasottnak jelölése" aria-label="Értesítés bezárása és olvasottnak jelölése">×</button></header><p>${escapeHtml(n.message)}</p><div><label>Újra jelezzen <select data-snooze><option value="1">1 nap múlva</option><option value="3">3 nap múlva</option><option value="7" selected>7 nap múlva</option><option value="14">14 nap múlva</option><option value="30">30 nap múlva</option></select></label><button class="secondary-button" type="button" data-dismiss="snooze">Emlékeztetés később</button><button class="danger-button" type="button" data-dismiss="forever">Ne értesítsen többet</button></div></article>`).join("")}</div>` : empty("Jelenleg nincs új értesítés. Az ablak ettől függetlenül bármikor megnyitható.") );
    $$("[data-mark-read]", $("#modal")).forEach((button) => button.addEventListener("click", async (event) => { event.stopPropagation(); const article = button.closest("article"); const notification = state.notifications[Number(article.dataset.notificationIndex)]; await api(`/notifications/${encodeURIComponent(notification.alert_key)}/read`, { method: "POST" }); toast("Az értesítés olvasottként bezárva."); await openNotifications(); }));
    $$("[data-dismiss]", $("#modal")).forEach((button) => button.addEventListener("click", async () => { const article = button.closest("article"); const notification = state.notifications[Number(article.dataset.notificationIndex)]; const mode = button.dataset.dismiss; const days = mode === "snooze" ? Number($("[data-snooze]", article).value) : null; await api("/notifications/dismiss", { method: "POST", body: { alert_key: notification.alert_key, mode, days } }); toast(mode === "forever" ? "Az értesítés végleg kikapcsolva." : `Az értesítés ${days} nap múlva ismét megjelenik.`); await openNotifications(); }));
    $$("[data-notification-index]", $("#modal")).forEach((article) => article.addEventListener("dblclick", async (event) => { if (event.target.closest("button,select,label")) return; const notification = state.notifications[Number(article.dataset.notificationIndex)]; closeModal(); if (notification.alert_type === "eng") { const assignmentId = Number(String(notification.alert_key).split(":")[1]); if (notification.project_id && (!state.project || state.project.id !== Number(notification.project_id))) await openProject(Number(notification.project_id)); await selectModule("engagements"); if (assignmentId) await openAssignment(assignmentId); } else if (notification.alert_type === "sub") { if (notification.project_id && (!state.project || state.project.id !== Number(notification.project_id))) await openProject(Number(notification.project_id)); await selectModule("subcontractors"); } else { await selectModule("disciplines"); } }));
}

async function refreshNotifications() {
    const [notifications, tasks, dateInfo] = await Promise.all([
        api("/notifications").catch(() => []),
        api("/notifications/tasks/today").catch(() => []),
        api("/notifications/date").catch(() => null),
    ]);
    state.notifications = Array.isArray(notifications) ? notifications : [];
    state.todayTasks = Array.isArray(tasks) ? tasks : [];
    state.applicationDate = dateInfo?.application_date || state.applicationDate || new Date().toISOString().slice(0, 10);
    const dateDisplay = $("#current-application-date");
    if (dateDisplay) {
        dateDisplay.dateTime = state.applicationDate;
        dateDisplay.textContent = `Ma: ${formatDate(state.applicationDate)}`;
        dateDisplay.classList.toggle("test-date", Boolean(dateInfo?.is_test_date));
        dateDisplay.title = dateInfo?.is_test_date
            ? "Adminisztrátori tesztdátum ezen a profilon"
            : "Az alkalmazás aktuális dátuma";
    }
    const notificationCount = state.notifications.length;
    const todayCount = state.todayTasks.length;
    $("#notification-count").textContent = notificationCount;
    $("#today-tasks-count").textContent = todayCount;
    $("#today-tasks-button").setAttribute("aria-label", todayCount
        ? `Mai teendők, ${todayCount} nyitott tétel`
        : "Mai teendők");
    $("#notification-button").classList.toggle("has-pending", notificationCount > 0);
    $("#notification-button").setAttribute("aria-label", notificationCount
        ? `Értesítések, ${notificationCount} nyitott tétel`
        : "Értesítések");
}

function priorityOptions(current = 2) {
    return [[1, "Sürgős"], [2, "Magas"], [3, "Normál"], [4, "Alacsony"]]
        .map(([value, label]) => `<option value="${value}" ${Number(current) === value ? "selected" : ""}>${label}</option>`)
        .join("");
}

function priorityLabel(priority) {
    return ({ 1: "Sürgős", 2: "Magas", 3: "Normál", 4: "Alacsony" })[Number(priority)] || "Magas";
}

function priorityPicker(name, current = 2, dataAttribute = "") {
    const priority = Number(current) || 2;
    return `<label class="priority-picker priority-${priority}">
        <span><i aria-hidden="true"></i>Prioritás</span>
        <select ${name ? `name="${name}"` : ""} ${dataAttribute}>${priorityOptions(priority)}</select>
    </label>`;
}

function updatePriorityPicker(select) {
    const picker = select?.closest(".priority-picker");
    if (!picker) return;
    picker.classList.remove("priority-1", "priority-2", "priority-3", "priority-4");
    picker.classList.add(`priority-${Number(select.value) || 2}`);
}

function localDateTimeValue(minutesFromNow = 60) {
    const value = new Date(Date.now() + minutesFromNow * 60000);
    return new Date(value.getTime() - value.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function notificationCard(notification, index) {
    return `<article class="priority-${Number(notification.priority) || 2}" data-notification-index="${index}">
        <header><div><strong>${escapeHtml(notification.subject || "Teendő")}</strong><span>${escapeHtml(notification.project_name || "Általános")}</span></div><span class="notification-priority">${escapeHtml(priorityLabel(notification.priority))}</span></header>
        <p>${escapeHtml(notification.message)}</p>
        <div class="notification-controls">
            ${priorityPicker("", notification.priority, "data-notification-priority")}
            <button class="secondary-button" type="button" data-notification-action="skip_15">Szünet 15 percre</button>
            <button class="secondary-button" type="button" data-notification-action="defer_24">Halasztás 24 órára</button>
            <label>Egyedi emlékeztetés<input data-custom-reminder type="datetime-local" min="${localDateTimeValue(1)}" value="${localDateTimeValue(60)}"></label>
            <button class="secondary-button" type="button" data-notification-action="custom">Beállítás</button>
            <button class="danger-button" type="button" data-notification-action="forever">Ne jelezzen többet</button>
            ${notification.alert_type === "task_overdue" ? "" : '<button class="secondary-button" type="button" data-move-notification>Áthelyezés a napi teendőkhöz</button>'}
            ${notification.alert_type === "task_overdue" ? '<button class="primary-button" type="button" data-complete-overdue-task>Készre jelölés</button>' : ""}
            <button class="primary-button" type="button" data-jump-notification>Ugrás a feladathoz</button>
        </div>
    </article>`;
}

async function applyNotificationAction(notification, action, article) {
    const body = { alert_key: notification.alert_key, action };
    if (action === "custom") {
        const value = $("[data-custom-reminder]", article).value;
        if (!value) throw new Error("Add meg az értesítés időpontját.");
        body.remind_at = new Date(value).toISOString();
    }
    if (action === "priority") body.priority = Number($("[data-notification-priority]", article).value);
    await api("/notifications/action", { method: "POST", body });
}

async function jumpToNotification(notification) {
    closeModal();
    const projectId = Number(notification.project_id || 0);
    if (projectId && (!state.project || state.project.id !== projectId)) await openProject(projectId);
    const module = notification.target_module || ({ eng: "engagements", sub: "subcontractors", monthly: "disciplines" })[notification.alert_type] || "settings";
    if (!projectId && module !== "admin") return loadProjects();
    if (module === "disciplines" && notification.target_id && projectId) {
        const disciplines = await api(`/disciplines/${projectId}`).catch(() => []);
        const discipline = disciplines.find((item) => Number(item.id) === Number(notification.target_id));
        if (discipline) state.activeDiscipline = discipline.name;
    }
    await selectModule(module);
    if (module === "engagements" && notification.target_id) await openAssignment(Number(notification.target_id));
}

function wireNotificationCards(reopen) {
    $$('[data-notification-index]', $("#modal")).forEach((article) => {
        const notification = state.notifications[Number(article.dataset.notificationIndex)];
        $("[data-notification-priority]", article)?.addEventListener("change", async () => {
            try {
                updatePriorityPicker($("[data-notification-priority]", article));
                await applyNotificationAction(notification, "priority", article);
                toast("A prioritás frissült.");
                await reopen();
            } catch (error) { toast(error.message, true); }
        });
        $$('[data-notification-action]', article).forEach((button) => button.addEventListener("click", async () => {
            try {
                await applyNotificationAction(notification, button.dataset.notificationAction, article);
                const messages = { skip_15: "15 perc múlva újra jelezzük.", defer_24: "Az értesítést 24 órára elhalasztottuk.", custom: "Az egyedi emlékeztetés beállítva.", forever: "Az értesítés lezárva." };
                toast(messages[button.dataset.notificationAction]);
                await reopen();
            } catch (error) { toast(error.message, true); }
        }));
        $("[data-move-notification]", article)?.addEventListener("click", async () => {
            try {
                await api("/notifications/tasks/from-notification", { method: "POST", body: {
                    alert_key: notification.alert_key,
                    priority: Number($("[data-notification-priority]", article).value),
                } });
                toast("Az értesítés átkerült a mai teendők közé.");
                await reopen();
            } catch (error) { toast(error.message, true); }
        });
        $("[data-complete-overdue-task]", article)?.addEventListener("click", async () => {
            try {
                await api(`/notifications/tasks/${Number(notification.target_id)}`, { method: "PATCH", body: { completed: true } });
                toast("A lejárt teendő elkészültként lezárva.");
                await reopen();
            } catch (error) { toast(error.message, true); }
        });
        $("[data-jump-notification]", article)?.addEventListener("click", () => jumpToNotification(notification));
        article.addEventListener("dblclick", (event) => {
            if (!event.target.closest("button,input,select,label")) jumpToNotification(notification);
        });
    });
}

async function openNotifications() {
    await refreshNotifications();
    showModal("Értesítések", `${state.notifications.length} aktuális értesítés`, state.notifications.length
        ? `<div class="notification-list">${state.notifications.map(notificationCard).join("")}</div>`
        : empty("Jelenleg nincs új értesítés."));
    wireNotificationCards(openNotifications);
}

function todayTaskCard(task) {
    const project = state.projects.find((item) => item.id === Number(task.project_id));
    return `<article class="today-task priority-${Number(task.priority) || 2}" data-today-task-id="${task.id}">
        <div><strong>${escapeHtml(task.title)}</strong><span>${escapeHtml(project?.name || "Általános")}${task.due_time ? ` · ${escapeHtml(String(task.due_time).slice(0, 5))}` : ""}</span>${task.details ? `<p>${escapeHtml(task.details)}</p>` : ""}</div>
        ${priorityPicker("", task.priority, "data-task-priority")}
        <button class="secondary-button" type="button" data-jump-task>Ugrás a feladathoz</button>
        <button class="primary-button" type="button" data-complete-task>Kész</button>
        <button class="danger-button" type="button" data-delete-task>Törlés</button>
    </article>`;
}

function taskHistoryCard(task) {
    const project = state.projects.find((item) => item.id === Number(task.project_id));
    const completed = Boolean(task.completed_at);
    return `<article class="task-history-card priority-${Number(task.priority) || 2} ${completed ? "completed" : "overdue"}">
        <div>
            <strong>${escapeHtml(task.title)}</strong>
            <span>${formatDate(task.due_date)} · ${escapeHtml(project?.name || "Általános")}${task.due_time ? ` · ${escapeHtml(String(task.due_time).slice(0, 5))}` : ""}</span>
            ${task.details ? `<p>${escapeHtml(task.details)}</p>` : ""}
        </div>
        <span class="task-history-status">${completed ? `Kész · ${formatDate(task.completed_at)}` : "Lejárt, nincs kész"}</span>
    </article>`;
}

async function jumpToTodayTask(task) {
    closeModal();
    const projectId = Number(task.project_id || 0);
    if (!projectId) return loadProjects();
    if (!state.project || state.project.id !== projectId) await openProject(projectId);
    await selectModule(task.target_module || "settings");
}

async function openTodayTasks() {
    await refreshNotifications();
    state.taskHistory = await api("/notifications/tasks/history").catch(() => []);
    const today = state.applicationDate || new Date().toISOString().slice(0, 10);
    const currentTaskIds = new Set(state.todayTasks.map((task) => Number(task.id)));
    const historyItems = state.taskHistory.filter((task) => !currentTaskIds.has(Number(task.id)));
    const projectOptions = state.projects.map((project) => `<option value="${project.id}" ${state.project?.id === project.id ? "selected" : ""}>${escapeHtml(project.work_number ? `${project.work_number} · ${project.name}` : project.name)}</option>`).join("");
    showModal("Mai teendők", `${formatDate(today)} · ${state.todayTasks.length} nyitott tétel`, `
        <div class="today-tasks-toolbar">
            <form id="today-task-form">
                <label>Teendő<input name="title" maxlength="255" required></label>
                <label>Dátum<input name="due_date" type="date" value="${escapeHtml(today)}" required></label>
                <label>Időpont<input name="due_time" type="time"></label>
                ${priorityPicker("priority", 2)}
                <label>Projekt<select name="project_id"><option value="">Általános</option>${projectOptions}</select></label>
                <label>Cél<select name="target_module"><option value="">Projekt adatlap</option><option value="disciplines">Szakágak</option><option value="schedule">Ütemterv</option><option value="subcontractors">Alvállalkozók</option><option value="finance">Pénzügy</option><option value="engagements">Engedélyek</option></select></label>
                <label class="today-task-details">Részletek<input name="details" maxlength="5000"></label>
                <button class="primary-button" type="submit">Teendő létrehozása</button>
            </form>
        </div>
        <section class="today-task-list"><h3>Mai teendők</h3>${state.todayTasks.length ? state.todayTasks.map(todayTaskCard).join("") : empty("Nincs mára rögzített teendő.")}</section>
        <details class="task-history" open>
            <summary>Korábbi teendők · 31 nap <span>${historyItems.length} tétel</span></summary>
            <div class="task-history-list">${historyItems.length ? historyItems.map(taskHistoryCard).join("") : empty("Az elmúlt 31 napban nincs korábbi teendő.")}</div>
        </details>`);
    $("#today-task-form [name='priority']")?.addEventListener("change", (event) => updatePriorityPicker(event.target));
    $("#today-task-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = formDataObject(event.currentTarget);
        try {
            await api("/notifications/tasks", { method: "POST", body: {
                title: data.title,
                details: data.details || "",
                due_date: data.due_date,
                due_time: data.due_time || null,
                priority: Number(data.priority),
                project_id: data.project_id ? Number(data.project_id) : null,
                target_module: data.project_id ? (data.target_module || "settings") : null,
            } });
            toast("A teendő létrejött.");
            await openTodayTasks();
        } catch (error) { toast(error.message, true); }
    });
    $$('[data-today-task-id]', $("#modal")).forEach((article) => {
        const task = state.todayTasks.find((item) => item.id === Number(article.dataset.todayTaskId));
        $("[data-task-priority]", article).addEventListener("change", async (event) => {
            updatePriorityPicker(event.target);
            await api(`/notifications/tasks/${task.id}`, { method: "PATCH", body: { priority: Number(event.target.value) } });
            await openTodayTasks();
        });
        $("[data-jump-task]", article).addEventListener("click", () => jumpToTodayTask(task));
        $("[data-complete-task]", article).addEventListener("click", async () => {
            await api(`/notifications/tasks/${task.id}`, { method: "PATCH", body: { completed: true } });
            toast("A teendő elkészült.");
            await openTodayTasks();
        });
        $("[data-delete-task]", article).addEventListener("click", async () => {
            if (!confirm("Biztosan törlöd ezt a teendőt?")) return;
            await api(`/notifications/tasks/${task.id}`, { method: "DELETE" });
            await openTodayTasks();
        });
    });
}

async function downloadFile(path, name) {
    try {
        const blob = await api(path);
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = name;
        link.click();
        URL.revokeObjectURL(url);
        toast("Az export elkészült.");
    } catch (error) {
        toast(error.message, true);
    }
}

function openAccount() {
    showModal(
        "Fiók és jelszó",
        state.user?.display_name || state.user?.email || "Felhasználói fiók",
        `<section class="account-summary"><div><span>Felhasználó</span><strong>${escapeHtml(state.user?.display_name || "–")}</strong></div><div><span>Szerepkör</span><strong>${escapeHtml(roleLabel(state.user?.role))}</strong></div></section>
        <form id="password-change-form" autocomplete="off">
            <div class="form-grid">
                <label class="span-3">Jelenlegi jelszó<input name="current_password" type="password" autocomplete="current-password" required maxlength="200"></label>
                <label class="span-3">Új jelszó<input name="new_password" type="password" autocomplete="new-password" required minlength="12" maxlength="200"></label>
                <label class="span-3">Új jelszó ismét<input name="new_password_confirmation" type="password" autocomplete="new-password" required minlength="12" maxlength="200"></label>
                <p class="field-help span-3">Legalább 12 karakteres, egyedi jelszót használj. A módosításhoz nem küldünk e-mailt.</p>
                <p id="password-change-error" class="form-error span-3" role="alert"></p>
            </div>
            <div class="modal-actions"><button type="button" data-close class="secondary-button">Bezárás</button><button type="submit" class="primary-button">Jelszó módosítása</button></div>
        </form>`,
    );
    $("#password-change-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const submit = form.querySelector('button[type="submit"]');
        $("#password-change-error").textContent = "";
        submit.disabled = true;
        submit.textContent = "Módosítás…";
        try {
            await api("/auth/change-password", { method: "POST", body: formDataObject(form) });
            closeModal();
            toast("A jelszó módosítása sikerült.");
        } catch (error) {
            $("#password-change-error").textContent = error.message;
            submit.disabled = false;
            submit.textContent = "Jelszó módosítása";
        }
    });
    $("[data-close]", $("#modal")).addEventListener("click", closeModal);
}

$("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submitButton = form.querySelector('button[type="submit"]');
    if (submitButton.disabled) return;
    $("#login-error").textContent = "";
    submitButton.disabled = true;
    submitButton.textContent = "Belépés…";
    try {
        const data = formDataObject(form);
        await api("/auth/login", { method: "POST", body: data });
        form.reset();
        if (!(await bootstrap())) throw new Error("A munkamenet nem nyitható meg.");
    } catch (error) {
        $("#login-error").textContent = error.message || "A bejelentkezés sikertelen.";
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = "Admin Belépés";
    }
});

$("#logout-button").addEventListener("click", async () => { await api("/auth/logout", { method: "POST" }); showLoginView(); });
$("#back-projects").addEventListener("click", () => loadProjects());
$("#module-nav").addEventListener("click", (event) => { const button = event.target.closest("[data-module]"); if (button) selectModule(button.dataset.module); });
$("#notification-button").addEventListener("click", openNotifications);
$("#today-tasks-button").addEventListener("click", openTodayTasks);
$("#account-button").addEventListener("click", openAccount);
$("#modal-close").addEventListener("click", closeModal);
$("#modal").addEventListener("click", (event) => { if (event.target === $("#modal")) closeModal(); });
wireAIAssistant();
$("#global-search").addEventListener("input", (event) => { clearTimeout(state.searchTimer); state.searchTimer = setTimeout(() => { if (!state.project) loadProjects(event.target.value.trim()); else if (state.module === "engagements") { const input = $("#eng-search"); if (input) input.value = event.target.value; loadAssignmentTable(); } }, 350); });

$("#guest-login-btn")?.addEventListener("click", async () => {
    const guestButton = $("#guest-login-btn");
    if (guestButton.disabled) return;
    $("#login-error").textContent = "";
    guestButton.disabled = true;
    guestButton.textContent = "Belépés vendégként…";
    try {
        await api("/auth/guest", { method: "POST" });
        if (!(await bootstrap())) throw new Error("A vendég munkamenet nem nyitható meg.");
    } catch (error) {
        $("#login-error").textContent = error.message || "A vendég belépés sikertelen.";
    } finally {
        guestButton.disabled = false;
        guestButton.textContent = "Belépés vendégként (1 kattintás)";
    }
});

showLoginView();
