(function () {
    async function apiRequest(path, options) {
        options = options || {};
        const headers = Object.assign({}, options.headers || {});
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
                if (!confirm("Delete this to-do?")) return;
                const id = btn.dataset.todoId;
                handleAction(btn, () => apiRequest(`/api/todos/${encodeURIComponent(id)}`, { method: "DELETE" }));
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
            const data = Object.fromEntries(new FormData(form).entries());
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

    document.addEventListener("DOMContentLoaded", function () {
        wireToggleRock();
        wireMoveRock();
        wireEditRock();
        wireDeleteRock();
        wireToggleAction();
        wireMoveAction();
        wireToggleTodo();
        wireDeleteTodo();
        wireAddTodo();
        wireAddCompanyRock();
        wireAddPersonRock();
    });
})();
