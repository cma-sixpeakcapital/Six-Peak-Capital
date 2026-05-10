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

    // --- Goals ---
    function wireToggleGoal() {
        document.querySelectorAll("button.check[data-goal-id]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const id = btn.dataset.goalId;
                handleAction(btn, () => apiRequest(`/api/goals/${encodeURIComponent(id)}/toggle`, { method: "POST" }));
            });
        });
    }

    function wireMoveGoal() {
        document.querySelectorAll(".move-goal-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (!confirm("Move this goal to To-Dos? It will be removed from the goals list.")) return;
                const id = btn.dataset.goalId;
                handleAction(btn, () => apiRequest(`/api/goals/${encodeURIComponent(id)}/move`, { method: "POST" }));
            });
        });
    }

    function wireEditGoal() {
        document.querySelectorAll(".edit-goal-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const id = btn.dataset.goalId;
                const form = document.querySelector(`.edit-goal-form[data-goal-id="${id}"]`);
                if (!form) return;
                form.classList.remove("hidden");
                const first = form.querySelector("input[name=title]");
                if (first) first.focus();
            });
        });
        document.querySelectorAll(".cancel-edit-goal").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const form = btn.closest(".edit-goal-form");
                if (form) form.classList.add("hidden");
            });
        });
        document.querySelectorAll(".edit-goal-form").forEach(function (form) {
            form.addEventListener("submit", async function (e) {
                e.preventDefault();
                const id = form.dataset.goalId;
                const data = Object.fromEntries(new FormData(form).entries());
                const submit = form.querySelector("button[type=submit]");
                handleAction(submit, () => apiRequest(`/api/goals/${encodeURIComponent(id)}`, {
                    method: "PATCH",
                    body: JSON.stringify(data),
                }));
            });
        });
    }

    function wireDeleteGoal() {
        document.querySelectorAll(".delete-goal-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (!confirm("Delete this goal? This cannot be undone.")) return;
                const id = btn.dataset.goalId;
                handleAction(btn, () => apiRequest(`/api/goals/${encodeURIComponent(id)}`, { method: "DELETE" }));
            });
        });
    }

    function wireAddGoal() {
        toggleForm("add-goal-form", "add-goal-open", "add-goal-cancel");
        const form = document.getElementById("add-goal-form");
        if (!form) return;
        form.addEventListener("submit", async function (e) {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(form).entries());
            const submit = form.querySelector("button[type=submit]");
            handleAction(submit, () => apiRequest("/api/goals/add", {
                method: "POST",
                body: JSON.stringify(data),
            }));
        });
    }

    // --- Action items ---
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

    // --- Todos ---
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

    document.addEventListener("DOMContentLoaded", function () {
        wireToggleGoal();
        wireMoveGoal();
        wireEditGoal();
        wireDeleteGoal();
        wireAddGoal();
        wireToggleAction();
        wireMoveAction();
        wireToggleTodo();
        wireDeleteTodo();
        wireAddTodo();
    });
})();
