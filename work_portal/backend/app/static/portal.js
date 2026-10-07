(function () {
    // "You are" picker: a self-reported name sent with every edit so the change
    // log (/changes) can show who made it. Not verified; editing stays open.
    const ACTOR_KEY = "l10_actor";
    function getActor() {
        try { return localStorage.getItem(ACTOR_KEY) || ""; } catch (e) { return ""; }
    }
    function wireActorPicker() {
        const sel = document.getElementById("actor-select");
        if (!sel) return;
        const cur = getActor();
        if (cur) sel.value = cur;
        sel.addEventListener("change", function () {
            try { localStorage.setItem(ACTOR_KEY, sel.value); } catch (e) { /* private mode */ }
        });
    }

    async function apiRequest(path, options) {
        options = options || {};
        const headers = Object.assign({}, options.headers || {});
        const actor = getActor();
        if (actor) headers["X-Actor"] = actor;
        if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
        const res = await fetch(path, Object.assign({}, options, { headers }));
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res;
    }

    async function handleAction(btn, fn) {
        btn.disabled = true;
        btn.classList.add("is-loading");
        try {
            await fn();
            window.location.reload();
        } catch (err) {
            alert("Failed: " + err.message);
            btn.disabled = false;
            btn.classList.remove("is-loading");
        }
    }

    function wireToggleRock() {
        document.querySelectorAll("button.check[data-rock-id]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const id = btn.dataset.rockId;
                handleAction(btn, () => apiRequest(`/api/rocks/${encodeURIComponent(id)}/toggle`, { method: "POST" }));
            });
        });
    }

    function wireMoveRock() {
        document.querySelectorAll(".move-rock-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (!confirm("Move this rock to To-Dos? It will be removed from quarterly rocks.")) return;
                const id = btn.dataset.rockId;
                handleAction(btn, () => apiRequest(`/api/rocks/${encodeURIComponent(id)}/move`, { method: "POST" }));
            });
        });
    }

    function wireEditRock() {
        document.querySelectorAll(".edit-rock-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const id = btn.dataset.rockId;
                const form = document.querySelector(`.edit-rock-form[data-rock-id="${id}"]`);
                if (!form) return;
                form.classList.remove("hidden");
                const first = form.querySelector("input[name=title]");
                if (first) first.focus();
            });
        });
        document.querySelectorAll(".cancel-edit-rock").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const form = btn.closest(".edit-rock-form");
                if (form) form.classList.add("hidden");
            });
        });
        document.querySelectorAll(".edit-rock-form").forEach(function (form) {
            form.addEventListener("submit", async function (e) {
                e.preventDefault();
                const id = form.dataset.rockId;
                const data = Object.fromEntries(new FormData(form).entries());
                const submit = form.querySelector("button[type=submit]");
                handleAction(submit, () => apiRequest(`/api/rocks/${encodeURIComponent(id)}`, {
                    method: "PATCH",
                    body: JSON.stringify(data),
                }));
            });
        });
    }

    function wireDeleteRock() {
        document.querySelectorAll(".delete-rock-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (!confirm("Delete this rock? This cannot be undone.")) return;
                const id = btn.dataset.rockId;
                handleAction(btn, () => apiRequest(`/api/rocks/${encodeURIComponent(id)}`, { method: "DELETE" }));
            });
        });
    }

    function showForm(form) {
        if (!form) return;
        form.classList.remove("hidden");
        const first = form.querySelector("input");
        if (first) first.focus();
    }

    function wireFiles() {
        // --- add a file link ---
        document.querySelectorAll(".file-add-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const wrap = btn.closest(".rock-files");
                showForm(wrap && wrap.querySelector(".add-file-form"));
            });
        });
        document.querySelectorAll(".cancel-add-file").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const form = btn.closest(".add-file-form");
                if (form) { form.classList.add("hidden"); form.reset(); }
            });
        });
        document.querySelectorAll(".add-file-form").forEach(function (form) {
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                const id = form.dataset.rockId;
                const data = Object.fromEntries(new FormData(form).entries());
                const submit = form.querySelector("button[type=submit]");
                handleAction(submit, () => apiRequest(`/api/rocks/${encodeURIComponent(id)}/files`, {
                    method: "POST",
                    body: JSON.stringify(data),
                }));
            });
        });

        // --- edit a file link ---
        document.querySelectorAll(".file-edit-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const rid = btn.dataset.rockId, fid = btn.dataset.fileId;
                showForm(document.querySelector(
                    `.edit-file-form[data-rock-id="${rid}"][data-file-id="${fid}"]`));
            });
        });
        document.querySelectorAll(".cancel-edit-file").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const form = btn.closest(".edit-file-form");
                if (form) form.classList.add("hidden");
            });
        });
        document.querySelectorAll(".edit-file-form").forEach(function (form) {
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                const rid = form.dataset.rockId, fid = form.dataset.fileId;
                const data = Object.fromEntries(new FormData(form).entries());
                const submit = form.querySelector("button[type=submit]");
                handleAction(submit, () => apiRequest(
                    `/api/rocks/${encodeURIComponent(rid)}/files/${encodeURIComponent(fid)}`, {
                    method: "PATCH",
                    body: JSON.stringify(data),
                }));
            });
        });

        // --- remove a file link ---
        document.querySelectorAll(".file-remove-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (!confirm("Remove this file link?")) return;
                const rid = btn.dataset.rockId, fid = btn.dataset.fileId;
                handleAction(btn, () => apiRequest(
                    `/api/rocks/${encodeURIComponent(rid)}/files/${encodeURIComponent(fid)}`,
                    { method: "DELETE" }));
            });
        });

        // Esc closes any open file form (Enter submits via the form default).
        document.querySelectorAll(".add-file-form, .edit-file-form").forEach(function (form) {
            form.addEventListener("keydown", function (e) {
                if (e.key === "Escape") { e.preventDefault(); form.classList.add("hidden"); }
            });
        });
    }

    function wireToggleAction() {
        document.querySelectorAll("button.check[data-action-id]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const mid = btn.dataset.meetingId;
                const aid = btn.dataset.actionId;
                handleAction(btn, () => apiRequest(
                    `/api/action/${encodeURIComponent(mid)}/${encodeURIComponent(aid)}/toggle`,
                    { method: "POST" }
                ));
            });
        });
    }

    function wireMoveAction() {
        document.querySelectorAll(".move-action-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const mid = btn.dataset.meetingId;
                const aid = btn.dataset.actionId;
                handleAction(btn, () => apiRequest(
                    `/api/action/${encodeURIComponent(mid)}/${encodeURIComponent(aid)}/move`,
                    { method: "POST" }
                ));
            });
        });
    }

    function wireToggleTodo() {
        document.querySelectorAll("button.check[data-todo-id]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const id = btn.dataset.todoId;
                handleAction(btn, () => apiRequest(`/api/todos/${encodeURIComponent(id)}/toggle`, { method: "POST" }));
            });
        });
    }

    function wireDeleteTodo() {
        document.querySelectorAll(".delete-todo-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (!confirm("Delete permanently? Only for a to-do entered by mistake. To stop working on it, use Drop instead.")) return;
                const id = btn.dataset.todoId;
                handleAction(btn, () => apiRequest(`/api/todos/${encodeURIComponent(id)}`, { method: "DELETE" }));
            });
        });
    }

    // To-do forms: owners is a multi-pick, so FormData.entries() would keep only one.
    function todoFormData(form) {
        const fd = new FormData(form);
        const data = Object.fromEntries(fd.entries());
        data.owners = fd.getAll("owners");
        return data;
    }

    function wireDropTodo() {
        document.querySelectorAll(".drop-todo-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const form = document.querySelector(`.drop-todo-form[data-todo-id="${btn.dataset.todoId}"]`);
                if (!form) return;
                form.classList.remove("hidden");
                const input = form.querySelector("input[name=reason]");
                if (input) input.focus();
            });
        });
        document.querySelectorAll(".cancel-drop-todo").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const form = btn.closest(".drop-todo-form");
                if (form) form.classList.add("hidden");
            });
        });
        document.querySelectorAll(".drop-todo-form").forEach(function (form) {
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                const id = form.dataset.todoId;
                const reason = (form.querySelector("input[name=reason]") || {}).value || "";
                const submit = form.querySelector("button[type=submit]");
                handleAction(submit, () => apiRequest(`/api/todos/${encodeURIComponent(id)}/drop`, {
                    method: "POST",
                    body: JSON.stringify({ reason: reason }),
                }));
            });
        });
        document.querySelectorAll(".restore-todo-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const id = btn.dataset.todoId;
                handleAction(btn, () => apiRequest(`/api/todos/${encodeURIComponent(id)}/restore`, { method: "POST" }));
            });
        });
    }

    function wireEditTodo() {
        document.querySelectorAll(".edit-todo-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const id = btn.dataset.todoId;
                const form = document.querySelector(`.edit-todo-form[data-todo-id="${id}"]`);
                if (!form) return;
                form.classList.remove("hidden");
                const first = form.querySelector("input[name=task]");
                if (first) first.focus();
            });
        });
        document.querySelectorAll(".cancel-edit-todo").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const form = btn.closest(".edit-todo-form");
                if (form) form.classList.add("hidden");
            });
        });
        document.querySelectorAll(".edit-todo-form").forEach(function (form) {
            form.addEventListener("submit", async function (e) {
                e.preventDefault();
                const id = form.dataset.todoId;
                const data = todoFormData(form);
                const submit = form.querySelector("button[type=submit]");
                handleAction(submit, () => apiRequest(`/api/todos/${encodeURIComponent(id)}`, {
                    method: "PATCH",
                    body: JSON.stringify(data),
                }));
            });
        });
    }

    function toggleForm(formId, openBtnId, cancelBtnId) {
        const form = document.getElementById(formId);
        const openBtn = document.getElementById(openBtnId);
        const cancelBtn = document.getElementById(cancelBtnId);
        if (!form || !openBtn) return;
        openBtn.addEventListener("click", function () {
            form.classList.remove("hidden");
            const first = form.querySelector("input[required], input");
            if (first) first.focus();
        });
        if (cancelBtn) {
            cancelBtn.addEventListener("click", function () {
                form.classList.add("hidden");
                form.reset();
            });
        }
    }

    function wireAddTodo() {
        toggleForm("add-todo-form", "add-todo-open", "add-todo-cancel");
        const form = document.getElementById("add-todo-form");
        if (!form) return;
        form.addEventListener("submit", async function (e) {
            e.preventDefault();
            const data = todoFormData(form);
            const submit = form.querySelector("button[type=submit]");
            handleAction(submit, () => apiRequest("/api/todos", {
                method: "POST",
                body: JSON.stringify(data),
            }));
        });
    }

    function wireAddCompanyRock() {
        toggleForm("add-company-rock-form", "add-company-rock-open", "add-company-rock-cancel");
        const form = document.getElementById("add-company-rock-form");
        if (!form) return;
        form.addEventListener("submit", async function (e) {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(form).entries());
            const submit = form.querySelector("button[type=submit]");
            handleAction(submit, () => apiRequest("/api/company_rocks/add", {
                method: "POST",
                body: JSON.stringify(data),
            }));
        });
    }

    function wireAddPersonRock() {
        document.querySelectorAll(".add-rock-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const card = btn.closest(".person-card");
                if (!card) return;
                const form = card.querySelector(".add-rock-form");
                if (!form) return;
                form.classList.remove("hidden");
                const first = form.querySelector("input[required], input");
                if (first) first.focus();
            });
        });
        document.querySelectorAll(".cancel-add-rock").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const form = btn.closest(".add-rock-form");
                if (form) { form.classList.add("hidden"); form.reset(); }
            });
        });
        document.querySelectorAll(".add-rock-form").forEach(function (form) {
            form.addEventListener("submit", async function (e) {
                e.preventDefault();
                const owner = form.dataset.owner;
                const category = form.dataset.category;
                const data = Object.fromEntries(new FormData(form).entries());
                data.category = category;
                const submit = form.querySelector("button[type=submit]");
                handleAction(submit, () => apiRequest(`/api/rocks/${encodeURIComponent(owner)}/add`, {
                    method: "POST",
                    body: JSON.stringify(data),
                }));
            });
        });
    }

    function wireScorecardRefresh() {
        const btn = document.getElementById("scorecard-refresh");
        if (!btn) return;
        btn.addEventListener("click", function () {
            handleAction(btn, () => apiRequest("/api/scorecard/refresh", { method: "POST" }));
        });
    }

    // ---- IDS issues list ----
    function wireIssues() {
        toggleForm("add-issue-form", "add-issue-open", "add-issue-cancel");
        const add = document.getElementById("add-issue-form");
        if (add) add.addEventListener("submit", function (e) {
            e.preventDefault();
            handleAction(add.querySelector("button[type=submit]"),
                () => apiRequest("/api/issues", { method: "POST", body: JSON.stringify(todoFormData(add)) }));
        });
        document.querySelectorAll(".issue-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const li = btn.closest(".issue");
                li.querySelectorAll("form").forEach(f => f.classList.add("hidden"));
                showForm(li.querySelector("." + btn.dataset.form));
            });
        });
        document.querySelectorAll(".cancel-issue-form").forEach(function (btn) {
            btn.addEventListener("click", function () { btn.closest("form").classList.add("hidden"); });
        });
        const id = f => encodeURIComponent(f.dataset.issueId);
        document.querySelectorAll(".edit-issue-form").forEach(function (form) {
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                handleAction(form.querySelector("button[type=submit]"),
                    () => apiRequest(`/api/issues/${id(form)}`, { method: "PATCH", body: JSON.stringify(todoFormData(form)) }));
            });
        });
        document.querySelectorAll(".solve-issue-form").forEach(function (form) {
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                const data = { resolution: form.resolution.value, make_todo: form.make_todo.checked };
                handleAction(form.querySelector("button[type=submit]"),
                    () => apiRequest(`/api/issues/${id(form)}/solve`, { method: "POST", body: JSON.stringify(data) }));
            });
        });
        document.querySelectorAll(".drop-issue-form").forEach(function (form) {
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                handleAction(form.querySelector("button[type=submit]"),
                    () => apiRequest(`/api/issues/${id(form)}/drop`, { method: "POST", body: JSON.stringify({ reason: form.reason.value }) }));
            });
        });
        document.querySelectorAll(".reopen-issue-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                handleAction(btn, () => apiRequest(`/api/issues/${id(btn)}/reopen`, { method: "POST" }));
            });
        });
        document.querySelectorAll(".delete-issue-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (!confirm("Delete this issue? Use only for one entered by mistake.")) return;
                handleAction(btn, () => apiRequest(`/api/issues/${id(btn)}`, { method: "DELETE" }));
            });
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        wireActorPicker();
        wireScorecardRefresh();
        wireToggleRock();
        wireMoveRock();
        wireEditRock();
        wireDeleteRock();
        wireFiles();
        wireToggleAction();
        wireMoveAction();
        wireToggleTodo();
        wireDeleteTodo();
        wireEditTodo();
        wireDropTodo();
        wireAddTodo();
        wireAddCompanyRock();
        wireAddPersonRock();
        wireIssues();
    });
})();
