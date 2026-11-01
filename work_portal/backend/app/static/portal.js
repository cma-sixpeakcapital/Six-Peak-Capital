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

    function wireKeepTodo() {
        document.querySelectorAll(".keep-todo-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const mid = btn.dataset.meetingId;
                const aid = btn.dataset.actionId;
                handleAction(btn, () => apiRequest(
                    `/api/action/${encodeURIComponent(mid)}/${encodeURIComponent(aid)}/keep-todo`,
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
                const form = btn.closest("li.todo").querySelector(".drop-todo-form");
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
                const form = btn.closest("li.todo").querySelector(".edit-todo-form");
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


    // ---- Construction inputs (contract dates, cause codes, utilization hours) ----
    function ciBand(pct) {
        if (pct === null || isNaN(pct)) return "";
        if (pct >= 80 && pct <= 100) return "u-green";
        if ((pct >= 70 && pct < 80) || (pct > 100 && pct <= 110)) return "u-yellow";
        return "u-red";
    }
    function ciRecalc() {
        const req = document.getElementById("ci-required");
        const av = document.getElementById("ci-available");
        if (!req || !av) return;
        const reqTot = {};
        req.querySelectorAll("tbody tr").forEach(function (tr) {
            let rowTot = 0;
            tr.querySelectorAll("input.ci-h").forEach(function (inp) {
                const v = parseFloat(inp.value) || 0;
                rowTot += v;
                reqTot[inp.dataset.role] = (reqTot[inp.dataset.role] || 0) + v;
            });
            const cell = tr.querySelector(".ci-rowtot");
            if (cell) cell.textContent = rowTot ? rowTot.toFixed(1).replace(/\.0$/, "") : "0";
        });
        const avTot = {};
        av.querySelectorAll("tbody tr").forEach(function (tr) {
            const role = tr.querySelector("select[name=role]").value;
            avTot[role] = (avTot[role] || 0) + (parseFloat(tr.querySelector("input[name=hours]").value) || 0);
        });
        req.querySelectorAll(".ci-req-tot").forEach(function (td) {
            const v = reqTot[td.dataset.role] || 0;
            td.textContent = v ? v.toFixed(1).replace(/\.0$/, "") : "0";
        });
        document.querySelectorAll("#ci-util-preview .ci-util").forEach(function (td) {
            const r = reqTot[td.dataset.role] || 0, a = avTot[td.dataset.role] || 0;
            td.className = "num ci-util";
            if (!a) { td.textContent = r ? "no hours available" : "—"; return; }
            const pct = Math.round(100 * r / a);
            td.textContent = pct + "%";
            td.classList.add(ciBand(pct));
        });
    }
    function ciRowDelete(scope) {
        scope.querySelectorAll(".ci-row-del").forEach(function (btn) {
            if (btn.dataset.wired) return;
            btn.dataset.wired = "1";
            btn.addEventListener("click", function () { btn.closest("tr").remove(); ciRecalc(); });
        });
    }
    function wireConstruction() {
        const jobs = document.getElementById("ci-jobs");
        if (!jobs) return;
        ciRowDelete(document);
        document.querySelectorAll("#ci-required input, #ci-available input, #ci-available select").forEach(function (el) {
            el.addEventListener("input", ciRecalc);
            el.addEventListener("change", ciRecalc);
        });
        ciRecalc();

        const addJob = document.getElementById("ci-job-add");
        if (addJob) addJob.addEventListener("click", function () {
            const tpl = jobs.querySelector("tbody tr");
            const tr = tpl ? tpl.cloneNode(true) : null;
            if (!tr) { window.location.reload(); return; }
            tr.querySelectorAll("input").forEach(function (i) { if (i.type === "checkbox") i.checked = true; else i.value = ""; });
            tr.querySelectorAll("select").forEach(function (sel) { sel.value = ""; });
            tr.querySelectorAll(".ci-row-del").forEach(function (b) { delete b.dataset.wired; });
            jobs.querySelector("tbody").appendChild(tr);
            ciRowDelete(tr);
            tr.querySelector("input[name=job]").focus();
        });

        const saveJobs = document.getElementById("ci-jobs-save");
        if (saveJobs) saveJobs.addEventListener("click", function () {
            const rows = [];
            jobs.querySelectorAll("tbody tr").forEach(function (tr) {
                const g = function (n) { const el = tr.querySelector("[name=" + n + "]"); return el ? el.value.trim() : ""; };
                if (!g("job")) return;
                rows.push({ job: g("job"), active: tr.querySelector("[name=active]").checked, client: g("client"),
                    contract_completion: g("contract_completion"), contract_source: g("contract_source"),
                    pay_app_through: g("pay_app_through"), cause_code: g("cause_code"),
                    contingency_note: g("contingency_note"), notes: g("notes") });
            });
            const roles = (document.getElementById("ci-roles").value || "").split(",").map(function (x) { return x.trim(); }).filter(Boolean);
            handleAction(saveJobs, () => apiRequest("/api/construction_inputs/jobs", { method: "PUT", body: JSON.stringify({ jobs: rows, roles: roles }) }));
        });

        const addAvail = document.getElementById("ci-avail-add");
        const avail = document.getElementById("ci-available");
        if (addAvail && avail) addAvail.addEventListener("click", function () {
            const tbody = avail.querySelector("tbody");
            const roles = Array.from(document.querySelectorAll("#ci-required thead th")).slice(1, -1).map(function (th) { return th.textContent.trim(); });
            const tr = document.createElement("tr");
            tr.setAttribute("data-avail-row", "");
            tr.innerHTML = '<td><input class="ci-in" name="person" size="18"></td><td><select class="ci-in" name="role">' +
                roles.map(function (r) { return '<option value="' + r.replace(/"/g, "&quot;") + '">' + r + '</option>'; }).join("") +
                '</select></td><td class="num"><input class="ci-in ci-h" type="number" name="hours" min="0" step="0.5"></td><td><button type="button" class="link-btn ci-row-del" title="Remove">×</button></td>';
            tbody.appendChild(tr);
            tr.querySelectorAll("input, select").forEach(function (el) { el.addEventListener("input", ciRecalc); el.addEventListener("change", ciRecalc); });
            ciRowDelete(tr);
            tr.querySelector("input[name=person]").focus();
        });

        const saveUtil = document.getElementById("ci-util-save");
        if (saveUtil) saveUtil.addEventListener("click", function () {
            const req = document.getElementById("ci-required");
            const month = req.dataset.month;
            const required = {};
            req.querySelectorAll("tbody tr").forEach(function (tr) {
                const job = tr.dataset.job, byRole = {};
                tr.querySelectorAll("input.ci-h").forEach(function (inp) { if (inp.value !== "") byRole[inp.dataset.role] = parseFloat(inp.value); });
                if (Object.keys(byRole).length) required[job] = byRole;
            });
            const available = [];
            avail.querySelectorAll("tbody tr").forEach(function (tr) {
                const person = tr.querySelector("input[name=person]").value.trim();
                if (!person) return;
                available.push({ person: person, role: tr.querySelector("select[name=role]").value,
                    hours: parseFloat(tr.querySelector("input[name=hours]").value) || 0 });
            });
            const note = (document.getElementById("ci-util-note") || {}).value || "";
            handleAction(saveUtil, () => apiRequest("/api/construction_inputs/utilization/" + encodeURIComponent(month),
                { method: "PUT", body: JSON.stringify({ required: required, available: available, note: note }) }));
        });

        document.querySelectorAll(".ci-notice-remove").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (!confirm("Remove this note for everyone?")) return;
                handleAction(btn, () => apiRequest("/api/construction_inputs/notices/" + encodeURIComponent(btn.dataset.noteId), { method: "DELETE" }));
            });
        });
        // ---- Third-party awards (Tom) ----
        const awards = document.getElementById("ci-awards");
        function awardsTotal() {
            if (!awards) return;
            let t = 0;
            awards.querySelectorAll("tbody tr").forEach(function (tr) {
                if (tr.querySelector("select[name=status]").value !== "awarded") return;
                t += parseFloat(tr.querySelector("input[name=expected_value]").value) || 0;
            });
            const el = document.getElementById("ci-awards-total");
            if (el) el.textContent = "$" + Math.round(t).toLocaleString();
        }
        if (awards) {
            awards.querySelectorAll("input, select").forEach(function (el) { el.addEventListener("input", awardsTotal); el.addEventListener("change", awardsTotal); });
            awardsTotal();
            const addAward = document.getElementById("ci-award-add");
            if (addAward) addAward.addEventListener("click", function () {
                const tr = document.createElement("tr");
                tr.setAttribute("data-award-row", "");
                tr.innerHTML = '<td><input class="ci-in" name="project" size="16"></td><td><input class="ci-in" name="client" size="14"></td>' +
                    '<td><input class="ci-in" type="date" name="award_date"></td><td class="num"><input class="ci-in ci-money" type="number" min="0" step="1000" name="expected_value"></td>' +
                    '<td><input class="ci-in" type="date" name="expected_signing"></td><td><input class="ci-in" name="kpi_job" size="10" placeholder="as in KPI workbook"></td>' +
                    '<td><select class="ci-in" name="status"><option value="awarded">awarded</option><option value="signed">signed</option><option value="lost">lost</option></select></td>' +
                    '<td><input class="ci-in" name="notes" size="18"></td><td><button type="button" class="link-btn ci-row-del" title="Remove">×</button></td>';
                awards.querySelector("tbody").appendChild(tr);
                tr.querySelectorAll("input, select").forEach(function (el) { el.addEventListener("input", awardsTotal); el.addEventListener("change", awardsTotal); });
                ciRowDelete(tr);
                tr.querySelector("input[name=project]").focus();
            });
            const saveAwards = document.getElementById("ci-awards-save");
            if (saveAwards) saveAwards.addEventListener("click", function () {
                const rows = [];
                awards.querySelectorAll("tbody tr").forEach(function (tr) {
                    const g = function (n) { const el = tr.querySelector("[name=" + n + "]"); return el ? el.value.trim() : ""; };
                    if (!g("project")) return;
                    rows.push({ project: g("project"), client: g("client"), award_date: g("award_date"),
                        expected_value: g("expected_value"), expected_signing: g("expected_signing"),
                        kpi_job: g("kpi_job"), status: g("status"), notes: g("notes") });
                });
                handleAction(saveAwards, () => apiRequest("/api/construction_inputs/awards", { method: "PUT", body: JSON.stringify({ awards: rows }) }));
            });
        }

        const clearNotice = document.getElementById("ci-notice-clear");
        if (clearNotice) clearNotice.addEventListener("click", function () {
            if (!confirm("Remove the note for everyone?")) return;
            handleAction(clearNotice, () => apiRequest("/api/construction_inputs/notice", { method: "PUT", body: JSON.stringify({ text: "" }) }));
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        wireActorPicker();
        wireConstruction();
        wireScorecardRefresh();
        wireToggleRock();
        wireMoveRock();
        wireEditRock();
        wireDeleteRock();
        wireFiles();
        wireToggleAction();
        wireMoveAction();
        wireKeepTodo();
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
